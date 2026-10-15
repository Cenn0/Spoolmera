# Commit-email privacy in public repositories

[← Documentation index](README.md) · [← Contributing](../CONTRIBUTING.md)

Git records the **author** and **committer** name/email in every commit object. Changing a GitHub profile setting, `.mailmap`, a source-file address or the local Git configuration does **not** remove an old address from existing published commits. A source check in CI also cannot rewrite commit metadata.

## Prevent future exposure

1. In GitHub **Settings → Emails**, enable **Keep my email addresses private** and **Block command line pushes that expose my email** (when available). This affects GitHub's web operations and blocks some unsafe pushes, not existing history.
2. Copy **your own** GitHub noreply address from your Email settings. Modern accounts use `ID+USERNAME@users.noreply.github.com`. Do not copy another contributor's address.
3. Set your local identity in each relevant checkout: `git config user.email "ID+USERNAME@users.noreply.github.com"`; verify with `git config --get user.email`. For all repositories, use `git config --global user.email ...` if appropriate.
4. Use a pull request. Do not publish personal contact addresses in README, release bundles, screenshots, tests, issue text or commit messages.

`scripts/check_public_content.py` rejects unapproved email-shaped addresses found in **tracked source files** without printing the matched values. This guard does not inspect unpublished objects or the Git history and does not replace secret scanning.

## If history already contains a private email address

A complete remediation requires a **planned Git history rewrite**, not a normal pull request. Do not store the exposed address in a committed `.mailmap`, script or PR body. Follow GitHub's official [Removing sensitive data from a repository](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository) procedure with `git-filter-repo` in a private fresh mirror clone. Re-map author **and** committer addresses to the account's noreply address, inspect all branches/tags/refs, and review rewritten content before pushing.

Repository owners must coordinate a maintenance window, temporarily adjust any blocking rulesets, update affected refs using a controlled force push, rebuild affected releases, and prevent collaborators from merging old history back. All commit SHAs, signed commit signatures and PR links can change or become invalid. Restore protections immediately afterward. GitHub Support may need to clear old cached commit views and PR refs; forks, external clones and caches cannot be erased by an ordinary repository push. GitHub decides whether support remediation is available.

**Do not claim the historical address is completely removed** until affected server-side Git refs and caches have been verified separately. GitHub Settings cannot rewrite Git objects on behalf of an administrator.
