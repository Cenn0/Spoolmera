"""Regression guards for publishing a tested main image without weakening CI gates.

These checks validate security-sensitive workflow invariants; GitHub Actions
performs the authoritative workflow syntax and execution validation.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/publish-main-image.yml"
COMPOSE = ROOT / "compose.yaml"


def test_image_publication_only_after_successful_main_ci():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "on:\n  workflow_run:" in workflow
    assert "workflows: [CI]" in workflow
    assert "types: [completed]" in workflow
    assert "branches: [main]" in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.event == 'push'" in workflow
    assert "github.event.workflow_run.head_branch == 'main'" in workflow
    assert "github.event.workflow_run.head_repository.full_name == 'Cenn0/Spoolmera'" in workflow
    assert "workflow_dispatch:" not in workflow


def test_stale_ci_cannot_start_an_image_publish():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "cancel-in-progress: false" in workflow
    assert 'git fetch --no-tags --depth=1 origin main' in workflow
    assert 'git rev-parse HEAD' in workflow
    assert 'git rev-parse FETCH_HEAD' in workflow
    assert "current=false" in workflow
    # Image pushes must be conditional on the freshness check.
    assert workflow.count("if: steps.revision.outputs.current == 'true'") >= 4


def test_images_are_scoped_versioned_multiarch_and_experimental():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "packages: write" in workflow
    assert "persist-credentials: false" in workflow
    assert "ref: ${{ github.event.workflow_run.head_sha }}" in workflow
    assert "target: app-runtime" in workflow
    assert "platforms: linux/amd64,linux/arm64" in workflow
    assert "ghcr.io/cenn0/spoolmera:main" in workflow
    assert 'ghcr.io/cenn0/spoolmera:sha-$SOURCE_COMMIT' in workflow
    assert "ghcr.io/cenn0/spoolmera:latest" not in workflow
    assert "push: true" in workflow


def test_compose_supports_prebuilt_images_without_changing_default_build():
    compose = COMPOSE.read_text(encoding="utf-8")
    assert "image: ${SPOOLMERA_IMAGE:-spoolmera:local}" in compose
    assert "build: ." in compose
    assert "spoolmera_data:/data" in compose
    assert "127.0.0.1:8765:8765" in compose


def test_main_tag_only_moves_after_both_native_registry_verification_jobs():
    workflow = WORKFLOW.read_text(encoding="utf-8")
    build, verify, promote = workflow.split("  verify:")[0], workflow.split("  verify:")[1].split("  promote:")[0], workflow.split("  promote:")[1]
    assert "spoolmera:main" not in build
    assert "candidate-${{ github.event.workflow_run.head_sha }}" in build
    assert "needs: [publish, verify]" in promote
    assert "fail-fast: false" in verify
    assert "runner: ubuntu-24.04-arm" in verify
    assert "runner: ubuntu-24.04" in verify
    assert "packages: read" in verify and "packages: write" not in verify
    assert "verify_published_image.py" in verify
    assert "container_restore_smoke.py" in verify
    assert "scan_container.py" in verify
    assert "continue-on-error" not in workflow
    assert '"$SOURCE_COMMIT" != "$(git rev-parse FETCH_HEAD)"' in promote
    assert 'imagetools create' in promote and 'docker build ' not in promote


def test_release_image_scan_precedes_registry_and_release_publication():
    release = (ROOT / ".github/workflows/release-test.yml").read_text(encoding="utf-8")
    assert release.index("scripts/scan_container.py") < release.index("docker push")
    assert release.index("scripts/scan_container.py") < release.index("gh release create")
