## What

## Why

## Checks

- [ ] `python -m pytest` passes locally
- [ ] No network access added to tests
- [ ] Any new dependency is in `requirements.in` and the hash-pinned `requirements.txt` was regenerated
- [ ] No secrets, hostnames, addresses, usernames or local paths in the diff
- [ ] If the registry changed: every edited claim has a primary `source_url`, and `python -m drift snapshot --id <id>` was run
