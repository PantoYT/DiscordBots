# Cemetery

Where the bots of the *red family go when they stop answering.
Not deleted, just at rest. Each one has its folder in this repo.

## Departed

| Bot | Lived | Job | Cause of death |
|---|---|---|---|
| **Cred** | 2026 | The Claude bot. Reported on the autonomous Amberfall loop every 30 minutes, took verdicts via `/odpowiedz`. | The remote host it lived on was shut down. Its keepalive cron went with it. |
| **Hred** | 2026-08 to 2026-10 | The Discord face of Hermes Agent, run from the PC. | Retired, not killed: Hermes moved to the server under the otnaP name. Its Nous login had already expired on 2026-09-29, so it had been silent since. |
| **otnaP (discord.py)** | 2026 | The original orchestrator: `/status`, `/bots`, `/ask` via OpenRouter. The code in `otnaP/` is this version. | Replaced by Hermes Agent wearing the same name and token. |

> Cred — it reported every half hour, right up to the last one.

## Sleeping (parked 2026-07-24, can be woken up)

| Bot | Job | To wake up |
|---|---|---|
| Tred | Trivia and fun facts | uncomment in `launch_all.vbs`, or give it a compose dir on the server |
| Pred | Polls | same |
| Rred | Reminders | same |
| Ared | Moderation | same (needs the Server Members intent) |
| Mred | Last.fm music | same |

## Alive (on the home server, docker compose)

| Bot | Since | Where |
|---|---|---|
| Vred | 2026-09-28 | `~/vred` |
| Fred | 2026-10-18 | `~/fred` |
| Qred | 2026-10-18 | `~/qred` |
| otnaP (Hermes Agent gateway) | 2026-10-18 | `~/otnap`, official `nousresearch/hermes-agent` image pinned by digest |
| MultiMuteUs (Among Us) | earlier | `~/multimuteus`, cron `@reboot` + keepalive |

Rule: a bot runs in exactly one place. Two instances on one token double every
post and split the state (Qred once ended up with quotes in two different files).
