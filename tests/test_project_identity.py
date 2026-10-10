"""Fail if an obsolete application identity reappears in shipped project source."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
LEGACY = (
    "Filament" + "Manager",
    "Filament " + "Manager",
    "filament-" + "manager",
    "filament_" + "manager",
    "filament" + "manager",
    "FILAMENT" + "_",
    "filament_" + "session",
    "filament-" + "notifications",
    "filament_" + "notifier_state",
    "filament-" + "notify",
    ".filament-" + "restore-",
    "fm_" + "language",
    "fmm" + "_",
)
SUFFIXES = {".py", ".ts", ".mjs", ".html", ".css", ".md", ".yml", ".yaml", ".json", ".example"}
SKIP = {".git", ".venv", ".data", "node_modules", "dist", "coverage", "__pycache__", ".pytest_cache", "ui"}


def test_no_obsolete_brand_identifiers_in_source():
    violations = []
    for path in ROOT.rglob("*"):
        if any(part in SKIP for part in path.relative_to(ROOT).parts) or not path.is_file():
            continue
        if path.suffix not in SUFFIXES and path.name not in {"Dockerfile", "Dockerfile.notifications", ".env.example"}:
            continue
        # The identity guard uses concatenated markers, not actual legacy identifiers.
        content = path.read_text(encoding="utf-8")
        for token in LEGACY:
            if token.lower() in content.lower():
                violations.append(f"{path.relative_to(ROOT)}: {token}")
    assert not violations, "Obsolete project identifiers:\\n" + "\\n".join(violations)


def test_greenfield_project_namespace():
    frontend = json.loads((ROOT / "frontend/angular.json").read_text(encoding="utf-8"))
    assert frontend["projects"]["spoolmera"]["prefix"] == "sm"
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "name: spoolmera" in compose and "spoolmera_data:/data" in compose
    assert "SPOOLMERA_DB_PATH" in compose
