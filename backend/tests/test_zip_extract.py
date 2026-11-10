import io
import stat
import zipfile

import pytest

from app.ingestion.workspace import IngestionError, safe_join
from app.ingestion.zip_extract import extract_zip


def _zip(tmp_path, entries, name="a.zip"):
    p = tmp_path / name
    with zipfile.ZipFile(p, "w", zipfile.ZIP_DEFLATED) as zf:
        for entry in entries:
            if isinstance(entry, zipfile.ZipInfo):
                zf.writestr(entry, "x")
            else:
                zf.writestr(entry[0], entry[1])
    return p


def test_extracts_and_unwraps_single_root(tmp_path):
    archive = _zip(tmp_path, [("proj-main/app.py", "print(1)"), ("proj-main/lib/x.py", "")])
    dest = tmp_path / "out"
    dest.mkdir()
    extract_zip(archive, dest)
    assert (dest / "app.py").read_text() == "print(1)"
    assert (dest / "lib" / "x.py").exists()


@pytest.mark.parametrize("name", ["../evil.py", "/etc/passwd", "a/../../evil.py", "C:/win.ini"])
def test_rejects_path_traversal(tmp_path, name):
    archive = _zip(tmp_path, [(name, "x")])
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(IngestionError):
        extract_zip(archive, dest)
    assert not (tmp_path / "evil.py").exists()


def test_rejects_symlinks(tmp_path):
    info = zipfile.ZipInfo("link")
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    archive = _zip(tmp_path, [info])
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(IngestionError, match="symlink"):
        extract_zip(archive, dest)


def test_rejects_zip_bomb_ratio(tmp_path):
    archive = _zip(tmp_path, [("big.txt", "0" * 5_000_000)])
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(IngestionError, match="ratio|size"):
        extract_zip(archive, dest)


def test_rejects_too_many_files(tmp_path, monkeypatch):
    monkeypatch.setenv("AUDITOR_MAX_FILES", "3")
    from app.core.config import get_settings
    get_settings.cache_clear()
    archive = _zip(tmp_path, [(f"f{i}.py", "") for i in range(5)])
    dest = tmp_path / "out"
    dest.mkdir()
    with pytest.raises(IngestionError, match="entries"):
        extract_zip(archive, dest)


def test_rejects_non_zip(tmp_path):
    p = tmp_path / "x.zip"
    p.write_bytes(b"not a zip")
    with pytest.raises(IngestionError):
        extract_zip(p, tmp_path)


def test_safe_join(tmp_path):
    assert safe_join(tmp_path, "a/b.py") == (tmp_path / "a/b.py").resolve()
    for bad in ("../x", "a/../../x", "x\x00y"):
        with pytest.raises(ValueError):
            safe_join(tmp_path, bad)
    (tmp_path / "link").symlink_to("/etc")
    with pytest.raises(ValueError):
        safe_join(tmp_path, "link/passwd")


def test_zip_bytes_helper_roundtrip():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.py", "1")
    assert zipfile.is_zipfile(io.BytesIO(buf.getvalue()))
