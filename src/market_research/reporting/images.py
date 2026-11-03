"""Small cached product-source images; no provider/API calls and no arbitrary URLs."""
import hashlib
import ipaddress
import os
import socket
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, HTTPRedirectHandler

from ..common import ROOT

DOMAINS = ("media-amazon.com", "ssl-images-amazon.com", "walmartimages.com", "ebayimg.com", "etsystatic.com", "gstatic.com")
MAX_BYTES = 3_000_000
MAX_PIXELS = 20_000_000
TIMEOUT_SECONDS = 10
_runtime_lock = threading.Lock()


class ImageError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def allowed(url):
    try:
        p = urlsplit(url)
        host = (p.hostname or "").lower()
        if p.scheme != "https" or p.username or p.password or p.port not in {None, 443}:
            return False
        try:
            ipaddress.ip_address(host)
            return False
        except ValueError:
            pass
        return any(host == d or host.endswith("." + d) for d in DOMAINS)
    except (ValueError, TypeError):
        return False


class Redirect(HTTPRedirectHandler):
    max_redirections = 3
    max_repeats = 2

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed(newurl):
            raise ValueError("Ảnh chuyển tới host không được phép")
        public_host(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def public_host(url):
    """The fixed source hosts must still resolve to public addresses."""
    host = urlsplit(url).hostname
    addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(row[4][0]).is_global for row in addresses):
        raise ValueError("Host ảnh không phân giải tới địa chỉ công khai")


def pillow():
    """Load the same workspace-scoped optional runtime as the PDF exporter."""
    try:
        from PIL import Image
    except ImportError:
        with _runtime_lock:
            local = ROOT / ".artifact-runtime/pdf-deps"
            if local.is_dir() and str(local) not in sys.path:
                sys.path.append(str(local))
            from PIL import Image
    return Image


def verify_image(body):
    if not isinstance(body, bytes):
        raise ImageError("invalid_image", "Nguồn chưa trả nội dung ảnh dạng byte")
    if len(body) > MAX_BYTES:
        raise ImageError("byte_limit", "Ảnh nguồn vượt 3 MB")
    Image = pillow()
    try:
        with Image.open(BytesIO(body)) as picture:
            if picture.format not in {"JPEG", "PNG", "WEBP", "GIF"}:
                raise ImageError("unsupported_format", "Nguồn không trả ảnh JPEG/PNG/WebP/GIF được hỗ trợ")
            if picture.width <= 0 or picture.height <= 0 or picture.width * picture.height > MAX_PIXELS:
                raise ImageError("pixel_limit", "Ảnh nguồn vượt giới hạn 20 triệu pixel")
            picture.verify()
    except ImageError:
        raise
    except Exception as error:
        raise ImageError("invalid_image", "Ảnh nguồn bị hỏng hoặc không giải mã được") from error


def normalize_image(body, *, preserve_compatible=False):
    """Keep the first source frame in a verified, PDF-compatible raster format."""
    verify_image(body)
    Image = pillow()
    with Image.open(BytesIO(body)) as picture:
        source_format, frames = picture.format, getattr(picture, "n_frames", 1)
        picture.seek(0)
        picture.load()
        alpha = "A" in picture.getbands() or "transparency" in picture.info
        suffix = ".png" if source_format in {"PNG", "GIF"} or alpha else ".jpg"
        details = {"source_format": source_format, "width": picture.width, "height": picture.height,
            "source_frames": frames, "frame_policy": "first_frame" if frames > 1 else "single_frame"}
        # Do not recompress the same cached JPEG on every report rebuild.
        if preserve_compatible and frames == 1 and (source_format == "PNG" or source_format == "JPEG" and picture.mode in {"RGB", "L"}):
            return body, suffix, {**details, "bytes": len(body)}
        normalized = picture.convert("RGBA" if alpha else "RGB")
        output = BytesIO()
        normalized.save(output, format="PNG" if suffix == ".png" else "JPEG", **({"optimize": True} if suffix == ".png" else {"quality": 88, "optimize": True}))
        value = output.getvalue()
        if len(value) > MAX_BYTES:
            raise ImageError("byte_limit", "Ảnh sau chuẩn hóa vượt 3 MB")
        return value, suffix, {**details, "bytes": len(value)}


def atomic_write(path, body):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix=path.name + ".", suffix=".tmp", dir=path.parent, delete=False) as stream:
            temporary = stream.name
            stream.write(body)
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def retryable(error):
    if isinstance(error, HTTPError):
        return error.code == 429 or 500 <= error.code <= 599
    reason = error.reason if isinstance(error, URLError) else error
    return isinstance(reason, (TimeoutError, socket.timeout)) or getattr(reason, "winerror", None) in {10054, 10060} or getattr(reason, "errno", None) in {54, 60, 104, 110}


