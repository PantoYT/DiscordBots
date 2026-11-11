# Vred – Vulcan Recurrent Education Dump

Vred is a Discord bot that automatically fetches and posts your school schedule and upcoming exams from the eduVULCAN platform.

## How to use
- Run `register.py` once to link your eduVULCAN account
- Add the bot to your server
- Use slash commands to view your timetable or upcoming tests
- To see all available commands, type `/help`

The bot speaks English; data from the register (subjects, topics, exam descriptions)
stays in Polish, and AI answers default to Polish (`AI_LANGUAGE`) because the exams are.

## Features
- 📅 **Schedule**: View your lesson plan for today, tomorrow, or any day
- 📝 **Exams**: Browse upcoming tests (sprawdziany, kartkówki)
- ⏰ **Next Exam**: Quick look at what's coming up first
- 🔔 **Auto Notifications**: Bot automatically checks for new exams every hour and posts them to your channel
- 🔁 **Exam changes**: when an announced exam is moved to another day or its scope is rewritten, the exams channel gets an old → new notice
- 🔀 **Substitution details**: shows what replaces a lesson (subject, teacher) and why it was cancelled
- 🌙 **Evening reminder**: at `REMINDER_HOUR` (default 19:00) posts tomorrow's exams with topics and timetable changes; with `GROQ_API_KEY` set, every exam gets a 🧠 *Revise* button (cached, so a second click costs nothing) and exams in the next 3 days with unresolved quiz mistakes get a 🔁 button
- 🗓️ **Sunday preview and heavy weeks**: on Sundays the reminder adds the week ahead; with 3 or more exams it also lays out a study plan — a first pass 2–3 days before each exam on the least loaded day, a final review the day before
- 🌅 **Morning alert**: at `MORNING_ALERT` (default 06:30) compares today's timetable with the snapshot taken by the evening reminder and posts what changed overnight
- ⚠️ **Busy days**: warns when two or more exams fall on the same day
- 🎓 **Grade alerts**: DMs the owner about new or changed grades, with the subject average before → after
- 📉📈 **Grades on the edge**: DMs the owner once when a subject's average comes within 0.15 of a final-grade threshold — about to drop, or one good grade from the next final grade
- 📚 **Homework**: posts new homework to the exams channel; tomorrow's homework is part of the evening reminder
- 🚸 **Attendance alerts**: DMs the owner when a lesson is marked absent or late; an absence comes with a *What did I miss?* button
- 🧾 **Missed lessons**: topics of the lessons you missed, upcoming exams and homework in those subjects, and an AI catch-up on the topics
- 🏁 **Proposed / final grades**: DMs the owner when a proposed or final grade appears or changes
- 🌟 **Notes**: DMs the owner about new uwagi / pochwały
- 🍀 **Lucky number**: with `LUCKY_NUMBER` set to your register number, a DM on the days it is drawn
- 📬 **Weekly digest**: a DM at `WEEKLY_DIGEST` (default `fri 15:00`) with the week's grades and average changes, attendance, subjects on the edge, next week's exams and homework, and waiting quiz mistakes
- 🗄️ **Topic archive**: every lesson topic is kept in `topics_archive.json` (first run backfills the current term), so `/find` keeps working after the register stops serving last year
- 📆 **Google Calendar**: the timetable in a coloured `Lekcje` calendar, and exams plus homework as all-day events with reminders (18:00 the day before, and two days before an exam) in a separate `Exams & homework` calendar
- 🧠 **AI study help** (optional, free): revision sheets, quizzes and answers from Groq (`openai/gpt-oss-120b`); revisions and answers search the web first and list their sources
- ✉️ **Messages**: since November 2026 eduVULCAN serves register messages only to Premium accounts (`EDUVULCAN_PREMIUM`); Vred stops polling after the first such answer

