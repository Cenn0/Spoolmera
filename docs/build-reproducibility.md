# Build inputs and dependency updates

The release target is CPython 3.12 on Linux; the CI image artifact is `linux/amd64`. Backend and frontend package versions are **0.10.0**. Other architectures in an upstream manifest do not imply application validation on those hosts.

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

These controls reproduce dependency selection and verify Python distributions. They do **not** promise byte-identical Docker builds: Debian transitive packages are not frozen to a historical apt snapshot, timestamps vary, and the optional package repository must still supply the pinned slicer version. The built image ID and archive hash are recorded in each test artifact.

## Release licenses and software inventory

The default and optional application images ship the project's Apache-2.0 LICENSE and a third-party license overview at `/usr/share/doc/spoolmera/`. `scripts/collect_python_licenses.py` reads exactly the pinned runtime distributions and includes their packaged license/notice files and a JSON component manifest. `frontend/scripts/collect-license-notices.mjs` collects notices for installed production npm packages and fails the build if a required notice is missing. Debian copyright files for installed system packages remain under `/usr/share/doc/`; the optional PrusaSlicer worker specifically verifies `/usr/share/doc/prusa-slicer/copyright`.

The `docker-smoke` job verifies these files and copies runtime notices into the downloadable CI test bundle. `security-audit` additionally produces a production npm CycloneDX SBOM for inspection; this is **not** a complete SBOM for Debian packages or the optional slicer image. For any stable binary release, inventory Debian/system packages separately and verify the license/source-offer obligations of the exact image build. Details: [License compliance](license-compliance.md).

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

A successful `browser-smoke` job publishes genuine German and UI/UX Chromium captures using a synthetic, disposable database. Reviewed images are checked in under [`docs/screenshots/`](screenshots/README.md), referenced by the README and accompanied by a source commit and run identifier. The files are not a claim of physical printer certification, and CI artifacts are only temporarily available.

## Test artifact provenance

The Docker CI job produces `spoolmera-0.10.0-test-linux-amd64`. Its `release.json` identifies version, schema, tested checkout commit and Docker image ID. `SHA256SUMS` covers the archive and supporting files. `TESTING.md` explains the isolated test volume and launcher. Validate checksums before importing the image.

Artifacts are retained for the period configured in CI. They are downloadable test builds, not a published GitHub release or a declaration of production/hardware certification. Packaging does not change repository visibility.
