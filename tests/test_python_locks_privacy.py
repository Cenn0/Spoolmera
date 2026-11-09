"""Privacy and strict parsing regressions for the public dependency-lock CI gate."""
from pathlib import Path

import pytest

from scripts.check_python_locks import check_locks, read_pins


def test_invalid_requirement_does_not_disclose_embedded_credential(tmp_path: Path) -> None:
    synthetic = "gh" + "p_" + "Z" * 36
    source = tmp_path / "requirements.in"
    source.write_text("https://example.invalid/" + synthetic + "\n", encoding="utf-8")
    with pytest.raises(ValueError) as error:
        read_pins(source, require_hashes=False)
    message = str(error.value)
    assert "unsupported or unpinned" in message
    assert synthetic not in message
    assert str(tmp_path) not in message


def test_lock_rejects_unsupported_options_without_echoing_them(tmp_path: Path) -> None:
    synthetic = "gh" + "p_" + "Z" * 36
    source = tmp_path / "requirements.txt"
    source.write_text("fastapi==1.2 --extra-index-url=https://example.invalid/" + synthetic
                      + " --hash=sha256:" + "a" * 64 + "\n", encoding="utf-8")
    with pytest.raises(ValueError) as error:
        read_pins(source, require_hashes=True)
    assert synthetic not in str(error.value)
    assert "unsupported" in str(error.value)


def test_version_mismatch_diagnostics_hide_untrusted_version(tmp_path: Path) -> None:
    for stem in ("requirements", "requirements-dev", "requirements-e2e"):
        (tmp_path / f"{stem}.in").write_text("fastapi==1.2\n", encoding="utf-8")
        (tmp_path / f"{stem}.txt").write_text(
            "fastapi==1.2 \\\n    --hash=sha256:" + "a" * 64 + "\n", encoding="utf-8")
    (tmp_path / "requirements.in").write_text("fastapi==2.0+local\n", encoding="utf-8")
    errors = check_locks(tmp_path)
    assert any("pinned dependency differs" in problem for problem in errors)
    assert not any("2.0+local" in problem for problem in errors)

def test_missing_input_files_do_not_expose_absolute_paths(tmp_path: Path) -> None:
    errors = check_locks(tmp_path)
    assert errors
    assert str(tmp_path) not in "\n".join(errors)


def test_duplicate_valid_package_name_is_withheld(tmp_path: Path) -> None:
    # Package-like strings can also resemble credentials, so never echo names.
    synthetic = "gh" + "p_" + "Z" * 36
    source = tmp_path / "requirements.in"
    source.write_text(f"{synthetic}==1.2\n{synthetic}==1.2\n", encoding="utf-8")
    with pytest.raises(ValueError) as error:
        read_pins(source, require_hashes=False)
    assert "duplicate dependency" in str(error.value)
    assert synthetic not in str(error.value)


def test_package_name_is_withheld_from_cross_lock_errors(tmp_path: Path) -> None:
    synthetic = "gh" + "p_" + "Z" * 36
    hash_pin = " --hash=sha256:" + "a" * 64
    for stem in ("requirements", "requirements-dev", "requirements-e2e"):
        (tmp_path / f"{stem}.in").write_text(f"{synthetic}==1.2\n", encoding="utf-8")
        (tmp_path / f"{stem}.txt").write_text(
            f"{synthetic}==1.2{hash_pin}\n", encoding="utf-8"
        )
    (tmp_path / "requirements.txt").write_text(
        f"{synthetic}==2.0{hash_pin}\n", encoding="utf-8"
    )
    errors = check_locks(tmp_path)
    assert any("pinned dependency differs" in problem for problem in errors)
    assert any("runtime dependency pin mismatch" in problem for problem in errors)
    assert synthetic not in "\n".join(errors)
