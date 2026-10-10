# Public GitHub repository security

[← Documentation index](README.md) · [← Security policy](../SECURITY.md)

This guide describes the intended controls for the **public** [Cenn0/Spoolmera](https://github.com/Cenn0/Spoolmera) repository. The JSON file in [`.github/rulesets/main.json`](../.github/rulesets/main.json) is a **declarative proposal**, not an active GitHub ruleset until an authorized repository administrator applies it. A file in Git alone cannot enforce branch protection.

## One-time administrator setup

Prerequisites: repository administration rights, the GitHub CLI (`gh`) authenticated as that administrator, and this change merged into the default branch. Review the JSON before applying it. Verify that the [CI workflow](../.github/workflows/ci.yml) succeeded on `main` and currently exposes the five distinct job check names below.

```bash
gh auth status
gh api repos/Cenn0/Spoolmera/rulesets
# First application only: must show no same-named ruleset already in place.
gh api -X POST repos/Cenn0/Spoolmera/rulesets --input .github/rulesets/main.json
gh api repos/Cenn0/Spoolmera/rulesets
```

If that ruleset already exists, **do not POST again**. Instead, review its ID using `gh api repos/Cenn0/Spoolmera/rulesets`, then use `gh api -X PUT repos/Cenn0/Spoolmera/rulesets/<RULESET_ID> --input .github/rulesets/main.json` after checking for administrator changes in GitHub. Re-check the ruleset's `enforcement` value is `active`.

Go to [Settings → Rules → Rulesets](https://github.com/Cenn0/Spoolmera/settings/rules) and confirm that the ruleset targets the default branch, includes **no bypass actors**, and enforces:

- Changes through pull requests, with conversations resolved.
- Required checks: `test`, `docker-smoke`, `browser-smoke`, `slicer-build`, `security-audit`.
- Up-to-date checks before merging.
- Squash or rebase merges only (linear history).
- No direct updates that circumvent the PR rule, no force pushes and no branch deletion.

The ruleset deliberately requires **zero approvals** because this is currently a single-maintainer repository; GitHub does not allow an author to approve their own PR. That is a workable solo-maintainer policy, **not** equivalent to independent review. When an independent eligible maintainer is available, raise the count to one and enable code owner review after assessing contributor workflows. The existing `CODEOWNERS` file routes changes for visibility only.

## GitHub settings that cannot be applied by committing files

Configure and verify these controls in the repository web settings:

1. [Settings → Advanced Security](https://github.com/Cenn0/Spoolmera/settings/security_analysis): enable **Dependabot alerts**, **Dependabot security updates**, **secret scanning**, **push protection**, and **private vulnerability reporting**, where each control is offered. Availability can vary by account and repository setting. Activating the Dependabot configuration file alone does not activate alerts, security updates or secret scanning.
2. [Settings → Actions → General](https://github.com/Cenn0/Spoolmera/settings/actions): keep default `GITHUB_TOKEN` permissions **read-only**, require approval for untrusted outside contributions where supported, and prohibit unrestricted access to secrets in forked pull-request workflows.
3. Do **not** add `pull_request_target` or a privileged `workflow_run` flow that executes code or artifacts from untrusted forks. CI uses a read-only token and does not supply production credentials.
4. Consider enabling automatic deletion of merged feature branches under [Settings → General](https://github.com/Cenn0/Spoolmera/settings), but do not delete branches with unmerged work.
5. [Security](https://github.com/Cenn0/Spoolmera/security): examine Dependabot/CodeQL findings. The separate CodeQL workflow scans Python and JavaScript/TypeScript; first verify it succeeds before making its dynamically named check(s) mandatory. Do not activate GitHub's alternative CodeQL default setup on top of this advanced workflow without a deliberate reason, because that can duplicate scans.

## After changing a private repository to public

- Check **all Git history**, tags, workflow logs, releases and Actions artifacts for any secrets or personal information. Current-source inspection or a clean CI run is not proof that Git history is clean.
- If a credential was ever committed or included in a published artifact, **revoke/rotate it at its provider first**. Deleting a file or rewriting history is not sufficient once a secret has been exposed.
- Review legacy image artifacts, screenshots and tests for personal data, private hostnames, API credentials, real printer access codes and database backups.
- Keep runtime `.env`, printer access codes, TLS certificate fingerprints where confidentiality matters, API tokens, SSH keys and production SQLite backups out of the repository. Existing `.gitignore` and `.dockerignore` mitigate accidental adds/build leakage; they are not a guarantee.
- Treat public PR code and dependency changes as untrusted. Never run forked scripts with production secrets or trusted Docker mounts.
- Enable [private vulnerability reporting](https://github.com/Cenn0/Spoolmera/security) so security reports do not need to be disclosed through public issues.

## Supply-chain update workflow

Dependabot proposes changes to `frontend/package-lock.json`, frontend manifests and GitHub Actions. Review transitive dependency changes and upstream advisories; require CI. Python uses intentionally layered, hash-locked `requirements*.txt` generated from `requirements*.in`: maintain those sets together using [the documented update procedure](build-reproducibility.md) and verify `pip-audit`. Do not blindly merge a bot PR that breaks the hash-locked Python dependency graph. Docker image digest and slicer package changes are likewise reviewed manually with [build-inputs.json](build-inputs.json).

**Security status must be checked in GitHub itself:** a committed ruleset JSON, workflow YAML, `SECURITY.md` or policy text does not establish that the repository settings are active.
