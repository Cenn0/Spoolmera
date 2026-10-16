## Summary

What changes, why is it necessary, and what remains outside scope?

## Verification

- [ ] Python tests and Angular typecheck/unit tests/build pass (or failures are documented).
- [ ] Backend/API contracts and migration or inventory invariants are covered where relevant.
- [ ] Docker / browser / optional worker checks were run, or the untested boundary is explicit.
- [ ] Documentation and EN/DE UI strings were updated when behavior changed.
- [ ] No credentials, live customer data, printer access codes, database files or private profiles are committed.
- [ ] New commits use my own GitHub noreply identity; no private contact addresses or copied vendor assets enter the repository.
- [ ] Added/updated dependencies and distribution artifacts preserve applicable license texts and notices.
- [ ] No privileged `pull_request_target` / `workflow_run` execution of untrusted PR code was introduced.
- [ ] Hardware behavior is described as mocked or physically verified, not assumed.
- [ ] Actual UI screenshots, if included, use disposable data and record provenance.

## Security and operational impact

How does this affect authentication, network exposure, data integrity, printing or dependency trust? State "none" if not applicable. Do not report undisclosed vulnerabilities publicly; see [SECURITY.md](../SECURITY.md).
