# Notion Auth Broker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans task-by-task.

**Goal:** Let Claude, Codex, and the dashboard share one Keychain-stored Notion PAT without exposing it to sandboxed agent processes.

**Architecture:** A user-scoped broker owns Keychain access and accepts authenticated local requests on a Unix socket. `NotionSession` uses the broker when direct Keychain access fails; direct Keychain use remains the fallback for normal terminals.

**Tech Stack:** Python standard library Unix sockets, keyring, requests, pytest.

## Global Constraints

- PAT remains in macOS Keychain; config files never contain it.
- Socket directory and socket file carry an ownership marker and appear in the install manifest.
- `teardown` removes the broker artifact but preserves Keychain PAT unless `--purge-secrets` is used.
- Broker protocol never returns the PAT; it forwards only allow-listed Notion API requests.

### Task 1: Broker protocol and lifecycle

**Files:** Create `notionmemory/core/notion_broker.py`; test `tests/core/test_notion_broker.py`.

- [ ] Write failing tests for request forwarding, refusal of token-returning paths, and socket permissions.
- [ ] Implement JSON-lines Unix-socket broker with per-user socket permissions and an owned marker.
- [ ] Run `./venv/bin/python -m pytest tests/core/test_notion_broker.py -v`.

### Task 2: Session fallback

**Files:** Modify `notionmemory/core/notion_client.py`, `notionmemory/core/notion_auth.py`; test `tests/core/test_notion_auth.py`.

- [ ] Write failing tests for Keychain-missing process using the broker without receiving a raw PAT.
- [ ] Make `NotionSession` delegate HTTP requests to the broker only after direct Keychain lookup fails.
- [ ] Run focused auth/client tests.

### Task 3: Installation contract

**Files:** Modify `notionmemory/core/install/manifest.py`, install/teardown handlers, tests under `tests/core/install/` and `tests/test_artifact_contract.py`.

- [ ] Write failing artifact contract and teardown tests for the owned socket directory.
- [ ] Install/start broker on demand; remove broker artifact during teardown without deleting user data or PAT by default.
- [ ] Run installation and clean-clone verification.

### Task 4: End-to-end verification

- [ ] Run complete pytest suite.
- [ ] Run `./scripts/verify_clean_clone.sh`.
- [ ] Verify broker fallback with a Keychain-denied test double and direct Keychain path with an existing-token test double.
