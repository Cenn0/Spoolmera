"""Regression tests for hash-lock consistency checks used by Dependabot PR CI."""
from pathlib import Path

from scripts.check_python_locks import check_locks, read_pins

HASH = "a" * 64


def write_set(root: Path, stem: str, direct: str, locked: list[tuple[str, str]]) -> None:
    (root / f"{stem}.in").write_text(direct, encoding="utf-8")
    lines = [
        f"{name}=={version} \\\n    --hash=sha256:{HASH}"
        for name, version in locked
    ]
    (root / f"{stem}.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")


def setup_locks(tmp_path: Path) -> None:
    write_set(tmp_path, "requirements", "fastapi==1.2\nqrcode==2\n", [("fastapi", "1.2"), ("qrcode", "2")])
    write_set(tmp_path, "requirements-dev", "-r requirements.in\npytest==9\n",
              [("fastapi", "1.2"), ("qrcode", "2"), ("pytest", "9")])
    write_set(tmp_path, "requirements-e2e", "-r requirements.in\nplaywright==3\n",
              [("fastapi", "1.2"), ("qrcode", "2"), ("playwright", "3")])


def test_matching_hashed_locks(tmp_path: Path) -> None:
    setup_locks(tmp_path)
    assert check_locks(tmp_path) == []


def test_stale_direct_requirement_is_rejected(tmp_path: Path) -> None:
    setup_locks(tmp_path)
    (tmp_path / "requirements.in").write_text("fastapi==2\nqrcode==2\n")
    assert any("fastapi must equal" in problem for problem in check_locks(tmp_path))


def test_runtime_test_lock_drift_is_rejected(tmp_path: Path) -> None:
    setup_locks(tmp_path)
    write_set(tmp_path, "requirements-e2e", "-r requirements.in\nplaywright==3\n",
              [("fastapi", "1.1"), ("qrcode", "2"), ("playwright", "3")])
    assert any("runtime dependency fastapi" in problem for problem in check_locks(tmp_path))


def test_missing_distribution_hash_is_rejected(tmp_path: Path) -> None:
    setup_locks(tmp_path)
    (tmp_path / "requirements-dev.txt").write_text("fastapi==1.2\n", encoding="utf-8")
    assert any("missing SHA256 hash" in problem for problem in check_locks(tmp_path))


def test_unpinned_input_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "requirements.in"
    source.write_text("fastapi>=1.2\n", encoding="utf-8")
    try:
        read_pins(source, require_hashes=False)
    except ValueError as exc:
        assert "unpin" in str(exc)
    else:
        raise AssertionError("Expected an error for a floating direct requirement")


def test_ambiguous_normalized_dependency_is_rejected(tmp_path: Path) -> None:
    source = tmp_path / "requirements.in"
    source.write_text("argon2_cffi==1\nargon2-cffi==1\n", encoding="utf-8")
    try:
        read_pins(source, require_hashes=False)
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("Expected an error for a duplicate normalized package name")
