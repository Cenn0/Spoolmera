"""Keep public release and database version documentation in sync."""
import json
from pathlib import Path

from scripts.check_docs import metadata_consistency_errors


def _write(root: Path, relative: str, content: str):
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def test_docs_gate_rejects_stale_schema_and_release(tmp_path):
    _write(tmp_path, "app/__init__.py", '__version__ = "0.10.0"\n')
    _write(tmp_path, "app/infrastructure/database/migrations.py", "CURRENT_SCHEMA_VERSION = 12\n")
    _write(tmp_path, "frontend/package.json", json.dumps({"version": "0.10.0"}))
    for relative in (
        "README.md", "docs/README.md", "docs/deployment.md",
        "docs/architecture.md", "docs/roadmap-implementation.md",
    ):
        _write(tmp_path, relative, "Spoolmera v0.10.0\n")
    _write(tmp_path, "docs/architecture.md", "Spoolmera v0.10.0\nCurrent SQLite schema version: **12**.\n")
    _write(tmp_path, "docs/security-and-printers.md", "The current database schema is version 12; migrations are forward-only.\n")
    assert metadata_consistency_errors(tmp_path) == []

    _write(tmp_path, "docs/architecture.md", "Spoolmera v0.10.0\nCurrent SQLite schema version: **10**.\n")
    assert any("schema version" in problem for problem in metadata_consistency_errors(tmp_path))

    _write(tmp_path, "docs/architecture.md", "Spoolmera v0.10.0\nCurrent SQLite schema version: **12**.\n")
    _write(tmp_path, "frontend/package.json", json.dumps({"version": "0.9.0"}))
    assert any("frontend/package.json" in problem for problem in metadata_consistency_errors(tmp_path))


def test_docs_gate_rejects_stale_operator_schema(tmp_path):
    _write(tmp_path, "app/__init__.py", '__version__ = "0.10.0"\n')
    _write(tmp_path, "app/infrastructure/database/migrations.py", "CURRENT_SCHEMA_VERSION = 12\n")
    _write(tmp_path, "frontend/package.json", json.dumps({"version": "0.10.0"}))
    for relative in (
        "README.md", "docs/README.md", "docs/deployment.md",
        "docs/roadmap-implementation.md",
    ):
        _write(tmp_path, relative, "Spoolmera v0.10.0\n")
    _write(tmp_path, "docs/architecture.md", "Spoolmera v0.10.0\nCurrent SQLite schema version: **12**.\n")
    _write(tmp_path, "docs/security-and-printers.md", "The current database schema is version 10.\n")
    assert any("docs/security-and-printers.md" in issue for issue in metadata_consistency_errors(tmp_path))
