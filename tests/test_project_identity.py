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
    "fm" + "-",
    "X-" + "Filament-",
    "x-" + "filament-",
    "filament-" + "browser-",
    "filament-" + "ui-previews",
    "filament-" + "language-",
)
SUFFIXES = {".py", ".ts", ".mjs", ".html", ".css", ".md", ".yml", ".yaml", ".json", ".example"}
SKIP = {".git", ".venv", ".data", "node_modules", "dist", "coverage", "__pycache__", ".pytest_cache"}

# The repository URL and its checkout directory still have the pre-rebrand name.
# This narrow docs-only exception must not permit old application identifiers in
# code, configuration, product descriptions or arbitrary documentation prose.
REPOSITORY_NAME = "Filament" + "Manager"
REPOSITORY_PATH = "Cenn0/" + REPOSITORY_NAME


def checked_identity_content(path: Path) -> str:
    content = path.read_text(encoding="utf-8")
    if path.suffix == ".md":
        content = content.replace(REPOSITORY_PATH, "")
        content = content.replace("cd " + REPOSITORY_NAME, "")
    return content


def test_no_obsolete_brand_identifiers_in_source():
    violations = []
    for path in ROOT.rglob("*"):
        parts = path.relative_to(ROOT).parts
        if any(part in SKIP for part in parts) or parts[:2] == ("app", "ui") or not path.is_file():
            continue
        if path.suffix not in SUFFIXES and path.name not in {"Dockerfile", "Dockerfile.notifications", ".env.example"}:
            continue
        # The identity guard uses concatenated markers, not actual legacy identifiers.
        content = checked_identity_content(path)
        for token in LEGACY:
            if (token in content if token == "FILAMENT" + "_" else token.lower() in content.lower()):
                violations.append(f"{path.relative_to(ROOT)}: {token}")
    assert not violations, "Obsolete project identifiers:\\n" + "\\n".join(violations)


def test_greenfield_project_namespace():
    frontend = json.loads((ROOT / "frontend/angular.json").read_text(encoding="utf-8"))
    assert frontend["projects"]["spoolmera"]["prefix"] == "sm"
    compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
    assert "name: spoolmera" in compose and "spoolmera_data:/data" in compose
    assert "SPOOLMERA_DB_PATH" in compose


def test_old_application_name_still_rejected_outside_repository_references(tmp_path):
    doc = tmp_path / "docs.md"
    doc.write_text("App: " + REPOSITORY_NAME + "\\n", encoding="utf-8")
    assert any(token.lower() in checked_identity_content(doc).lower() for token in LEGACY)
    doc.write_text("Repository: " + REPOSITORY_PATH + "\\ncd " + REPOSITORY_NAME + "\\n", encoding="utf-8")
    assert all(token.lower() not in checked_identity_content(doc).lower() for token in LEGACY)
    source = tmp_path / "module.py"
    source.write_text("App: " + REPOSITORY_NAME, encoding="utf-8")
    assert REPOSITORY_NAME in checked_identity_content(source)