## Available Commands
- `/today` — Timetable for today (in the timetable channel it updates the pinned message)
- `/tomorrow` — Timetable for tomorrow
- `/day <offset>` — Timetable N days from today
- `/week [which]` — Whole week: previous, current or next
- `/exams [weeks]` — Upcoming exams (default 2 weeks)
- `/next` — Time until the next exam
- `/revise [exam]` — AI revision for an exam picked from the list (type to filter; empty = the next exam), with sources; the scope comes from the register's lesson topics since the last test in that subject (for a retake: the topics before it), so a bare label like "Unit 8" is no longer guessed from some random textbook. Teachers who run several vocational subjects mix material between them, so their other subjects' topics are added when they share a keyword with the exam description. The answer has a 🧩 *Quiz* button
- `/quiz [exam]` — Multiple-choice quiz for an exam picked from the list (8 questions, `QUIZ_QUESTIONS`) built from the revision; answers by buttons, an explanation after each, and the wrong ones are saved and offered again before the exam
- `/ask <question>` — AI answer grounded in a web search, with sources
- `/homework [days]` — Homework due in the next N days (default 14)
- `/topics [offset]` — Lesson topics for a day (0 = today, -1 = yesterday)
- `/find <query> [subject]` — Search every lesson topic of the year (diacritics ignored), newest first, with the date it first came up
- `/missed [days]` — Lessons you missed in the last N days (default 14) with their topics, plus an AI catch-up button (owner only, ephemeral)
- `/grades [target]` — Weighted averages for the current period plus the predicted final grade per subject (x.75 rounds up; owner only, ephemeral). With `target` (e.g. `4.75`) it targets the mean of final grades and lists the fewest grades to raise by one step, never to a 6, or says the target is out of reach
- `/attendance` — Attendance in the current period, per subject (owner only, ephemeral)
- `/messages [count]` — Latest eduVULCAN messages (owner only, ephemeral, max 10; needs eduVULCAN Premium)

### Owner Commands
- `/info` — Bot status (owner only)
- `/sync` — Force sync slash commands (owner only)
- `/shutdown` — Shut down the bot (owner only)

### Cost of the AI on the free Groq tier
The free tier allows 1000 requests a day, 8000 tokens a minute and 200K tokens a day per
model (the fallback model has its own budget). A revision or a catch-up searches the web and
costs 10–60k tokens, so it may wait for the per-minute limit, and a day allows roughly 4–8 of
them per model; revisions are cached per exam and day. A quiz is one JSON request without
search, about 2–3k tokens.

## Running your own instance
1. Create a `.env` file containing:
   - `OWNER_ID` — Your Discord user ID
   - `DISCORD_TOKEN` — Your Discord bot token
   - `SCHEDULE_CHANNEL` — Channel name for schedule (default: `timetable`; an old `plan-lekcji` channel is renamed on startup)
   - `EXAMS_CHANNEL` — Channel name for exam notifications (default: `exams`; an old `sprawdziany` channel is renamed on startup)
   - `CHECK_INTERVAL` — How often to check for new exams in minutes (default: `60`)
   - `MESSAGES_INTERVAL` — How often to check for new messages in minutes (default: `15`)
   - `GROQ_API_KEY` — optional, enables `/revise`, `/quiz`, `/ask` and the AI buttons; free key at https://console.groq.com/keys (no card)
   - `AI_LANGUAGE` — language of AI answers (default: `Polish`)
   - `REMINDER_HOUR` / `MORNING_ALERT` — evening reminder hour (default `19`) and morning check `HH:MM` (default `06:30`, empty disables)
   - `QUIZ_QUESTIONS` — questions per quiz (default `8`)
   - `LUCKY_NUMBER` — your number in the class register, for the lucky-number DM (optional)
   - `WEEKLY_DIGEST` — day and time of the weekly digest DM (default `fri 15:00`, empty disables)
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
- `python logic.py` runs the selftest for the pure logic (substitutions, averages, busy days, exam context, missed lessons, quiz parsing, grade edges, timetable diff, exam changes, calendar events, study plan)
- Grade averages use the same convention as VulcanScope: `+` = +0.5, `-` = −0.25, weighted by column weight
- Requires Python 3.12 (vulcan API dependency does not support 3.14+)
- `credentials.json` is generated by `register.py` — keep it private, do not commit it
- Uses the eduVULCAN Hebe mobile API — the same API as the official mobile app
- Exam notifications are deduplicated via `seen_exams.json`, which also keeps each exam's date and scope to detect changes
