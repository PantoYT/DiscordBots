# Privacy Policy — Cred

_Last updated: 2026-06-11_

Cred is a private bot that aims to collect and store **as little as possible**.

## What Cred processes
- **Slash-command interactions** you send (e.g. the text you pass to `/odpowiedz`).
  The `/odpowiedz` text is written to a local file (`preview/owner_verdict.txt`) on the
  operator's server so the Amberfall automation can read your verdict. Other commands
  are processed in memory and not persisted.
- **Your Discord user ID** (`OWNER_ID`) is read from local configuration to identify the
  owner and to deliver direct-message reports.

## What Cred does NOT do
- It does **not** read message content (no Message Content Intent).
- It does **not** track, profile, or store other users' messages or activity.
- It does **not** share data with third parties. Reports (project status + render
  images) are sent only to the configured owner/channel.

## Storage & retention
- The only persisted user data is the text you explicitly submit via `/odpowiedz`,
  kept in a local file on the operator's server until manually cleared.
- Bot logs may contain operational messages (not user content).

## Your choices
- Don't want data stored? Don't use `/odpowiedz`.
- Removal requests: contact the operator (PantoYT); the local verdict file can be
  deleted on request.

## Contact
Operator: PantoYT, via the Discord server where Cred is deployed.