def download(url):
    try:
        public_host(url)
    except ValueError as error:
        raise ImageError("unsafe_host", str(error)) from error
    request = Request(url, headers={"User-Agent": "MarketResearch/2.0", "Accept": "image/jpeg,image/png,image/webp,image/gif"})
    with build_opener(Redirect()).open(request, timeout=TIMEOUT_SECONDS) as response:
        final_url = response.geturl() if callable(getattr(response, "geturl", None)) else url
        if final_url != url:
            if not allowed(final_url):
                raise ImageError("unsafe_redirect", "Ảnh chuyển tới host không được phép")
            public_host(final_url)
        body = response.read(MAX_BYTES + 1)
    return normalize_image(body)


def failure(error):
    if isinstance(error, ImageError):
        return error.code, str(error)
    if isinstance(error, ImportError):
        return "missing_pillow", "Thiếu Pillow để giải mã ảnh; cài gói tùy chọn PDF của dự án"
    if isinstance(error, HTTPError):
        return "http_" + str(error.code), "Máy chủ ảnh trả HTTP " + str(error.code)
    reason = error.reason if isinstance(error, URLError) else error
    if getattr(reason, "winerror", None) == 10061 or getattr(reason, "errno", None) in {61, 111, 10061}:
        return "connection_refused", "Không kết nối được máy chủ ảnh (kết nối bị từ chối); kiểm tra mạng/proxy hoặc quyền mạng của tiến trình"
    if isinstance(reason, (TimeoutError, socket.timeout)):
        return "timeout", "Hết thời gian chờ máy chủ ảnh"
    return "source_error", str(error)[:200]


def asset(run, url, *, allow_network=False):
    """Return output-relative/local image paths or an explicit missing reason."""
    if not allowed(url):
        return {"status": "unavailable", "reason": "Nguồn chưa có ảnh HTTPS thuộc host ảnh được hỗ trợ", "error_code": "unsupported_source", "attempts": 0, "cache_status": "missing"}
    token = hashlib.sha256(url.encode()).hexdigest()[:24]
    cache = run.root / "data/report-images"
    cached_paths = sorted(p for p in cache.glob(token + ".*") if p.suffix in {".jpg", ".png"}) if cache.exists() else []
    attempts, invalid, image_data, cached, cached_body = 0, [], None, None, None
    try:
        for path in cached_paths:
            try:
                with path.open("rb") as stream:
                    cached_body = stream.read(MAX_BYTES + 1)
                image_data = normalize_image(cached_body, preserve_compatible=True)
                cached = path
                break
            except (OSError, ValueError) as error:
                invalid.append(str(error))
        if image_data is None:
            if not allow_network:
                raise ImageError("cache_corrupt" if invalid else "cache_missing", "Ảnh trong cache bị hỏng; chưa cho phép tải lại mạng" if invalid else "Ảnh chưa nằm trong cache; chưa cho phép tải mạng")
            for attempt in range(2):
                attempts += 1
                try:
                    image_data = download(url)
                    break
                except (OSError, ValueError, ImportError) as error:
                    if attempt or not retryable(error):
                        raise
                    time.sleep(.25)
        body, suffix, details = image_data
        target = cache / (token + suffix)
        if cached != target or cached_body != body:
            atomic_write(target, body)
        cached = target
        destination = run.output / "assets" / cached.name
        atomic_write(destination, body)
        return {"status": "available", "path": str(destination), "relative": "assets/" + destination.name, "source": url,
            "attempts": attempts, "cache_status": "repaired" if invalid and attempts else "downloaded" if attempts else "hit", **details}
    except (OSError, ValueError, ImportError) as error:
        code, reason = failure(error)
        return {"status": "unavailable", "reason": "Chưa tải được ảnh nguồn: " + reason, "error_code": code,
            "attempts": attempts, "cache_status": "invalid" if invalid else "missing", "source": url}


def prepare(run, products, *, allow_network=False, limit=15):
    """Prepare bounded product assets concurrently; no research provider is used."""
    if type(limit) is not int or not 0 <= limit <= 100:
        raise ValueError("Giới hạn chuẩn bị ảnh phải từ 0 đến 100")
    unique = {p["product_id"]: p for p in products}
    output, by_url = {}, {}
    for index, (pid, product) in enumerate(unique.items()):
        if index >= limit:
            output[pid] = {"status": "unavailable", "error_code": "not_prepared", "reason": "Ngoài giới hạn ảnh của lần dựng báo cáo", "attempts": 0}
            continue
        url = product.get("thumbnail")
        if not allowed(url):
            output[pid] = asset(run, url)
        else:
            by_url.setdefault(url, []).append(pid)
    if by_url:
        with ThreadPoolExecutor(max_workers=min(4, len(by_url)), thread_name_prefix="report-image") as pool:
            pending = {pool.submit(asset, run, url, allow_network=allow_network): url for url in by_url}
            for future in as_completed(pending):
                url = pending[future]
                try:
                    result = future.result()
                except Exception as error:
                    result = {"status": "unavailable", "error_code": "processing_error", "reason": "Không xử lý được ảnh: " + type(error).__name__, "attempts": 0, "source": url}
                for pid in by_url[url]:
                    output[pid] = dict(result)
    return {pid: output[pid] for pid in unique}
