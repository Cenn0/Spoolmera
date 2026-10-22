# Releasing Spoolmera

The versioned release workflow produces an **experimental Linux amd64 test bundle** only after its publication gates pass. No downloadable bundle exists merely because the source version was updated. It is not a certified production printer controller. Full PR/main CI additionally tests the default app on native Linux arm64, but this release workflow publishes only a tested **amd64** image. Optional slicing/notifier images are **not** pushed.

## Automatically published main images

The [publish-main-image workflow](../.github/workflows/publish-main-image.yml) accepts successful **push-to-main** CI only and builds the standard `app-runtime` image for `linux/amd64` and `linux/arm64`. It first publishes a **candidate**, `ghcr.io/cenn0/spoolmera:candidate-<full-commit-sha>`, with OCI source labels, provenance and an image SBOM. A candidate is not an accepted build.

Separate native AMD64 and ARM64 runners pull the **exact registry digest**, check its CPU architecture, non-root user, source revision, Angular assets and notices, then exercise authenticated HTTP, ledger/restart persistence and guarded offline recovery using disposable volumes. Each runner scans actual OS and Python packages and generates a CycloneDX image SBOM. Only after **both** verification jobs pass does the promotion job update `ghcr.io/cenn0/spoolmera:main` and `ghcr.io/cenn0/spoolmera:sha-<full-commit-sha>`, using the verified digest without rebuilding. It checks main freshness again immediately before promotion. A rejected or stale candidate leaves the previously accepted main image in place.

The scanner is upstream Trivy with a version and **release-archive SHA-256 pinned** in [scanner inputs](../scripts/container_scan_inputs.json); it does not execute an install script or a mutable scanner Action. [The scan harness](../scripts/scan_container.py) records every severity, rejects incomplete scans and blocks **all HIGH/CRITICAL findings, including unfixed ones**. It disables inherited Trivy environment settings and uses empty explicit config/ignore files. Download/database/scanner failures also block promotion. Reports and SBOM stay in the job's temporary directory; the job summary records totals. Review lower-severity findings separately. Scan success is not proof that an application is safe or independently audited.

**Known release blocker (2026-10-22):** the previously published application image was scanned with this policy and reported HIGH Debian package findings without an available fix in that scan. Do not interpret earlier green dependency audits or the existing moving tag as evidence that this stricter image gate passed. Candidate images must remain unaccepted until the blocking package findings are resolved or separately reviewed through an explicit security-policy change; there are no automatic exceptions.

The workflow does not deploy to a host, publish the optional slicer/notifier, create a version tag or create a GitHub release. This main channel remains experimental and never uses `latest`. The first GHCR package may require the owner to configure public visibility. See [deployment instructions](deployment.md#pull-the-ci-published-image-without-building-locally).

## Publish a reviewed version

1. Update `app/__init__.py`, `frontend/package.json`, `frontend/package-lock.json` and release documentation to the **same** version. Merge through protected `main`.
2. In GitHub Actions select **Publish tagged experimental test bundle**, choose `main`, and enter an **unused** `vMAJOR.MINOR.PATCH` tag (e.g., `v0.10.0`). Alternatively push that tag on an ancestor of protected `main`.
3. The workflow executes the entire reusable CI, validates that the tag equals the backend version and came from `main`, builds and runtime-tests the actual amd64 image including persistence, scans its actual packages with the same HIGH/CRITICAL gate, creates a checksummed test archive, **re-verifies its contents and metadata before publication**, pushes the tested image to `ghcr.io/cenn0/spoolmera:<version>`, and creates a GitHub **prerelease** with the archive and `SHA256SUMS.txt`.
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
