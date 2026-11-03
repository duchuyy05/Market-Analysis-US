"""Bounded source-photo preparation; CDN/DNS traffic is always mocked."""
import builtins
import hashlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError, URLError
import threading
import time

import pytest

from market_research.reporting import images

URL = "https://m.media-amazon.com/images/product-photo.jpg"


def picture(format="JPEG", *, size=(24, 16)):
    output = BytesIO()
    images.pillow().new("RGB", size, "#5b4cc4").save(output, format=format)
    return output.getvalue()


def run_at(tmp_path):
    return SimpleNamespace(root=tmp_path, output=tmp_path / "outputs" / "test")


def cached_path(run, suffix=".jpg"):
    path = run.root / "data/report-images" / (hashlib.sha256(URL.encode()).hexdigest()[:24] + suffix)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.parametrize("format", ["JPEG", "PNG", "WEBP", "GIF"])
def test_source_formats_normalize_to_verified_pdf_compatible_images(format):
    body, suffix, details = images.normalize_image(picture(format))
    assert suffix in {".png", ".jpg"}
    assert details["source_format"] == format and details["width"] == 24
    with images.pillow().open(BytesIO(body)) as decoded:
        assert decoded.format in {"JPEG", "PNG"}
        decoded.load()


def test_pixel_byte_and_format_limits_are_checked_before_acceptance(monkeypatch):
    with pytest.raises(ValueError, match="3 MB"):
        images.normalize_image(b"x" * (images.MAX_BYTES + 1))
    with pytest.raises(ValueError, match="hỗ trợ"):
        images.normalize_image(picture("BMP"))
    monkeypatch.setattr(images, "MAX_PIXELS", 10)
    with pytest.raises(ValueError, match="pixel"):
        images.normalize_image(picture(size=(4, 3)))


def test_pillow_falls_back_to_scoped_pdf_runtime(tmp_path, monkeypatch):
    local = tmp_path / ".artifact-runtime/pdf-deps"
    local.mkdir(parents=True)
    monkeypatch.setattr(images, "ROOT", tmp_path)
    monkeypatch.setattr(images.sys, "path", list(images.sys.path))
    original = builtins.__import__
    attempts = []
    def import_once_unavailable(name, *args, **kwargs):
        if name == "PIL":
            attempts.append(name)
            if len(attempts) == 1:
                raise ImportError("not in base environment")
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, "__import__", import_once_unavailable)
    assert images.pillow().new("RGB", (1, 1))
    assert str(local) in images.sys.path and len(attempts) == 2


def test_valid_cache_is_verified_and_reused_without_recompressing_jpeg(tmp_path, monkeypatch):
    run = run_at(tmp_path)
    source = picture()
    cache = cached_path(run)
    cache.write_bytes(source)
    monkeypatch.setattr(images, "download", lambda _: pytest.fail("Cache must avoid network"))
    first = images.asset(run, URL)
    second = images.asset(run, URL)
    assert first["status"] == "available" and first["attempts"] == 0
    assert first["cache_status"] == "hit" and second["cache_status"] == "hit"
    assert Path(first["path"]).read_bytes() == source == cache.read_bytes()
    assert not list(run.root.rglob("*.tmp"))


def test_corrupt_cache_is_diagnosed_then_repaired_only_when_network_allowed(tmp_path, monkeypatch):
    run = run_at(tmp_path)
    cache = cached_path(run)
    cache.write_bytes(b"not an image")
    missing = images.asset(run, URL)
    assert missing["status"] == "unavailable" and missing["error_code"] == "cache_corrupt"
    assert missing["attempts"] == 0 and not (run.output / "assets").exists()
    calls = []
    def download(url):
        calls.append(url)
        return images.normalize_image(picture())
    monkeypatch.setattr(images, "download", download)
    repaired = images.asset(run, URL, allow_network=True)
    assert repaired["status"] == "available" and repaired["cache_status"] == "repaired"
    assert repaired["attempts"] == 1 and calls == [URL]
    images.verify_image(cache.read_bytes())


