# Vred – Vulcan Recurrent Education Dump

Vred is a Discord bot that automatically fetches and posts your school schedule and upcoming exams from the eduVULCAN platform.

## How to use
- Run `register.py` once to link your eduVULCAN account
- Add the bot to your server
- Use slash commands to view your timetable or upcoming tests
- To see all available commands, type `/commands`

## Features
- 📅 **Schedule**: View your lesson plan for today, tomorrow, or any day
- 📝 **Exams**: Browse upcoming tests and sprawdziany
- ⏰ **Next Exam**: Quick look at what's coming up first
- 🔔 **Auto Notifications**: Bot automatically checks for new exams every hour and posts them to your channel
- 🔀 **Substitution details**: shows what replaces a lesson (subject, teacher) and why it was cancelled
- 🌙 **Evening reminder**: at `REMINDER_HOUR` (default 19:00) posts tomorrow's exams with topics and timetable changes; on Sundays also a preview of the week; with `GROQ_API_KEY` set, every exam gets a 🧠 *Powtórka* button that generates the AI revision on click (cached, so a second click costs nothing)
- ⚠️ **Busy days**: warns when two or more exams fall on the same day
- 🎓 **Grade alerts**: DMs the owner about new or changed grades, with the subject average before → after
- ✉️ **Message alerts**: DMs the owner every new eduVULCAN message (checked every `MESSAGES_INTERVAL` minutes); reading the list does not mark messages as read
- 📚 **Homework**: posts new homework to the exams channel; tomorrow's homework is part of the evening reminder
- 🚸 **Attendance alerts**: DMs the owner when a lesson is marked absent or late
- 🏁 **Proposed / final grades**: DMs the owner when a proposed or final grade appears or changes
- 🌟 **Notes**: DMs the owner about new uwagi / pochwały
- 🧠 **AI study help** (optional, free): `/powtorka` builds a revision sheet for the next exam and `/szukaj` answers a question — both search the web first and list their sources (Groq, `openai/gpt-oss-120b` with `browser_search`)

## Available Commands
- `/plan` — Lesson plan for today
- `/jutro` — Lesson plan for tomorrow
- `/dzien <offset>` — Lesson plan N days from today
- `/sprawdziany [tygodnie]` — Upcoming exams (default 2 weeks)
- `/nastepny` — Time until the next exam
- `/srednie` — Weighted averages for the current period (owner only, ephemeral)
- `/powtorka [przedmiot]` — AI revision for the next exam (or the next one of that subject), with sources
- `/szukaj <pytanie>` — AI answer grounded in a web search, with sources
- `/zadania [dni]` — Homework due in the next N days (default 14)
- `/tematy [offset]` — Lesson topics for a day (0 = today, -1 = yesterday)
- `/frekwencja` — Attendance in the current period, per subject (owner only, ephemeral)
- `/wiadomosci [ile]` — Latest eduVULCAN messages (owner only, ephemeral, max 10)

### Owner Commands
- `/info` — Bot status (owner only)
- `/sync` — Force sync slash commands (owner only)
- `/shutdown` — Shut down the bot (owner only)

## Running your own instance
1. Create a `.env` file containing:
   - `OWNER_ID` — Your Discord user ID
   - `DISCORD_TOKEN` — Your Discord bot token
   - `SCHEDULE_CHANNEL` — Channel name for schedule (default: `plan-lekcji`)
   - `EXAMS_CHANNEL` — Channel name for exam notifications (default: `sprawdziany`)
   - `CHECK_INTERVAL` — How often to check for new exams in minutes (default: `60`)
   - `MESSAGES_INTERVAL` — How often to check for new messages in minutes (default: `15`)
   - `GROQ_API_KEY` — optional, enables `/powtorka` and `/szukaj`; free key at https://console.groq.com/keys (no card)
   - `GROQ_MODEL` / `GROQ_FALLBACK_MODEL` — defaults `openai/gpt-oss-120b` / `openai/gpt-oss-20b`; the free tier limits tokens per minute per model, so the fallback answers while the main one cools down
2. Install all required Python packages from `requirements.txt`:
   ```bash
   py -3.12 -m pip install -r requirements.txt -r requirements-register.txt
   py -3.12 -m playwright install chromium
   ```
3. Register your eduVULCAN account (run once):
   ```bash
   py -3.12 register.py
   ```
4. Run the bot:
   ```bash
   py -3.12 main.py
   ```
   Or use `vred_launch.vbs` to run it silently in the background.
5. To shut down the bot, use the `/shutdown` command.

## Running in Docker
State and secrets live in a data directory (`VRED_DATA_DIR`, default: next to the script).
Put `.env`, `credentials.json` and optionally `google_calendar_token.json` in `./data`, then:
```bash
docker compose up -d --build
docker logs -f vred
```

## Google Calendar sync and the OAuth login
An OAuth app in **Testing** status gets refresh tokens that expire after 7 days, so the
consent screen is set to **In production** (no verification needed for personal use —
you will see an "unverified app" warning on consent). Tokens issued after that do not
expire on their own; Vred sends the owner a DM only if Google rejects the token
(revoked access, about six months unused), and then `calendar_auth.py` is run again.
On a headless server, run `calendar_auth.py` on a machine with a browser and copy
`google_calendar_token.json` into the data directory.

## Notes
- `python logic.py` runs the selftest for the pure logic (substitutions, averages, busy days)
- Grade averages use the same convention as VulcanScope: `+` = +0.5, `-` = −0.25, weighted by column weight
- Requires Python 3.12 (vulcan API dependency does not support 3.14+)
- `credentials.json` is generated by `register.py` — keep it private, do not commit it
- Uses the eduVULCAN Hebe mobile API — the same API as the official mobile app
- Exam notifications are deduplicated via `seen_exams.json`
