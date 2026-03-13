from app.videos.validation import validate_magic_bytes


def test_invalid_magic_bytes(tmp_path):
    f = tmp_path / "fake.mp4"
    f.write_bytes(b"this is not a video file")
    assert validate_magic_bytes(str(f)) is False


def test_text_file_rejected(tmp_path):
    f = tmp_path / "script.mp4"
    f.write_bytes(b"#!/bin/bash\nrm -rf /")
    assert validate_magic_bytes(str(f)) is False


def test_empty_file_rejected(tmp_path):
    f = tmp_path / "empty.mp4"
    f.write_bytes(b"")
    assert validate_magic_bytes(str(f)) is False
