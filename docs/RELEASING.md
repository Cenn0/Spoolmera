# Releasing Spoolmera

The current distributable is an **experimental Linux amd64 test bundle**, not a certified production printer controller. Full PR/main CI additionally tests the default app on native Linux arm64, but this release workflow publishes only a tested **amd64** image. Optional slicing/notifier images are **not** pushed.

## Automatically published main images

The [publish-main-image workflow](../.github/workflows/publish-main-image.yml) listens for successful completion of the **push-to-main** CI run. It rejects PR/tag CI runs and stale commits, then builds and publishes the standard `app-runtime` image to GitHub Container Registry for `linux/amd64` and `linux/arm64`. Each successful publication updates the moving experimental tag `ghcr.io/cenn0/spoolmera:main` and a commit-specific `ghcr.io/cenn0/spoolmera:sha-<full-40-character-commit-sha>` tag. Builds publish OCI provenance and an image SBOM. The workflow does not publish the optional slicer or notifier, deploy to any host, tag a release, or create a GitHub release.

This **main channel is experimental** and not a stable release or manufacturer certification. It never uses the moving `latest` tag. Main CI already builds and smoke-tests the app on native AMD64 and ARM64; the registry workflow depends on its successful conclusion and verifies the published multi-platform manifest. Verify an image's CI status, provenance, licenses and deployment impact before production use. The first GHCR package may require the owner to configure **public** visibility. See [deployment instructions](deployment.md#pull-the-ci-published-image-without-building-locally).

## Publish a reviewed version

1. Update `app/__init__.py`, `frontend/package.json`, `frontend/package-lock.json` and release documentation to the **same** version. Merge through protected `main`.
2. In GitHub Actions select **Publish tagged experimental test bundle**, choose `main`, and enter an **unused** `vMAJOR.MINOR.PATCH` tag (e.g., `v0.10.0`). Alternatively push that tag on an ancestor of protected `main`.
3. The workflow executes the entire reusable CI, validates that the tag equals the backend version and came from `main`, builds and runtime-tests the actual amd64 image including persistence, creates a checksummed test archive, **re-verifies its contents and metadata before publication**, pushes the tested image to `ghcr.io/cenn0/spoolmera:<version>`, and creates a GitHub **prerelease** with the archive and `SHA256SUMS.txt`.
4. Review the [GitHub release](https://github.com/Cenn0/Spoolmera/releases), pull and smoke-test GHCR externally, and check the package's public visibility; initial GHCR package visibility may need an owner change. Check downloaded ZIP integrity before extraction.

## Verify a downloaded release bundle

Use the `SHA256SUMS.txt` downloaded from that release and independently confirm the expected tag and 40-character **source commit SHA** from the repository. In a checked-out Spoolmera source directory with Python 3.12+:

```bash
sha256sum -c SHA256SUMS.txt
# Set SOURCE_COMMIT_SHA to the verified source commit (40 lowercase hex characters).
python3 scripts/verify_release_bundle.py spoolmera-v0.10.0-test-linux-amd64.zip \
  --tag v0.10.0 --commit "${SOURCE_COMMIT_SHA:?Set SOURCE_COMMIT_SHA first}" \
  --sha256-file SHA256SUMS.txt
```

Replace the example version and commit with those of the release being verified. The Python verifier streams every ZIP member without extracting or executing it, rejects traversal, unexpected or duplicate entries, bad internal checksums and mismatched `release.json` provenance. The release workflow executes this check **before** pushing to GHCR or creating a GitHub release. The verifier itself is also included inside the archive for offline reference; prefer the source checkout when verifying an untrusted download.

**Integrity is not authenticity:** an attacker controlling both an archive and its checksum file can replace both. These unsigned test bundles are not cryptographically signed or independently attested, and the verifier does not scan OCI image packages for vulnerabilities, certify a printer, or replace the deployment and security reviews.

Never set `latest` on experimental image tags, and never treat unit tests or smoke tests as production or manufacturer certification. A stable release requires an independently reviewed license inventory (including Debian components), image SBOM, vulnerability/security assessment and operational acceptance. The optional AGPL-licensed slicer requires separate source/notice obligations if ever distributed.

GitHub Actions `GITHUB_TOKEN`-created tags do **not** start a second tag-push workflow; the manually-dispatched job builds, tags and publishes within the same run. Configure tag protection and release immutability in repository settings.
