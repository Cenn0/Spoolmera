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
    assert any("fastapi must equal" in problem for problem in errors)
    assert not any("2.0+local" in problem for problem in errors)
