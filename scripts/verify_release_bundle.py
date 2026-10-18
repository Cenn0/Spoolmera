"""Verify a Spoolmera experimental release archive without extracting or executing it.

The checksums detect damage or inconsistencies. They are NOT a digital signature
or an independent guarantee about who produced the artifact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import stat
from zipfile import BadZipFile, ZipFile

CHUNK_BYTES = 1024 * 1024
MAX_MEMBERS = 64
MAX_MEMBER_BYTES = 3 * 1024**3
MAX_TOTAL_BYTES = 4 * 1024**3
REQUIRED_FILES = frozenset({
    "LICENSE", "THIRD_PARTY_LICENSES.md", "TESTING.md", "build-inputs.json",
    "compose.test.yaml", "npm-licenses.txt", "python-dependencies.json",
    "python-licenses.txt", "release.json", "scripts/start_test.py",
    "scripts/verify_release_bundle.py", "spoolmera-image.tar.gz",
})
CHECKSUM_LINE = re.compile(r"([0-9a-f]{64})  ([^\r\n]+)\Z")
TAG = re.compile(r"v[0-9]+\.[0-9]+\.[0-9]+\Z")
COMMIT = re.compile(r"[a-f0-9]{40}\Z")
IMAGE_ID = re.compile(r"sha256:[a-f0-9]{64}\Z")


class ReleaseVerificationError(ValueError):
    """Release artifact does not satisfy the published integrity contract."""


def _checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for part in iter(lambda: stream.read(CHUNK_BYTES), b""):
            digest.update(part)
    return digest.hexdigest()


def _validate_outer_checksum(archive: Path, sha256_file: Path) -> None:
    if sha256_file.stat().st_size > 4096:
        raise ReleaseVerificationError("Oversized outer SHA256SUMS.txt")
    lines = sha256_file.read_text(encoding="utf-8").splitlines()
    if len(lines) != 1:
        raise ReleaseVerificationError("Outer SHA256SUMS.txt must have exactly one entry")
    match = CHECKSUM_LINE.fullmatch(lines[0])
    if match is None or match.group(2) != archive.name:
        raise ReleaseVerificationError("Outer SHA256SUMS.txt does not identify this archive")
    if match.group(1) != _checksum(archive):
        raise ReleaseVerificationError("Release archive checksum mismatch")


def _member_path(filename: str, *, directory: bool) -> str | None:
    if "\\" in filename or "\x00" in filename:
        raise ReleaseVerificationError("Unsafe archive member path")
    # Reject traversal, absolute paths, empty components and odd normalization.
    parts = filename.rstrip("/").split("/")
    if any(part in ("", ".", "..") for part in parts):
        raise ReleaseVerificationError("Unsafe archive member path")
    if parts[0] != "test-release":
        raise ReleaseVerificationError("Archive member outside test-release/")
    if directory:
        return None
    if len(parts) < 2:
        raise ReleaseVerificationError("Unexpected file at archive root")
    return "/".join(parts[1:])


def _read_small(archive: ZipFile, path: str, limit: int = 128 * 1024) -> bytes:
    info = archive.getinfo("test-release/" + path)
    if info.file_size > limit:
        raise ReleaseVerificationError(f"Oversized metadata file: {path}")
    data = archive.read(info)
    if len(data) != info.file_size:
        raise ReleaseVerificationError(f"Truncated metadata file: {path}")
    return data


def verify_bundle(
    archive_path: Path, *, expected_tag: str, expected_commit: str,
    sha256_file: Path | None = None,
) -> dict:
    """Check the outer checksum, all inner files, metadata and ZIP structure."""
    if not TAG.fullmatch(expected_tag) or not COMMIT.fullmatch(expected_commit):
        raise ReleaseVerificationError("Expected tag or commit is not a valid release identity")
    if sha256_file is not None:
        _validate_outer_checksum(archive_path, sha256_file)
    try:
        with ZipFile(archive_path) as bundle:
            entries = bundle.infolist()
            if not entries or len(entries) > MAX_MEMBERS:
                raise ReleaseVerificationError("Invalid number of ZIP members")
            seen_paths: set[str] = set()
            files: dict[str, object] = {}
            total_size = 0
            for entry in entries:
                if entry.filename in seen_paths:
                    raise ReleaseVerificationError("Duplicate archive member name")
                seen_paths.add(entry.filename)
                is_directory = entry.is_dir()
                name = _member_path(entry.filename, directory=is_directory)
                mode = stat.S_IFMT(entry.external_attr >> 16)
                if mode not in (0, stat.S_IFDIR if is_directory else stat.S_IFREG):
                    raise ReleaseVerificationError("Unsupported archive member type")
                if entry.flag_bits & 1:
                    raise ReleaseVerificationError("Encrypted ZIP entries are unsupported")
                if is_directory:
                    continue
                if entry.file_size > MAX_MEMBER_BYTES:
                    raise ReleaseVerificationError("Oversized ZIP member")
                total_size += entry.file_size
                if total_size > MAX_TOTAL_BYTES:
                    raise ReleaseVerificationError("Release archive exceeds size budget")
                if name in files:
                    raise ReleaseVerificationError("Duplicate archive payload path")
                files[name] = entry
            if set(files) != REQUIRED_FILES | {"SHA256SUMS"}:
                raise ReleaseVerificationError("Missing or unexpected files in release bundle")
            raw = _read_small(bundle, "SHA256SUMS", limit=32 * 1024)
            try:
                lines = raw.decode("utf-8").splitlines()
            except UnicodeDecodeError as exc:
                raise ReleaseVerificationError("Inner checksum manifest is not UTF-8") from exc
            checksums: dict[str, str] = {}
            for line in lines:
                match = CHECKSUM_LINE.fullmatch(line)
                if match is None or match.group(2) in checksums:
                    raise ReleaseVerificationError("Invalid or duplicated inner checksum entry")
                checksums[match.group(2)] = match.group(1)
            if set(checksums) != set(files) - {"SHA256SUMS"}:
                raise ReleaseVerificationError("Inner checksum manifest does not cover exactly the published files")
            for path, digest in checksums.items():
                computed = hashlib.sha256()
                with bundle.open(files[path]) as stream:
                    for part in iter(lambda: stream.read(CHUNK_BYTES), b""):
                        computed.update(part)
                if computed.hexdigest() != digest:
                    raise ReleaseVerificationError(f"Inner checksum mismatch for {path}")
            try:
                metadata = json.loads(_read_small(bundle, "release.json").decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ReleaseVerificationError("Invalid release.json metadata") from exc
            if not isinstance(metadata, dict) or any((
                metadata.get("tag") != expected_tag,
                metadata.get("version") != expected_tag[1:],
                metadata.get("commit") != expected_commit,
                metadata.get("platform") != "linux/amd64",
                metadata.get("image_archive") != "spoolmera-image.tar.gz",
                metadata.get("image_tag") != "spoolmera:test",
                type(metadata.get("schema_version")) is not int or metadata["schema_version"] <= 0,
                not isinstance(metadata.get("image_id"), str) or not IMAGE_ID.fullmatch(metadata["image_id"]),
            )):
                raise ReleaseVerificationError("Release metadata does not match its expected source and image")
            return metadata
    except (BadZipFile, KeyError, EOFError, OSError) as exc:
        raise ReleaseVerificationError("Unreadable or incomplete release archive") from exc


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path, help="Path to the test-release ZIP")
    parser.add_argument("--tag", required=True, help="Expected release tag, e.g. v0.10.0")
    parser.add_argument("--commit", required=True, help="Expected 40-character Git commit SHA")
    parser.add_argument("--sha256-file", type=Path, help="Optional outer SHA256SUMS.txt")
    args = parser.parse_args()
    try:
        result = verify_bundle(args.archive, expected_tag=args.tag, expected_commit=args.commit,
                               sha256_file=args.sha256_file)
    except ReleaseVerificationError as exc:
        parser.exit(1, f"Release bundle verification failed: {exc}\n")
    print(f"Verified {args.archive.name}: {result['tag']} at {result['commit']} ({result['platform']}).")
    print("Checksums confirm integrity, not publisher authenticity or hardware safety.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
