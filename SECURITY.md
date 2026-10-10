# Security policy

Spoolmera is experimental, self-hosted open-source software. It manages credentials and can optionally send physical printer commands; successful automated tests do not establish a safety certification or penetration test.

## Supported baseline

Use the latest tested main branch or tagged release. Keep the service on localhost behind a trusted HTTPS reverse proxy or VPN, secure cookies enabled for HTTPS, dedicated printer least-privilege credentials, and only exact private IPs in the printer allowlist. Printer commands and slicing are disabled by default; use the optional isolated worker for slicing.

## Reporting

**Do not publish exploitable vulnerabilities or secrets in public issues.** Use GitHub private vulnerability reporting if enabled for this repository, or contact the maintainer privately through an available private channel. Include affected commit/version, impact, reproduction steps with redacted credentials, and any suggested remediation.

The project is maintained by volunteers; no guaranteed commercial SLA, response window, bounty, or paid support is offered. Security fixes should be accompanied by focused tests without exposing exploitable secrets.

## Bambu Lab LAN boundary

The experimental Bambu Lab MQTT adapter is a **community/non-official integration** and has not been certified against hardware or all firmware. It requires an exact private IP allowlist, a verified TLS leaf-certificate fingerprint and a separately protected LAN access code. Certificate-pin mismatches must not be bypassed to restore access. Never publish MQTT port 8883 or printer credentials. Read the [device configuration and limitations](docs/security-and-printers.md#bambu-lab-lan-adapter-community--non-official).

## Deployment reminder

A malicious STL, G-code or controller can damage equipment. Optional network controls and an isolated slicer reduce exposure but cannot guarantee machine safety. Review generated G-code and supervise physical operation.
