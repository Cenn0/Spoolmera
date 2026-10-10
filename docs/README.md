# Spoolmera documentation

[← Project README and screenshots](../README.md)

**Spoolmera v0.10.0** is an experimental, self-hosted Python/FastAPI + Angular + SQLite application. The source repository is [`Cenn0/Spoolmera`](https://github.com/Cenn0/Spoolmera). The UI supports English and German; developer and operator documentation is in English.

## User and operator guides

| Task | Guide |
| --- | --- |
| Install with Docker, configure HTTPS/QR URLs, back up or upgrade | [Deployment](deployment.md) |
| Navigate inventory, cards, tables, locations and drag-and-drop | [UI and UX](interface-ux.md) |
| Use English or German | [Language behavior](interface-languages.md) |
| Import/export filaments and physical spools | [CSV schema](csv-format.md) |
| Manage job states, opt-in slicer, cloud relays, backups and restoration | [Operations](operations.md) |
| Configure Moonraker, OctoPrint or community Bambu Lab LAN MQTT | [Security and printers](security-and-printers.md) |
| Determine actual feature coverage and limitations | [Feature/status matrix](roadmap-implementation.md) |
| Test in an isolated environment, inspect every UI view in four layouts, interpret CI evidence | [Testing](testing.md) |
| Examine/refresh real browser screenshots | [Screenshot provenance](screenshots/README.md) |

## Engineering and integration reference

| Subject | Guide |
| --- | --- |
| Module ownership, transactions, migration and printer lifecycle | [Architecture](architecture.md) |
| Existing API and proposed adapters | [Integration contracts](integrations.md) |
| Dependency lockfiles, Docker base images and CI artifacts | [Build reproducibility](build-reproducibility.md) and [build inputs](build-inputs.json) |
| Development contributions and vulnerability reports | [Contributing](../CONTRIBUTING.md) and [Security policy](../SECURITY.md) |

## Terminology and support

**Implemented** means corresponding code and application tests exist; it does not mean hardware-certified. **Documented upstream** means the device/service has a published API, not that it endorses Spoolmera. **Recommended** describes preferred engineering or operational practice. **Security recommended** is a separate assessment of exposure and risk.

The Bambu Lab **LAN MQTT** integration is community-developed and **not officially supported by Bambu Lab**. It does not provide native cloud login, file transfer or remote start. Moonraker and OctoPrint also lack physical printer/firmware certification. Refer to [hardware boundaries](security-and-printers.md).

## Dated reference material — historical, not current instructions

These records preserve earlier reviews, plans and test evidence. When they conflict with current behavior, use the application code and current operational guides rather than treating a dated plan as a shipped feature.

- [Implementation report (2026-10-09)](implementation-2026-10-09.md)
- [Code review (2026-10-08)](review-2026-10-08.md)
- [Regression follow-up (2026-10-08)](review-regressions-2026-10-08.md)
- [Inventory UI follow-up (2026-10-09)](inventory-ui-followup-2026-10-09.md)
- [UI review follow-up (2026-10-09)](ui-review-followup-2026-10-09.md)
- [Storage-board follow-up (2026-10-09)](ui-storage-board-2026-10-09.md)
- [Original UI/UX concept](ui-ux-concept.md)

## Documentation maintenance

When features, environment settings or device behavior change, update this index, the [README](../README.md), the relevant operator guide and the [feature matrix](roadmap-implementation.md) together. Never present simulated-controller tests as real-printer verification. Screenshots must be captured from the built Angular app with **disposable example data** and documented CI provenance; do not substitute generated mockups. See [the capture procedure](screenshots/README.md).
