# Build inputs and dependency updates

The release target is CPython 3.12 on Linux; tagged experimental test bundles target `linux/amd64`. Backend and frontend package versions are **0.10.0**. The default application container is also built and exercised on a native Linux arm64 runner by the `arm64-container` CI job (API, persisted ledger, offline restore). Check the commit's CI result; no arm64 release bundle or hardware certification is provided. The optional slicer image is not part of this arm64 gate. Other architectures in upstream base-image manifests do not imply application validation on those hosts.

## What is locked

- `requirements.in` holds deliberate direct runtime choices; `requirements.txt` contains the complete graph and accepted distribution hashes.
- `requirements-dev.in` and `requirements-e2e.in` add test tools. Their locks are constrained by the runtime lock so the application graph matches production.
- `frontend/package-lock.json` records the npm graph; install with `npm ci`.
- Application Docker stages and the optional notifier use reviewed base-image digests. The optional slicer pins its Debian PrusaSlicer package version.
- [build-inputs.json](build-inputs.json) records reviewed tags, manifest digests, platform metadata, slicer source and lock generator.

Install with hash verification:

```bash
python -m pip install --require-hashes -r requirements-dev.txt
python -m pip install --require-hashes -r requirements-e2e.txt
```

Both test locks may be installed in one development environment. Runtime containers install only `requirements.txt`.

These controls reproduce dependency selection and verify Python distributions. They do **not** promise byte-identical Docker builds: Debian transitive packages are not frozen to a historical apt snapshot, timestamps vary, and the optional package repository must still supply the pinned slicer version. The tagged test release metadata records the released image ID and archive hash.

## Release licenses and software inventory

The default and optional application images ship the project's Apache-2.0 LICENSE and a third-party license overview at `/usr/share/doc/spoolmera/`. `scripts/collect_python_licenses.py` reads exactly the pinned runtime distributions and includes their packaged license/notice files and a JSON component manifest. `frontend/scripts/collect-license-notices.mjs` collects notices for installed production npm packages and fails the build if a required notice is missing. Debian copyright files for installed system packages remain under `/usr/share/doc/`; the optional PrusaSlicer worker specifically verifies `/usr/share/doc/prusa-slicer/copyright`.

The `docker-smoke` job verifies these files; the tagged test-release workflow copies runtime notices into the downloadable release bundle. `security-audit` additionally validates a production npm CycloneDX SBOM in-job without storing it; this is **not** a complete SBOM for Debian packages or the optional slicer image. For any stable binary release, inventory Debian/system packages separately and verify the license/source-offer obligations of the exact image build. Details: [License compliance](license-compliance.md).

## Dependabot Python update proposals

Dependabot checks the root directory using the `pip` ecosystem weekly on Monday
at 07:30 Europe/Berlin, with at most three open Python version-update PRs.
Patch and minor releases are grouped; major releases are reviewed separately.
Security audits remain independent from Dependabot version-update scheduling.

**Important limitation:** Spoolmera generates its `requirements*.txt` files
with `uv pip compile`, not pip-tools and not the `uv.lock` project format.
Dependabot's `pip` updater recognizes requirement files, but native
regeneration of all three **uv-generated** hash locks is not guaranteed.
Do not treat an automatically generated PR as a reproducible upgrade
until all of its affected input files and locks are synchronized.

For each Python update PR:

1. Check `requirements.in`, `requirements-dev.in` and `requirements-e2e.in`
   against their three corresponding hashed `.txt` files; update the relevant
   **direct pin** in the `.in` file if Dependabot changed only a compiled lock.
   Grouped changes may require a separate decision on each direct dependency.
2. Regenerate the runtime lock first, then the development and E2E locks using
   the `uv 0.12.23` procedure below. For a targeted transitive update, use
   `--upgrade-package <package-name>` where necessary; evaluate any resulting
   changes to other transitive packages.
3. Run `python scripts/check_python_locks.py` before installing. CI rejects
   missing SHA256 hashes, different direct pins and runtime/test lock divergence.
   It does not perform dependency resolution: also execute the hash-verified
   installs and the complete CI/security audit.
4. Review package release notes, licenses, dependency/API compatibility and
   Docker integration. Only merge with successful tests; there is no automatic
   merge or reduced PR permissions for Dependabot.

Do not remove hashes, loosen pinned direct dependencies or skip the lock check
to make an updater PR green. If Dependabot cannot update the `uv` format
correctly, fix the proposed branch through the documented local `uv` commands.
A green CI verifies the tested graph, not untested real hardware compatibility.

## Deliberate update procedure

Review direct version changes in the `.in` files first. Using the recorded generator (`uv 0.12.23` for this update), resolve and hash the supported target:

```bash
uv pip compile requirements.in --python-version 3.12 --generate-hashes --upgrade -o requirements.txt
uv pip compile requirements-dev.in --python-version 3.12 --constraints requirements.txt --generate-hashes --upgrade -o requirements-dev.txt
uv pip compile requirements-e2e.in --python-version 3.12 --constraints requirements.txt --generate-hashes --upgrade -o requirements-e2e.txt
```

Install in a clean Python 3.12 environment with `--require-hashes`. Review npm updates with their lockfile. Resolve new digests from the official image registry and update Dockerfiles and `build-inputs.json` together. Check the Debian package version/source on slicer updates and run the real fixture gate, not just `--help`.

Regenerate API declarations with `python scripts/generate_api_types.py`; CI uses `--check`. Run the Python suite, `npm run typecheck`, `npm test`, `npm run build`, browser smoke, default/recovery/notifier Docker smoke, optional slicer smoke and dependency audits. A version bump updates `app/__init__.py`, `frontend/package.json`, npm lock package metadata and release documentation together.

## Browser screenshot provenance

A successful `browser-smoke` job validates genuine German and UI/UX Chromium captures from a synthetic, disposable database without uploading them. Reviewed images are checked in under [`docs/screenshots/`](screenshots/README.md), referenced by the README and accompanied by a source commit and run identifier. The files are not a claim of physical printer certification; complete fresh captures can be regenerated locally.

## Tagged test-release provenance

Routine CI runs have no persistent Actions artifacts or dependency caches. The tag-triggered test release runs all CI gates, then rebuilds and smoke-tests a Linux amd64 Docker image from the tagged commit. Its `release.json` identifies version, schema, source tag/commit and image ID. `SHA256SUMS` inside the bundle covers the image archive and accompanying files, while `SHA256SUMS.txt` on GitHub Releases verifies the outer downloadable ZIP. `TESTING.md` describes the isolated test volume and launcher.

The workflow refuses version/tag mismatches and refuses to overwrite an existing release. Published assets are unsigned experimental test distributions, not a production or physical-printer certification.
