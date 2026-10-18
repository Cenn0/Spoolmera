# Hardware compatibility and verification matrix

[← Documentation index](README.md) · [Printer security](security-and-printers.md) · [CI testing](testing.md)

**Evidence cutoff: 2026-10-19 · Application release: experimental v0.10.0.**

This matrix distinguishes an implemented adapter from its upstream API contract, automated simulation, practical operating guidance and real hardware validation. **No actual printer model/firmware combination or physical scale/tag reader is currently verified by project-maintained, reviewable real-device evidence.** Passing CI does not certify a printer or a safe print.

## Printer and accessory support

| Integration | Implemented in Spoolmera | Upstream status / official support | Executed test level | Physical compatibility status |
| --- | --- | --- | --- | --- |
| **Moonraker / Klipper** | Local status, history-based job correlation, privileged opt-in upload and start/pause/resume/cancel | Moonraker publishes a [documented HTTP/WebSocket API](https://moonraker.readthedocs.io/en/latest/web_api/); **no upstream certification of Spoolmera** | Automated API/controller simulations and isolated application browser tests | **Unverified:** no reviewed physical printer/firmware report |
| **OctoPrint** | Local status, opt-in G-code upload and printer commands; ambiguous completion requires explicit review | OctoPrint publishes an [HTTP API](https://docs.octoprint.org/en/main/api/index.html); **no upstream certification of Spoolmera** | Automated API/controller simulations | **Unverified:** no reviewed physical printer/firmware report |
| **Bambu Lab LAN MQTT** | Local status, temperatures, AMS telemetry, opt-in pause/resume/stop and strictly correlated **estimated** job consumption | Community/reverse-engineered integration; **not an officially supported Bambu Lab integration**. No vendor cloud login, file upload or remote print start | Mocked MQTT and failure/replay/correlation tests | **Unverified:** no reviewed hardware/firmware report |
| **PrusaSlicer (optional worker)** | Isolated CLI slicing from explicitly approved profiles; returns G-code to operator for review | Uses the PrusaSlicer CLI distributed through Debian; does not establish printer or vendor-cloud compatibility | CI builds and invokes a real CLI executable and a disposable test slicing job | **No physical output verified** |
| **NFC / Web NFC identification** | Explicit spool tag ID registration and lookup; compatible-browser Web NFC serial lookup | Browser/hardware-dependent; **not** full OpenPrintTag NDEF support or universal reader compatibility | Automated identifier/API and UI tests | **No verified reader/tag combination** |
| **Signed scale integration** | HMAC-SHA256 report intake, deduplication, human approval, transactional weight adjustment | Vendor-neutral webhook contract; no bundled sensor firmware | Automated webhook signature, replay and approval tests | **No verified calibration or real sensor** |

Evidence sources in this repository include [Moonraker/OctoPrint API tests](../tests/test_security_jobs.py), [Bambu LAN tests](../tests/test_bambu_lan.py), [Bambu consumption tests](../tests/test_bambu_consumption.py), [identification tests](../tests/test_identifiers.py), [scale tests](../tests/test_scale_relay.py) and the [slicer smoke harness](../scripts/slicer_smoke.py). These are **software tests**, not actual equipment certifications.

## Meaning of a compatibility claim

| Question | Present answer |
| --- | --- |
| **Does it work at application level?** | The implemented features above have test coverage. Review the CI status on the exact revision being deployed. |
| **Is it officially supported by the printer manufacturer?** | A documented Moonraker or OctoPrint API does **not** imply endorsement of Spoolmera. Bambu LAN MQTT is explicitly an unofficial community integration. |
| **What is the recommended operating model?** | One self-hosted application worker, an isolated test stack, read-only checks before enabling any command, and explicit operator review of all uncertain print outcomes. |
| **What is security-recommended?** | VPN/HTTPS, exact private-IP printer allowlists, least-privilege role gating, restricted network egress, and pinned TLS where required. Physical printer actions remain disabled by default. |
| **Which physical models/firmware combinations are certified?** | **None.** This project has no published, reviewed hardware certification evidence. |

## Procedure for a supervised physical compatibility report

Carry out physical tests only with explicit equipment-owner authorization, a supervised printer, disposable example jobs and a separately backed-up **test** Spoolmera database. Do not use production spool balances or trust a simulated controller as a physical device.

1. **Record identity without secrets:** Spoolmera commit/version; adapter; printer model; printer firmware and API/controller version; self-host OS/architecture; date; tester/reviewer. Replace device serial numbers, IPs, MAC addresses, tokens, certificate values and private hostnames with redacted placeholders before sharing.
2. **Start read-only:** Verify connectivity, state freshness, failure and reconnection behavior. Confirm an invalid certificate pin, unapproved IP and unavailable controller fail closed without exposing credentials or modifying stock.
3. **Exercise opt-in commands under supervision only where supported:** Explicitly enable and verify the intended action and its actual machine outcome. A successful HTTP/MQTT acknowledgement is **not** proof of physical execution. Never automatically repeat a start after a lost response.
4. **Validate interrupted prints and spool changes:** Include cancellation, network loss, controller restart, delayed completion, wrong filename/run ID, duplicate observations, multi-material mapping and a real spool swap. Reconcile movement history and remaining grams manually; no duplicate or unapproved debit is acceptable.
5. **Measure independently:** Weigh physical filament and purge/support waste with a calibrated scale if claiming usage accuracy. Record measurement uncertainty; simulated slicer estimates and AMS percentages are not measurements in grams.
6. **Review and retain sanitized evidence:** Store pass/fail/unsupported per feature plus the relevant logs with secrets removed, the reviewer decision and unresolved limitations. Retest each materially changed firmware, adapter or authentication mode.

### Public report template

Use a new issue or pull request only with sanitized data. For suspected vulnerabilities, follow the [private security reporting process](../SECURITY.md) instead of publishing the logs.

| Field | Value |
| --- | --- |
| Spoolmera commit / version | |
| Adapter / model / firmware / API version | |
| OS and architecture | |
| Date and independent reviewer | |
| Read-only status and reconnection | Pass / Fail / Not tested |
| TLS, network, access and failure boundaries | Pass / Fail / Not tested |
| Supervised commands (when applicable) | Pass / Fail / Not supported / Not tested |
| Cancellation, ambiguous result and replay | Pass / Fail / Not tested |
| Spool mapping and ledger idempotency | Pass / Fail / Not tested |
| Independent mass/calibration evidence | Pass / Fail / Not applicable / Not tested |
| Sanitized supporting evidence | |
| Known limitations and decision | |

A submitted report is **unreviewed community evidence** until its version, test setup, outcomes and redactions have been reviewed. It does not create manufacturer support. This matrix should be updated only with explicit evidence and clear firmware/version scope; never promote a simulated pass into a hardware-validated claim.
