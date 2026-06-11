# Cred

The Claude bot of the family (Ared · Fred · Mred · otnaP · Pred · Qred · Rred ·
Tred · Vred · **Cred**). Cred reports on the **autonomous Amberfall** project: it
DMs the owner a status + latest render every 30 minutes, answers `/raport` on
demand, and records the owner's verdict via `/odpowiedz` so the autonomous loop can
read it. discord.py · slash commands only · amber accent.

## Commands

| Command | Who | What |
|---|---|---|
| `/raport` | owner | Immediate Amberfall report (latest render + status) |
| `/odpowiedz <tekst>` | owner | Record your verdict (👍/👎/notes) → `preview/owner_verdict.txt` |
| `/status` | anyone | Short text status |
| `/commands` | anyone | List commands |
| `/shutdown` | owner | Stop Cred |

A report is also sent automatically every `REPORT_INTERVAL_MIN` (default 30) minutes.

## Setup

```bash
python3 -m venv --without-pip venv      # if your distro lacks ensurepip
curl -sSL https://bootstrap.pypa.io/get-pip.py | venv/bin/python -
venv/bin/pip install -r requirements.txt
cp .env.example .env                    # fill DISCORD_TOKEN, OWNER_ID, AMBERFALL_DIR
./run.sh
```

Keep it alive with cron (host where Amberfall runs):

```cron
*/5 * * * * /home/wojtekhalasa/cred/keepalive.sh >> /home/wojtekhalasa/cred/cred.log 2>&1
```

## Inviting Cred + the scopes question

In the Developer Portal you already picked the right scopes: **`bot`** and
**`applications.commands`**. You don't toggle them anywhere else — they go into the
**invite (OAuth2) URL** that adds Cred to your server. Use:

```
https://discord.com/oauth2/authorize?client_id=1514710272689045694&scope=bot+applications.commands&permissions=51200
```

(`permissions=51200` = Send Messages + Embed Links + Attach Files — all Cred needs.)
Open it, pick your server, authorize. Done.

**About "messages read" / intents:** Cred uses **only slash commands**, whose data
arrives through the interaction payload — *not* through message content. So you do
**NOT** need the privileged **Message Content Intent** (the one that wants the
verification link). Leave all "Privileged Gateway Intents" OFF. Nothing else to do.

(Slash commands sync globally on first launch and can take up to ~1h to appear; if
you want them instantly, invite Cred to your server first, then restart Cred.)

## Files

- `cred.py` — the bot (single file, family style).
- `.env` — secrets (gitignored). `.env.example` — template.
- `run.sh` / `keepalive.sh` — launch + cron keepalive (run outside any sandbox).
- `TOS.md`, `PRIVACY.md`, `LICENSE`.

MIT. Part of PantoYT's DiscordBots family.