@pytest.mark.parametrize(("status", "expected"), [(403, 1), (404, 1), (429, 2), (500, 2), (503, 2)])
def test_transient_errors_retry_at_most_once_and_permanent_http_errors_do_not(tmp_path, monkeypatch, status, expected):
    calls = []
    def download(url):
        calls.append(url)
        raise HTTPError(url, status, "fixture", {}, None)
    monkeypatch.setattr(images, "download", download)
    monkeypatch.setattr(images.time, "sleep", lambda _: None)
    result = images.asset(run_at(tmp_path), URL, allow_network=True)
    assert result["status"] == "unavailable" and result["attempts"] == expected
    assert len(calls) == expected and result["error_code"] == "http_" + str(status)


def test_timeout_can_recover_on_single_retry(tmp_path, monkeypatch):
    calls = []
    def download(url):
        calls.append(url)
        if len(calls) == 1:
            raise URLError(TimeoutError("fixture timeout"))
        return images.normalize_image(picture("WEBP"))
    monkeypatch.setattr(images, "download", download)
    monkeypatch.setattr(images.time, "sleep", lambda _: None)
    result = images.asset(run_at(tmp_path), URL, allow_network=True)
    assert result["status"] == "available" and result["attempts"] == 2
    assert result["source_format"] == "WEBP"


def test_refused_connection_has_diagnostic_without_futile_retry(tmp_path, monkeypatch):
    calls = []
    def download(url):
        calls.append(url)
        raise URLError(ConnectionRefusedError(10061, "fixture refused"))
    monkeypatch.setattr(images, "download", download)
    result = images.asset(run_at(tmp_path), URL, allow_network=True)
    assert result["error_code"] == "connection_refused" and result["attempts"] == 1
    assert len(calls) == 1


def test_download_checks_public_dns_final_host_and_bounded_request(tmp_path, monkeypatch):
    calls, resolved = [], []
    body = picture("PNG")
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def geturl(self): return URL
        def read(self, limit):
            assert limit == images.MAX_BYTES + 1
            return body
    class Opener:
        def open(self, request, timeout):
            calls.append(request)
            assert timeout == 10
            return Response()
    monkeypatch.setattr(images, "public_host", lambda url: resolved.append(url))
    monkeypatch.setattr(images, "build_opener", lambda _: Opener())
    result = images.asset(run_at(tmp_path), URL, allow_network=True)
    assert result["status"] == "available" and resolved == [URL] and len(calls) == 1
    monkeypatch.setattr(Response, "geturl", lambda _: "https://127.0.0.1/private")
    blocked = images.asset(run_at(tmp_path), URL + "?another", allow_network=True)
    assert blocked["status"] == "unavailable" and blocked["error_code"] == "unsafe_redirect"


def test_atomic_write_failure_leaves_no_partial_cache_or_output(tmp_path, monkeypatch):
    run = run_at(tmp_path)
    monkeypatch.setattr(images, "download", lambda _: images.normalize_image(picture()))
    def fail_replace(*_):
        raise OSError("fixture write failure")
    monkeypatch.setattr(images.os, "replace", fail_replace)
    result = images.asset(run, URL, allow_network=True)
    assert result["status"] == "unavailable"
    assert not list(run.root.rglob("*.tmp")) and not list((run.root / "data/report-images").glob("*.jpg"))


def test_prepare_deduplicates_urls_limits_products_and_uses_at_most_four_workers(tmp_path, monkeypatch):
    lock = threading.Lock()
    calls, active, peak = [], [0], [0]
    def fake_asset(run, url, *, allow_network=False):
        with lock:
            calls.append(url); active[0] += 1; peak[0] = max(peak[0], active[0])
        time.sleep(.02)
        with lock:
            active[0] -= 1
        return {"status": "available", "source": url, "attempts": int(allow_network)}
    monkeypatch.setattr(images, "asset", fake_asset)
    products = [{"product_id": "P" + str(i), "thumbnail": URL + "?" + str(i)} for i in range(7)]
    products[5]["thumbnail"] = products[0]["thumbnail"]
    result = images.prepare(run_at(tmp_path), products, allow_network=True, limit=6)
    assert len(result) == 7 and len(calls) == 5 and 1 < peak[0] <= 4
    assert result["P0"] == result["P5"]
    assert result["P6"]["error_code"] == "not_prepared"
