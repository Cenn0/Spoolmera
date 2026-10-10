"""Validated operator settings. Configuration errors fail before workers start."""
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping
from urllib.parse import urlsplit


class ConfigurationError(ValueError):
    """An operator setting is malformed; values and secrets are never echoed."""


def _integer(env: Mapping[str, str], name: str, default: int, lower: int, upper: int) -> int:
    try:
        value = int(env.get(name, str(default)))
    except (ValueError, TypeError):
        raise ConfigurationError(f"{name} must be an integer between {lower} and {upper}.") from None
    if not lower <= value <= upper:
        raise ConfigurationError(f"{name} must be between {lower} and {upper}.")
    return value


def _boolean(env: Mapping[str, str], name: str) -> bool:
    value = env.get(name, "0")
    if value not in {"0", "1"}:
        raise ConfigurationError(f"{name} must be 0 or 1.")
    return value == "1"


def read_secret(name: str, env: Mapping[str, str] | None = None) -> str:
    """Support narrowly mounted Docker secrets without logging their contents."""
    values = os.environ if env is None else env
    direct, filename = values.get(name, ""), values.get(name + "_FILE", "")
    if direct and filename:
        raise ConfigurationError(f"Set only one of {name} and {name}_FILE.")
    if not filename:
        return direct
    try:
        with Path(filename).open("r", encoding="utf-8") as source:
            secret = source.read(8193)
    except (OSError, UnicodeError):
        raise ConfigurationError(f"Cannot read {name}_FILE.") from None
    if len(secret) > 8192:
        raise ConfigurationError(f"{name}_FILE is too large.")
    return secret.rstrip("\r\n")


@dataclass(frozen=True)
class Settings:
    poll_interval_seconds: int = 30
    poll_lease_seconds: int = 30
    backup_timeout_seconds: int = 30
    backup_max_bytes: int = 256 * 1024 * 1024
    storage_reserve_bytes: int = 64 * 1024 * 1024
    slicer_enabled: bool = False
    slicer_configured: bool = False

    @classmethod
    def from_environment(cls, env: Mapping[str, str] | None = None) -> "Settings":
        values = os.environ if env is None else env
        interval = _integer(values, "SPOOLMERA_PRINTER_POLL_SECONDS", 30, 10, 300)
        timeout = _integer(values, "SPOOLMERA_BACKUP_TIMEOUT_SECONDS", 30, 1, 300)
        reserve_mb = _integer(values, "SPOOLMERA_STORAGE_RESERVE_MIB", 64, 1, 4096)
        for name in ("SPOOLMERA_COOKIE_SECURE", "SPOOLMERA_PRINTER_CONTROL_ENABLED", "SPOOLMERA_CATALOG_ENABLED"):
            _boolean(values, name)
        slicer_enabled = _boolean(values, "SPOOLMERA_SLICER_ENABLED")
        public_origin = values.get("SPOOLMERA_PUBLIC_BASE_URL", "")
        if public_origin:
            try:
                parsed = urlsplit(public_origin)
                parsed.port
            except ValueError:
                raise ConfigurationError("SPOOLMERA_PUBLIC_BASE_URL must be an HTTP(S) origin.") from None
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                    or parsed.password or parsed.path not in {"", "/"} or parsed.query or parsed.fragment):
                raise ConfigurationError("SPOOLMERA_PUBLIC_BASE_URL must be an HTTP(S) origin.")
        slicer_configured = (
            values.get("SPOOLMERA_SLICER_WORKER_URL") == "http://slicer-worker:8767"
            and len(values.get("SPOOLMERA_SLICER_WORKER_TOKEN", "")) >= 32
        )
        if slicer_enabled and not slicer_configured:
            raise ConfigurationError("Enabled slicing requires its internal worker URL and a 32-character token.")
        return cls(poll_interval_seconds=interval, backup_timeout_seconds=timeout,
                   storage_reserve_bytes=reserve_mb * 1024 * 1024,
                   slicer_enabled=slicer_enabled, slicer_configured=slicer_configured)
