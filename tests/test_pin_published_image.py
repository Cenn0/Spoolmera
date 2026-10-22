"""The pinned-image workflow cannot silently switch containers or expose secrets."""
from pathlib import Path
import os
import stat
import subprocess
import sys

from scripts.pin_published_image import pin_env

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/pin_published_image.py"
DIGEST = "sha256:" + "a" * 64
IMAGE = f"ghcr.io/cenn0/spoolmera@{DIGEST}"


def run_cli(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *arguments],
        check=False, capture_output=True, text=True
    )


def test_replace_single_image_assignment_without_touching_secrets():
    private = "SPOOLMERA_BOOTSTRAP_TOKEN=private-value\nSPOOLMERA_IMAGE=ghcr.io/cenn0/spoolmera:main\nSPOOLMERA_COOKIE_SECURE=1\n"
    updated = pin_env(private, IMAGE)
    assert updated == (
        "SPOOLMERA_BOOTSTRAP_TOKEN=private-value\n"
        f"SPOOLMERA_IMAGE={IMAGE}\n"
        "SPOOLMERA_COOKIE_SECURE=1\n"
    )
    assert "private-value" in updated


def test_append_image_when_env_has_no_trailing_newline():
    assert pin_env("SPOOLMERA_COOKIE_SECURE=1", IMAGE) == (
        "SPOOLMERA_COOKIE_SECURE=1\n" + f"SPOOLMERA_IMAGE={IMAGE}\n"
    )


def test_reject_duplicate_image_assignments():
    try:
        pin_env("SPOOLMERA_IMAGE=a\nexport SPOOLMERA_IMAGE=b\n", IMAGE)
    except ValueError as exception:
        assert "Multiple SPOOLMERA_IMAGE" in str(exception)
    else:
        raise AssertionError("Expected ambiguous .env to be rejected")


def test_preview_is_non_mutating_and_redacts_existing_secret(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("SPOOLMERA_BOOTSTRAP_TOKEN=secret-not-to-print\n")
    result = run_cli("--digest", DIGEST, "--env-file", str(env))
    assert result.returncode == 0
    assert f"SPOOLMERA_IMAGE={IMAGE}" in result.stdout
    assert "secret-not-to-print" not in result.stdout + result.stderr
    assert env.read_text() == "SPOOLMERA_BOOTSTRAP_TOKEN=secret-not-to-print\n"


def test_explicit_apply_preserves_other_variables_and_restricts_permissions(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("SPOOLMERA_BOOTSTRAP_TOKEN=private-value\nSPOOLMERA_IMAGE=ghcr.io/cenn0/spoolmera:main\n")
    os.chmod(env, 0o644)
    result = run_cli("--digest", DIGEST, "--env-file", str(env), "--apply")
    assert result.returncode == 0, result.stderr
    assert env.read_text() == (
        "SPOOLMERA_BOOTSTRAP_TOKEN=private-value\n" + f"SPOOLMERA_IMAGE={IMAGE}\n"
    )
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
    assert "private-value" not in result.stdout + result.stderr


def test_invalid_digest_is_rejected_without_modification(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("SPOOLMERA_IMAGE=spoolmera:local\n")
    for invalid in ("sha256:abc", "sha256:" + "A" * 64, "sha256:" + "a" * 64 + ":main"):
        result = run_cli("--digest", invalid, "--env-file", str(env), "--apply")
        assert result.returncode != 0
        assert env.read_text() == "SPOOLMERA_IMAGE=spoolmera:local\n"


def test_symlinked_or_missing_env_file_is_rejected(tmp_path: Path):
    real = tmp_path / "real.env"
    real.write_text("SPOOLMERA_BOOTSTRAP_TOKEN=secret\n")
    symlink = tmp_path / ".env"
    symlink.symlink_to(real)
    for path in (symlink, tmp_path / "does-not-exist"):
        result = run_cli("--digest", DIGEST, "--env-file", str(path), "--apply")
        assert result.returncode != 0
        assert "Refusing" in result.stderr
    assert real.read_text() == "SPOOLMERA_BOOTSTRAP_TOKEN=secret\n"


def test_double_application_is_idempotent(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("SPOOLMERA_COOKIE_SECURE=1\n")
    for _ in range(2):
        result = run_cli("--digest", DIGEST, "--env-file", str(env), "--apply")
        assert result.returncode == 0
    assert env.read_text().count("SPOOLMERA_IMAGE=") == 1


def test_multiline_values_are_rejected_without_modifying_other_configuration(tmp_path):
    env = tmp_path / ".env"
    original = "TEST_VALUE='first\nSPOOLMERA_IMAGE=literal-value\nlast'\n"
    env.write_text(original)
    result = run_cli("--digest", DIGEST, "--env-file", str(env), "--apply")
    assert result.returncode != 0
    assert env.read_text() == original
    assert "literal-value" not in result.stdout + result.stderr


def test_colon_and_unset_image_assignments_are_replaced_and_duplicates_rejected():
    for original in ("SPOOLMERA_IMAGE: old\n", "export SPOOLMERA_IMAGE: old\n", "SPOOLMERA_IMAGE\n"):
        assert pin_env(original, IMAGE) == f"SPOOLMERA_IMAGE={IMAGE}\n"
    try:
        pin_env("SPOOLMERA_IMAGE: old\nSPOOLMERA_IMAGE=new\n", IMAGE)
    except ValueError:
        pass
    else:
        raise AssertionError("Mixed duplicate assignments must be rejected")


def test_matching_digest_still_gets_private_file_permissions(tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"SPOOLMERA_IMAGE={IMAGE}\n")
    env.chmod(0o644)
    result = run_cli("--digest", DIGEST, "--env-file", str(env), "--apply")
    assert result.returncode == 0
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_other_value_bytes_and_crlf_are_preserved(tmp_path):
    env = tmp_path / ".env"
    original = b'TEST_VALUE="one \\"quoted\\" value"\r\nSPOOLMERA_IMAGE: old\r\nOTHER=unchanged\r\n'
    env.write_bytes(original)
    result = run_cli("--digest", DIGEST, "--env-file", str(env), "--apply")
    assert result.returncode == 0, result.stderr
    assert env.read_bytes() == original.replace(b"SPOOLMERA_IMAGE: old", f"SPOOLMERA_IMAGE={IMAGE}".encode())
