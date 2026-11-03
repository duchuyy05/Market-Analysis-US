from pathlib import Path
import threading

import pytest

from market_research.common import read_json, write_json


def test_json_reader_finishes_before_atomic_replacement(tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    write_json(path, {"stage": "old"})
    opened, release, finished = threading.Event(), threading.Event(), threading.Event()
    original = Path.read_text
    observed = []

    def hold_reader(file, *args, **kwargs):
        if file == path and not release.is_set():
            opened.set()
            assert release.wait(3)
        return original(file, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", hold_reader)
    reader = threading.Thread(target=lambda: observed.append(read_json(path)))

    def update():
        write_json(path, {"stage": "new"})
        finished.set()

    writer = threading.Thread(target=update)
    reader.start()
    try:
        assert opened.wait(3)
        writer.start()
        assert not finished.wait(0.05)
    finally:
        release.set()
        reader.join(timeout=3)
        if writer.ident is not None:
            writer.join(timeout=3)
    assert observed == [{"stage": "old"}]
    assert finished.is_set()
    assert read_json(path) == {"stage": "new"}


def test_atomic_write_retries_brief_windows_locks(tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    replace = Path.replace
    calls = []

    def locked(file, target):
        calls.append(target)
        if len(calls) <= 2:
            error = PermissionError("temporary sharing violation")
            error.winerror = 32
            raise error
        return replace(file, target)

    monkeypatch.setattr(Path, "replace", locked)
    monkeypatch.setattr("market_research.common.time.sleep", lambda _: None)
    write_json(path, {"status": "complete"})
    assert len(calls) == 3
    assert read_json(path) == {"status": "complete"}
    assert not path.with_suffix(".json.tmp").exists()


def test_atomic_write_preserves_previous_data_on_permanent_denial(tmp_path, monkeypatch):
    path = tmp_path / "manifest.json"
    write_json(path, {"status": "saved"})
    calls = []

    def denied(file, target):
        calls.append(target)
        error = PermissionError("access denied")
        error.winerror = 5
        raise error

    monkeypatch.setattr(Path, "replace", denied)
    monkeypatch.setattr("market_research.common.time.sleep", lambda _: None)
    with pytest.raises(PermissionError):
        write_json(path, {"status": "new"})
    assert len(calls) == 5
    assert read_json(path) == {"status": "saved"}
    assert not path.with_suffix(".json.tmp").exists()
