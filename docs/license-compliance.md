# Licensing and public release compliance

[← Documentation index](README.md) · [← Project README](../README.md)

Spoolmera is Apache-2.0 software. External packages, optional executable programs, services, data and trademarks are **not** automatically covered by that project license. Consult the [third-party inventory](../THIRD_PARTY_LICENSES.md) and the relevant original license texts before redistribution.

## Distribution boundaries

| Delivered item | Contents and license obligations |
| --- | --- |
| Public source repository | Spoolmera Apache-2.0 source; do not strip upstream copyright, license or NOTICE text from any incorporated third-party files |
| Default application Docker image | Installed Python dependencies and compiled Angular runtime; include the full project license, bundled npm notices, Python notices and installed base-system copyright records |
| Optional notifier image | Project Python notification script plus Python/Debian base image; include project license and base-image licensing |
| Optional slicing worker | The above plus Debian PrusaSlicer and its dependencies; **AGPL-3.0 obligations** apply to the distributed slicer program. Supply or arrange access to complete corresponding sources when required, including version-matched patches and build information |
| CI test download | Docker image archive plus the project license, license inventory and built-image license manifests. It is **not** an audited production release |
| Optional catalog and printer API lookups | Third-party network communications at runtime, not bundled copies of the remote products or services. A separately deployed cloud adapter must observe its own terms |

A standalone CLI subprocess in an isolated worker is not automatically an AGPL-derived copy of the Apache-2.0 application. This is not a guarantee of license compatibility in every modified or integrated deployment.

## Verify the notices actually distributed

Build the default image and check the exact installed files:

```bash
docker build -t spoolmera:licensing-audit .
docker run --rm --entrypoint /bin/sh spoolmera:licensing-audit -ec \
  'ls -l /usr/share/doc/spoolmera && test -s /usr/share/doc/spoolmera/npm-licenses.txt && test -s /usr/share/doc/spoolmera/python-licenses.txt'
```

For the optional slicer worker:

```bash
docker build --target slicer-runtime -t spoolmera:slicer-licensing-audit .
docker run --rm --entrypoint /bin/sh spoolmera:slicer-licensing-audit -ec \
  'test -s /usr/share/doc/prusa-slicer/copyright; dpkg-query -W'
```

This tests presence, not the legal sufficiency of the image's entire dependency tree. Use `dpkg-query` and Debian copyright/source records for all packages; inspect `/usr/share/doc/prusa-slicer/copyright` and the exact Debian source version. The output of `npm sbom --omit=dev --sbom-format cyclonedx`, the Python dependency manifest and hashes/digests are review inputs, not legal certification.

## Release checklist

1. Confirm which **exact** images or artifacts will be distributed. Review upstream license changes on every dependency upgrade and ensure generated notices match installed package versions.
2. Preserve all required license/NOTICE/copyright texts in the resulting images **and** downloadable bundles. Confirm available source for the exact AGPL-licensed PrusaSlicer package and any included dependencies, not merely a link to the repository's latest main branch.
3. Inspect optional npm/Python dependencies and Debian packages for restrictive or mixed licenses. Ensure the resulting frontend JavaScript does not contain copied fonts, icons or assets without redistribution rights.
4. Produce and retain per-image software-bill-of-materials, version/digest provenance and vulnerability scans. The repository's npm CycloneDX file and Python manifest do not cover all OS packages by themselves.
5. Audit the distribution package for secrets, private profiles, personal information and generated user data. Do not put internal GitHub administration rules, private contacts or account credentials into release documentation.
6. Release under clear experimental-support and non-endorsement statements. Protect physical printers and require operator review for critical commands.

## Licenses, protocols and third-party data

- [Apache-2.0 text](../LICENSE) applies to Spoolmera's source and requires retaining the relevant attribution and notice conditions.
- [PrusaSlicer license](https://github.com/prusa3d/PrusaSlicer/blob/master/LICENSE) is AGPL-3.0. Optional separate installation is a product choice; Docker image distribution still brings AGPL obligations.
- [Open Filament Database upstream repository](https://github.com/OpenFilamentCollective/open-filament-database) states that its dataset is MIT-licensed. Spoolmera's read-only opt-in browser does not copy the dataset into a release image.
- Controller API availability is different from manufacturer support, trademark permission or licensing of a copied SDK. Spoolmera includes no official Bambu SDK; see [hardware limitations](security-and-printers.md).

No part of this guide provides a legal clearance for an uninspected binary image.
