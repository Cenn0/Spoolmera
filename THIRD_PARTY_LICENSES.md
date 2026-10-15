# Third-party software and license notices

Spoolmera source code is licensed under [Apache License 2.0](LICENSE). That license does **not** relicense dependencies, other programs, vendor services, or externally supplied data.

This is a human-readable *license inventory*, not a claim that every external component has been independently certified. Exact installed versions are recorded in `requirements.txt`, `frontend/package-lock.json` and `docs/build-inputs.json`. License and copyright notices for **actually installed runtime distributions** are collected at image-build time.

## Application libraries

| Package or component | Upstream licensing | Distribution boundary |
| --- | --- | --- |
| Angular (`@angular/*`) | MIT | Static compiled Angular frontend; per-package notices in `npm-licenses.txt` |
| RxJS | Apache-2.0 | Compiled frontend; packaged notice in `npm-licenses.txt` |
| tslib | 0BSD | Frontend helper; packaged notice in `npm-licenses.txt` |
| FastAPI | MIT | Python runtime wheel and its upstream license text |
| Uvicorn | BSD-3-Clause | Python runtime wheel and its upstream license text |
| qrcode | BSD-3-Clause | Python runtime wheel and its upstream license text |
| argon2-cffi | MIT | Python runtime wheel and its upstream license text |
| Remaining transitive npm/Python dependencies | Mixed compatible licenses, not automatically Apache-2.0 | Exact packaged notices and generated inventories must be reviewed |

## Optional programs, images and external data

- **PrusaSlicer:** AGPL-3.0, installed from Debian's `prusa-slicer` package in the **optional, separate** slicer worker. It is not included in the default application image. Read `/usr/share/doc/prusa-slicer/copyright` in the worker image and the [upstream source and license](https://github.com/prusa3d/PrusaSlicer). The [Debian source package](https://packages.debian.org/source/trixie/slic3r-prusa) corresponds to the Debian packaging, not necessarily all downstream updates. Redistributing this image may require providing the **complete corresponding source** and license notices for AGPL and other contained binaries; publishing this Apache-2.0 repository alone is not a blanket source-code offer.
- **Debian and official Python/Node base images:** system packages retain their respective licenses, with installed package copyright records normally available under `/usr/share/doc/`. A base-image digest locks the referenced image, but does not replace a license inventory.
- **Open Filament Database:** its [upstream repository](https://github.com/OpenFilamentCollective/open-filament-database) states MIT licensing for the dataset. Spoolmera *optionally* retrieves records at runtime; it does not embed the dataset or logos in the default Docker image. Any future inclusion of third-party imagery must be separately checked for rights.
- **Spoolman, Moonraker, OctoPrint, Bambu Lab and ntfy:** Spoolmera implements API/protocol adapters or an import format; it does not bundle those programs or proprietary manufacturer SDKs in the default image. Upstream names remain the rights of their owners. Compatibility does **not** imply vendor endorsement or officially supported integration.

## Where full notices are shipped

The default and optional application images contain:
- `/usr/share/doc/spoolmera/LICENSE` — Spoolmera's Apache-2.0 license.
- `/usr/share/doc/spoolmera/THIRD_PARTY_LICENSES.md` — this inventory.
- `/usr/share/doc/spoolmera/npm-licenses.txt` — copied licensing/notice texts from installed production npm packages (generated at build time).
- `/usr/share/doc/spoolmera/python-licenses.txt` — copied licensing/notice texts from installed pinned Python distributions (generated at build time).
- `/usr/share/doc/spoolmera/python-dependencies.json` — pinned Python component/license metadata.

The optional notifier image contains the project license and overview; its Python script only imports the standard library. Debian system package notices are provided by the base image. The CI test download additionally ships the application license and generated notices. **For a real public binary release**, inspect all image layers and system package dependencies and document the corresponding source availability of AGPL software first.

See the [license-compliance and release guide](docs/license-compliance.md) for inspection commands and review requirements.
