"""Adversarial offline checks for experimental release bundle integrity."""
import hashlib
import json
from pathlib import Path
import stat
from zipfile import ZipFile, ZipInfo

import pytest

from scripts.verify_release_bundle import REQUIRED_FILES, ReleaseVerificationError, verify_bundle

TAG = "v0.10.0"
SHA = "a" * 40


def _bundle(tmp_path: Path, *, change=None) -> tuple[Path, Path]:
    release = {
        "tag": TAG, "version": "0.10.0", "commit": SHA, "platform": "linux/amd64",
        "image_archive": "spoolmera-image.tar.gz", "image_tag": "spoolmera:test",
        "image_id": "sha256:" + "b" * 64, "schema_version": 12,
    }
    data = {name: (json.dumps(release).encode() if name == "release.json" else name.encode())
            for name in REQUIRED_FILES}
    if change:
        change(data)
    manifest = "".join(f"{hashlib.sha256(content).hexdigest()}  {name}\n"
                       for name, content in sorted(data.items())).encode()
    archive = tmp_path / f"spoolmera-{TAG}-test-linux-amd64.zip"
    with ZipFile(archive, "w") as zipped:
        for name, content in data.items():
            zipped.writestr("test-release/" + name, content)
        zipped.writestr("test-release/SHA256SUMS", manifest)
    sums = tmp_path / "SHA256SUMS.txt"
    sums.write_text(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  {archive.name}\n")
    return archive, sums


def test_verifies_complete_zip_and_outer_sha256(tmp_path):
    archive, sums = _bundle(tmp_path)
    assert verify_bundle(archive, expected_tag=TAG, expected_commit=SHA, sha256_file=sums)["schema_version"] == 12


def test_rejects_corrupt_outer_digest(tmp_path):
    archive, sums = _bundle(tmp_path)
    sums.write_text("0" * 64 + "  " + archive.name + "\n")
    with pytest.raises(ReleaseVerificationError, match="checksum mismatch"):
        verify_bundle(archive, expected_tag=TAG, expected_commit=SHA, sha256_file=sums)


def test_rejects_corrupt_inner_digest_even_with_matching_outer(tmp_path):
    archive, _ = _bundle(tmp_path)
    with ZipFile(archive) as zipped:
        entries = {i.filename: zipped.read(i) for i in zipped.infolist()}
    entries["test-release/SHA256SUMS"] = entries["test-release/SHA256SUMS"].replace(b"0", b"1", 1)
    with ZipFile(archive, "w") as zipped:
        for name, content in entries.items():
            zipped.writestr(name, content)
    with pytest.raises(ReleaseVerificationError, match="checksum"):
        verify_bundle(archive, expected_tag=TAG, expected_commit=SHA)


def test_rejects_mismatched_release_commit(tmp_path):
    archive, _ = _bundle(tmp_path)
    with pytest.raises(ReleaseVerificationError, match="metadata"):
        verify_bundle(archive, expected_tag=TAG, expected_commit="c" * 40)


def test_rejects_missing_required_file(tmp_path):
    archive, _ = _bundle(tmp_path, change=lambda data: data.pop("LICENSE"))
    with pytest.raises(ReleaseVerificationError, match="Missing or unexpected"):
        verify_bundle(archive, expected_tag=TAG, expected_commit=SHA)


def test_rejects_unlisted_additional_file(tmp_path):
    archive, _ = _bundle(tmp_path, change=lambda data: data.update({"unexpected.txt": b"test"}))
    with pytest.raises(ReleaseVerificationError, match="Missing or unexpected"):
        verify_bundle(archive, expected_tag=TAG, expected_commit=SHA)


@pytest.mark.parametrize("path", [
    "../escape.txt", "test-release/../escape.txt",
    "test-release/./LICENSE", "test-release\\bad",
])
def test_rejects_unsafe_zip_members(tmp_path, path):
    archive, _ = _bundle(tmp_path)
    with ZipFile(archive, "a") as zipped:
        zipped.writestr(path, "evil")
    with pytest.raises(ReleaseVerificationError, match="Unsafe|outside"):
        verify_bundle(archive, expected_tag=TAG, expected_commit=SHA)


def test_rejects_duplicate_zip_members(tmp_path):
    archive, _ = _bundle(tmp_path)
    with pytest.warns(UserWarning, match="Duplicate name"):
        with ZipFile(archive, "a") as zipped:
            zipped.writestr("test-release/LICENSE", "second copy")
    with pytest.raises(ReleaseVerificationError, match="Duplicate"):
        verify_bundle(archive, expected_tag=TAG, expected_commit=SHA)


def test_rejects_symlink_payload(tmp_path):
    archive, _ = _bundle(tmp_path)
    with ZipFile(archive, "a") as zipped:
        info = ZipInfo("test-release/shortcut")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        zipped.writestr(info, "../LICENSE")
    with pytest.raises(ReleaseVerificationError, match="Unsupported archive member type"):
        verify_bundle(archive, expected_tag=TAG, expected_commit=SHA)


def test_rejects_untrusted_tag_before_reading(tmp_path):
    archive, _ = _bundle(tmp_path)
    with pytest.raises(ReleaseVerificationError, match="identity"):
        verify_bundle(archive, expected_tag="v0.10.0; command", expected_commit=SHA)
