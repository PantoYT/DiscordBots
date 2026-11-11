import discord
from discord.ext import commands, tasks
import asyncio
import os
import json
import secrets
from datetime import datetime, timedelta
from dotenv import load_dotenv
import pytz
import requests as req

from pathlib import Path

from client import VulcanClient
import ai
import calendar_sync
import logic

# State and secrets (credentials.json, Google token, seen_*.json) live in DATA_DIR —
# next to the script by default, on the volume in the container (VRED_DATA_DIR=/data).
DATA_DIR = Path(os.getenv("VRED_DATA_DIR") or Path(__file__).resolve().parent)
load_dotenv(DATA_DIR / ".env")

TOKEN            = os.getenv("DISCORD_TOKEN")
OWNER_ID         = int(os.getenv("OWNER_ID"))
SCHEDULE_CHANNEL = os.getenv("SCHEDULE_CHANNEL", "timetable")
EXAMS_CHANNEL    = os.getenv("EXAMS_CHANNEL", "exams")
# Channel names used before the bot went English (2026-11) — renamed in place on
# startup, so the history and the pinned timetable message stay.
LEGACY_CHANNELS = {SCHEDULE_CHANNEL: "plan-lekcji", EXAMS_CHANNEL: "sprawdziany"}
CHANNEL_TOPICS = {SCHEDULE_CHANNEL: "Timetable — kept up to date by Vred",
                  EXAMS_CHANNEL: "Exams, homework and reminders from Vred"}
CHECK_INTERVAL   = int(os.getenv("CHECK_INTERVAL", 60))

CET               = pytz.timezone("Europe/Warsaw")
SEEN_EXAMS_FILE   = DATA_DIR / "seen_exams.json"
SCHEDULE_MSG_FILE = DATA_DIR / "schedule_message.json"
SEEN_GRADES_FILE  = DATA_DIR / "seen_grades.json"
REMINDER_FILE     = DATA_DIR / "reminder_state.json"
CREDENTIALS_FILE  = DATA_DIR / "credentials.json"
SEEN_MESSAGES_FILE = DATA_DIR / "seen_messages.json"
SEEN_SCHOOL_FILE  = DATA_DIR / "seen_school.json"
GRADE_EDGES_FILE  = DATA_DIR / "grade_edges.json"
QUIZ_FILE         = DATA_DIR / "quiz_state.json"
TOPICS_FILE       = DATA_DIR / "topics_archive.json"
MESSAGES_INTERVAL = int(os.getenv("MESSAGES_INTERVAL", 15))
DAILY_HOUR        = int(os.getenv("DAILY_HOUR", 7))
REMINDER_HOUR     = int(os.getenv("REMINDER_HOUR", 19))
CALENDAR_SYNC_HOUR = int(os.getenv("CALENDAR_SYNC_HOUR", 20))
# HH:MM — compare today's timetable with the snapshot from the evening reminder;
# empty disables the morning alert.
MORNING_ALERT     = os.getenv("MORNING_ALERT", "06:30")
QUIZ_QUESTIONS    = int(os.getenv("QUIZ_QUESTIONS", 8))
# Your number in the class register — a DM when it is the lucky number of the day.
LUCKY_NUMBER      = int(os.getenv("LUCKY_NUMBER") or 0) or None
# "fri 15:00" — weekly digest DM; empty disables.
WEEKLY_DIGEST     = os.getenv("WEEKLY_DIGEST", "fri 15:00")
UPTIME_KUMA_URL   = os.getenv("UPTIME_KUMA_URL", "")
last_schedule_run: str | None = None
last_calendar_sync: str | None = None

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)

FOOTER = "Vred • eduVulcan bot"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def save_json(path: Path, data):
    """Atomic write — a crash halfway never leaves an empty state file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)


def load_json(path: Path, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def load_seen_exams() -> dict:
    """{exam_id: [date, content] | None}. Older versions stored a plain list of ids;
    those become None (= announced, details unknown, never reported as changed)."""
    data = load_json(SEEN_EXAMS_FILE, {})
    return {str(i): None for i in data} if isinstance(data, list) else data


def get_client() -> VulcanClient:
    return VulcanClient(str(CREDENTIALS_FILE))


def find_channel(name: str):
    return discord.utils.get(bot.get_all_channels(), name=name)


def today_str(now: datetime | None = None) -> str:
    return (now or datetime.now(CET)).strftime("%Y-%m-%d")


async def owner_only(interaction: discord.Interaction, what: str) -> bool:
    if interaction.user.id == OWNER_ID:
        return True
    await interaction.response.send_message(f"Only the owner can see {what}.", ephemeral=True)
    return False


async def ai_ready(interaction: discord.Interaction) -> bool:
    if ai.enabled():
        return True
    await interaction.response.send_message("AI is off — `GROQ_API_KEY` is missing from .env.", ephemeral=True)
    return False


def build_schedule_table(lessons: list, date_str: str) -> discord.Embed:
    embed = discord.Embed(title=f"📅 Timetable — {fmt_date(date_str)}", color=VRED_COLOR)

    if not lessons:
        embed.description = "```\nNo lessons this day.\n```"
        embed.set_footer(text=FOOTER)
        return embed

    views = sorted((logic.lesson_view(l) for l in lessons), key=lambda v: v["pos"])

    rows = []
    changes = []
    for v in views:
        flag = {"cancelled": " x", "subst": " !"}.get(v["kind"], "  ")
        rows.append((str(v["pos"]), v["time"], v["subject"][:24], v["room"] or "  -  ", flag))
        if v["kind"] != "normal":
            changes.append(f"`{v['pos']}.` **{v['subject']}** {logic.change_text(v)}")

    w_pos  = max(len(r[0]) for r in rows)
    w_time = max(len(r[1]) for r in rows)
    w_subj = max(len(r[2]) for r in rows)
    w_room = max(len(r[3]) for r in rows)

    header = f"{'No':<{w_pos}}  {'Time':<{w_time}}  {'Subject':<{w_subj}}  {'Room':<{w_room}}"
    sep    = "─" * len(header)
    lines  = [header, sep]
    for pos, time, subj, room, flag in rows:
        lines.append(f"{pos:<{w_pos}}  {time:<{w_time}}  {subj:<{w_subj}}  {room:<{w_room}}{flag}")

    embed.description = f"```\n{chr(10).join(lines)}\n```"
    if changes:
        embed.add_field(name="Changes", value="\n".join(changes)[:1024], inline=False)
        embed.set_footer(text=f"! = substitution  •  x = cancelled  •  {FOOTER}")
    else:
        embed.set_footer(text=FOOTER)
    return embed


async def post_or_edit_schedule(channel: discord.TextChannel, embed: discord.Embed):
    """Edit the existing message or post a new one — one message per channel."""
    data    = load_json(SCHEDULE_MSG_FILE, {})
    msg_id  = data.get(str(channel.id))
    if msg_id:
        try:
            msg = await channel.fetch_message(msg_id)
            await msg.edit(embed=embed)
            return
        except (discord.NotFound, discord.HTTPException):
            pass
    msg = await channel.send(embed=embed)
    data[str(channel.id)] = msg.id
    save_json(SCHEDULE_MSG_FILE, data)


# ---------------------------------------------------------------------------
# Embeds
# ---------------------------------------------------------------------------

VRED_COLOR = 0x2F6FEB

SUBJECT_COLORS = {
    "matematyka":  0xF1C40F,
    "fizyka":      0x3498DB,
    "chemia":      0x2ECC71,
    "biologia":    0x27AE60,
    "historia":    0xE67E22,
    "geografia":   0x1ABC9C,
    "polski":      0xE74C3C,
    "angielski":   0x9B59B6,
    "informatyka": 0x2980B9,
}


def subject_color(name: str) -> int:
    lower = name.lower()
    for key, color in SUBJECT_COLORS.items():
        if key in lower:
            return color
    return 0x95A5A6


WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def fmt_date(date_str: str) -> str:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{d.strftime('%d.%m.%Y')} ({WEEKDAYS[d.weekday()]})"
    except Exception:
        return date_str


def fmt_short(date_str: str) -> str:
    """'Tue 03.11'"""
    try:
        d = datetime.strptime(date_str[:10], "%Y-%m-%d")
        return f"{WEEKDAYS[d.weekday()][:3]} {d.strftime('%d.%m')}"
    except Exception:
        return date_str


def exam_subject(exam: dict) -> str:
    return (exam.get("Subject") or {}).get("Name", "?").strip()


def exam_label(exam: dict) -> str:
    return f"{exam_subject(exam)} ({(exam.get('Type') or 'sprawdzian').lower()})"


exam_date = logic.exam_date


def exam_embed(exam: dict, all_exams: list | None = None) -> discord.Embed:
    """all_exams — when given, warns about other exams on the same day."""
    subject = exam_subject(exam)
    embed = discord.Embed(
        title=f"📝 {subject}",
        description=exam.get("Content") or "No description",
        color=subject_color(subject),
    )
    embed.add_field(name="Date",    value=fmt_date(exam_date(exam) or "?"), inline=True)
    embed.add_field(name="Type",    value=exam.get("Type") or "Sprawdzian",  inline=True)
    creator = exam.get("Creator", {})
    if creator:
        embed.add_field(name="Teacher", value=creator.get("DisplayName", "?"), inline=True)
    if all_exams:
        others = [e for e in all_exams
                  if exam_date(e) == exam_date(exam) and e.get("Id") != exam.get("Id")]
        if others:
            embed.add_field(name=f"⚠️ Also that day ({len(others)})",
                            value="\n".join(exam_label(e) for e in others), inline=False)
    embed.set_footer(text=FOOTER)
    return embed


def lesson_date(lesson: dict) -> str | None:
    """The API moved from nested Date.Date to flat DateAt — handle both."""
    return lesson.get("DateAt") or lesson.get("Date", {}).get("Date")


def lesson_line(lesson: dict) -> str:
    v        = logic.lesson_view(lesson)
    room_str = f" • room {v['room']}" if v["room"] else ""
    name     = f"~~{v['subject']}~~" if v["kind"] == "cancelled" else v["subject"]
    change   = logic.change_text(v)
    return f"`{v['pos']}.` **{v['time']}** {name}{room_str}{' ' + change if change else ''}"


def lesson_sort_key(lesson: dict) -> int:
    return logic.lesson_view(lesson)["pos"]


def schedule_embed(lessons: list, date_str: str) -> discord.Embed:
    embed = discord.Embed(title=f"📅 Timetable — {fmt_date(date_str)}", color=VRED_COLOR)
    if not lessons:
        embed.description = "No lessons this day."
        return embed
    embed.description = "\n".join(lesson_line(l) for l in sorted(lessons, key=lesson_sort_key))
    embed.set_footer(text=FOOTER)
    return embed


WEEK_LABELS = {"previous": "Previous week", "current": "This week", "next": "Next week"}


def week_embed(lessons: list, monday: datetime, which: str) -> discord.Embed:
    sunday = monday + timedelta(days=6)
    embed = discord.Embed(
        title=f"📅 {WEEK_LABELS.get(which, 'Week')} — "
              f"{monday.strftime('%d.%m')}–{sunday.strftime('%d.%m.%Y')}",
        color=VRED_COLOR,
    )
    by_date: dict[str, list] = {}
    for l in lessons:
        d = lesson_date(l)
        if d:
            by_date.setdefault(d, []).append(l)

    for offset in range(7):
        day = monday + timedelta(days=offset)
        day_lessons = sorted(by_date.get(day.strftime("%Y-%m-%d"), []), key=lesson_sort_key)
        value = "\n".join(lesson_line(l) for l in day_lessons) if day_lessons else "No lessons."
        embed.add_field(name=f"{WEEKDAYS[offset]} {day.strftime('%d.%m')}", value=value[:1024], inline=False)

    embed.set_footer(text=FOOTER)
    return embed


def presence_label(l: dict) -> str:
    p = l.get("PresenceType") or {}
    return "Absence" if p.get("Absence") else "Late" if p.get("Late") else (p.get("Name") or "?")


# ---------------------------------------------------------------------------
# Daily timetable post
# ---------------------------------------------------------------------------

@tasks.loop(minutes=1)
async def daily_schedule():
    global last_schedule_run
    now   = datetime.now(CET)
    today = today_str(now)
    if now.hour < DAILY_HOUR or last_schedule_run == today:
        return
    last_schedule_run = today

    channel = find_channel(SCHEDULE_CHANNEL)
    if not channel:
        return
    try:
        lessons = await asyncio.to_thread(get_client().get_lessons, now, now)
        day     = [l for l in lessons if lesson_date(l) == today]
        await post_or_edit_schedule(channel, build_schedule_table(day, today))
    except Exception as e:
        print(f"[daily_schedule] {e}")


@daily_schedule.before_loop
async def before_daily():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Google Calendar sync (coloured timetable + exams & homework)
# ---------------------------------------------------------------------------

async def run_calendar_sync(reason: str):
    """Blocking network work in a thread so the Discord gateway does not freeze.
    When Google rejects the refresh_token (revoked, ~6 months unused) the owner
    gets a DM with renewal steps."""
    global last_calendar_sync
    last_calendar_sync = today_str()
    try:
        result = await asyncio.to_thread(calendar_sync.sync)
        print(f"[calendar_sync:{reason}] {result}")
        tasks_result = await asyncio.to_thread(calendar_sync.sync_tasks)
        print(f"[calendar_sync:{reason}:tasks] {tasks_result}")
    except calendar_sync.CalendarAuthError as e:
        print(f"[calendar_sync:{reason}] AUTH EXPIRED: {e}")
        try:
            owner = await bot.fetch_user(OWNER_ID)
            await owner.send(
                "📅 Google rejected the calendar token — sync is stopped.\n"
                "On the PC in the Vred folder: `py -3.12 calendar_auth.py`, then\n"
                "`scp google_calendar_token.json ubuntu@100.117.148.97:~/vred/data/` "
                "and `docker restart vred` on the server."
            )
        except Exception as dm_err:
            print(f"[calendar_sync:{reason}] could not send DM: {dm_err}")
    except Exception as e:
        print(f"[calendar_sync:{reason}] error: {e}")


@tasks.loop(minutes=1)
async def calendar_sync_task():
    now = datetime.now(CET)
    if last_calendar_sync == today_str(now) or now.hour < CALENDAR_SYNC_HOUR:
        return
    await run_calendar_sync("daily")


@calendar_sync_task.before_loop
async def before_calendar_sync():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# New and changed exams
# ---------------------------------------------------------------------------

def exam_change_embed(exam: dict, old_date: str, old_content: str) -> discord.Embed:
    subject = exam_subject(exam)
    lines = []
    if old_date != exam_date(exam):
        lines.append(f"Date: ~~{fmt_date(old_date)}~~ → **{fmt_date(exam_date(exam))}**")
    if old_content != (exam.get("Content") or "").strip():
        lines.append(f"Scope: ~~{old_content or '—'}~~ → **{(exam.get('Content') or '—').strip()}**")
    embed = discord.Embed(title=f"🔁 Exam changed: {exam_label(exam)}", description="\n".join(lines)[:4000],
                          color=subject_color(subject))
    embed.set_footer(text=FOOTER)
    return embed


@tasks.loop(minutes=CHECK_INTERVAL)
async def check_exams():
    await bot.wait_until_ready()
    channel = find_channel(EXAMS_CHANNEL)
    if not channel:
        return
    try:
        now   = datetime.now(CET)
        exams = await asyncio.to_thread(get_client().get_exams, now, now + timedelta(weeks=4))
        seen  = load_seen_exams()
        for exam, old_date, old_content in logic.exam_changes(exams, seen):
            await channel.send(embed=exam_change_embed(exam, old_date, old_content))
        for exam in exams:
            if str(exam["Id"]) not in seen:
                await channel.send(embed=exam_embed(exam, exams))
        seen.update(logic.exam_state(exams))
        save_json(SEEN_EXAMS_FILE, seen)
    except Exception as e:
        print(f"[check_exams] {e}")


# ---------------------------------------------------------------------------
# Evening reminder — tomorrow's exams, homework and timetable changes
# ---------------------------------------------------------------------------

async def build_reminder(now: datetime) -> tuple[discord.Embed | None, list, dict]:
    """(embed, tomorrow's exams, tomorrow's timetable signature)."""
    client   = get_client()
    tomorrow = now + timedelta(days=1)
    t_str    = tomorrow.strftime("%Y-%m-%d")
    exams    = await asyncio.to_thread(client.get_exams, tomorrow, tomorrow + timedelta(days=7))
    lessons  = await asyncio.to_thread(client.get_lessons, tomorrow, tomorrow)
    homework = await asyncio.to_thread(client.get_homework, tomorrow, tomorrow)
    signature = logic.plan_signature(lessons, t_str)

    embed = discord.Embed(title=f"🔔 Tomorrow — {fmt_date(t_str)}", color=VRED_COLOR)
    t_exams = [e for e in exams if exam_date(e) == t_str]
    if t_exams:
        warn = " ⚠️" if len(t_exams) >= 2 else ""
        embed.add_field(
            name=f"📝 Exams ({len(t_exams)}){warn}",
            value="\n".join(f"**{exam_label(e)}** — {e.get('Content') or 'no description'}"
                            for e in t_exams)[:1024],
            inline=False,
        )
    t_hw = [h for h in homework if (h.get("DeadlineAt") or "")[:10] == t_str]
    if t_hw:
        embed.add_field(name=f"📚 Homework ({len(t_hw)})",
                        value="\n".join(homework_line(h) for h in t_hw)[:1024], inline=False)
    changes = []
    for v in sorted((logic.lesson_view(l) for l in lessons if lesson_date(l) == t_str),
                    key=lambda v: v["pos"]):
        if v["kind"] != "normal":
            changes.append(f"`{v['pos']}.` **{v['subject']}** {logic.change_text(v)}")
    if changes:
        embed.add_field(name="🔀 Timetable changes", value="\n".join(changes)[:1024], inline=False)

    # Sundays: the whole week ahead, and a study plan when it is a heavy one
    if now.weekday() == 6:
        week = logic.exams_by_day(exams)
        if week:
            lines = []
            for d, es in week.items():
                mark = " ⚠️" if len(es) >= 2 else ""
                lines.append(f"**{fmt_date(d)}**{mark}: " + ", ".join(exam_label(e) for e in es))
            embed.add_field(name="🗓️ This week", value="\n".join(lines)[:1024], inline=False)
        total = sum(len(es) for es in week.values())
        if total >= logic.HEAVY_WEEK:
            plan = logic.study_plan(exams, today_str(now))
            lines = [f"**{fmt_short(d)}** — " + "; ".join(f"{kind}: {exam_subject(e)}" for kind, e in items)
                     for d, items in plan.items()]
            embed.add_field(name=f"🧠 Study plan — {total} exams this week",
                            value=("\n".join(lines) + "\n*First pass = read the revision; "
                                   "final review = quiz and mistakes.*")[:1024], inline=False)

    if not embed.fields:
        return None, [], signature
    embed.set_footer(text=FOOTER)
    return embed, t_exams, signature


@tasks.loop(minutes=1)
async def evening_reminder():
    now   = datetime.now(CET)
    today = today_str(now)
    if now.hour < REMINDER_HOUR:
        return
    state = load_json(REMINDER_FILE, {})
    if state.get("last") == today:
        return
    channel = find_channel(EXAMS_CHANNEL)
    if not channel:
        return
    try:
        embed, t_exams, signature = await build_reminder(now)
        view = reminder_view(t_exams, quiz_mistakes_due(now))
        if embed:
            await channel.send(embed=embed, **({"view": view} if view else {}))
        elif view:
            await channel.send("🧩 Quiz mistakes waiting before upcoming exams:", view=view)
        # Saved only after success — on a Vulcan error it retries in a minute.
        state.update(last=today, snapshot={"date": (now + timedelta(days=1)).strftime("%Y-%m-%d"),
                                           "sig": signature})
        save_json(REMINDER_FILE, state)
    except Exception as e:
        print(f"[evening_reminder] {e}")


@evening_reminder.before_loop
async def before_reminder():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Morning alert — the timetable changed after the evening reminder
# ---------------------------------------------------------------------------

def morning_due(now: datetime) -> bool:
    if not MORNING_ALERT:
        return False
    h, m = (int(x) for x in MORNING_ALERT.split(":"))
    return (now.hour, now.minute) >= (h, m)


@tasks.loop(minutes=1)
async def morning_alert():
    now   = datetime.now(CET)
    today = today_str(now)
    state = load_json(REMINDER_FILE, {})
    snap  = state.get("snapshot") or {}
    if not morning_due(now) or state.get("morning") == today or snap.get("date") != today:
        return
    channel = find_channel(EXAMS_CHANNEL)
    if not channel:
        return
    try:
        lessons = await asyncio.to_thread(get_client().get_lessons, now, now)
        lines   = logic.plan_diff(snap.get("sig") or {}, logic.plan_signature(lessons, today))
        if lines:
            embed = discord.Embed(title=f"🔀 Today's timetable changed since last evening — {fmt_date(today)}",
                                  description="\n".join(lines)[:4000], color=0xE5534B)
            embed.set_footer(text=FOOTER)
            await channel.send(embed=embed)
        state["morning"] = today
        save_json(REMINDER_FILE, state)
    except Exception as e:
        print(f"[morning_alert] {e}")


@morning_alert.before_loop
async def before_morning():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Lucky number — a DM when it is yours (no questioning today)
# ---------------------------------------------------------------------------

@tasks.loop(minutes=10)
async def lucky_check():
    now   = datetime.now(CET)
    today = today_str(now)
    if not LUCKY_NUMBER or not (6 <= now.hour < 16):
        return
    state = load_json(REMINDER_FILE, {})
    if state.get("lucky") == today:
        return
    try:
        n = await asyncio.to_thread(get_client().get_lucky_number)
        if n is None:            # not drawn yet, weekend or holiday — try again later
            return
        if int(n) == LUCKY_NUMBER:
            owner = await bot.fetch_user(OWNER_ID)
            await owner.send(embed=discord.Embed(
                title=f"🍀 Lucky number today: {n} — that's you",
                description="You should not be questioned today.", color=0x3FB950).set_footer(text="Vred"))
        state["lucky"] = today
        save_json(REMINDER_FILE, state)
    except Exception as e:
        print(f"[lucky_check] {e}")


@lucky_check.before_loop
async def before_lucky():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Weekly digest — a DM on Friday afternoon (grades are private)
# ---------------------------------------------------------------------------

def digest_due(now: datetime) -> bool:
    if not WEEKLY_DIGEST:
        return False
    day, hm = WEEKLY_DIGEST.lower().split()
    h, m = (int(x) for x in hm.split(":"))
    return WEEKDAYS[now.weekday()][:3].lower() == day[:3] and (now.hour, now.minute) >= (h, m)


async def build_digest(now: datetime) -> discord.Embed:
    client = get_client()
    monday = now - timedelta(days=now.weekday())
    mon_s  = monday.strftime("%Y-%m-%d")
    nxt_lo = monday + timedelta(days=7)
    nxt_hi = monday + timedelta(days=13)
    grades   = await asyncio.to_thread(client.get_grades)
    lessons  = await asyncio.to_thread(client.get_attendance, monday, now)
    exams    = await asyncio.to_thread(client.get_exams, nxt_lo, nxt_hi)
    homework = await asyncio.to_thread(client.get_homework, nxt_lo, nxt_hi)

    embed = discord.Embed(title=f"📬 Week {monday.strftime('%d.%m')}–{now.strftime('%d.%m')}", color=VRED_COLOR)
    wg = logic.week_grades(grades, mon_s)
    embed.add_field(name=f"🎓 Grades ({sum(len(v['new']) for v in wg.values())})", inline=False, value="\n".join(
        f"**{s}**: {', '.join(g.get('Content') or '?' for g in v['new'])} — "
        f"avg {fmt_avg(v['before'])} → **{fmt_avg(v['after'])}**" for s, v in wg.items())[:1024] or "No new grades.")

    stats = logic.attendance_stats(lessons).get("", (0, 0))
    issues = [l for l in lessons if logic.presence_issue(l)]
    value = f"{stats[0]}/{stats[1]} present" if stats[1] else "No attendance entered yet."
    if issues:
        value += "\n" + "\n".join(f"`{fmt_short(l.get('DayAt') or '')}` {(l.get('Subject') or {}).get('Name', '?')}: "
                                  f"{presence_label(l)}" for l in issues[:10])
    embed.add_field(name="🚸 Attendance", value=value[:1024], inline=False)

    edges = logic.grade_edges(by_subject(grades))
    if edges:
        embed.add_field(name="📉📈 On the edge", inline=False, value="\n".join(
            f"{'📉' if st.startswith('drop') else '📈'} {s} ({fmt_avg(logic.raw_avg(by_subject(grades)[s]))})"
            for s, st in edges.items())[:1024])

    exams = sorted(exams, key=lambda e: exam_date(e) or "")
    embed.add_field(name=f"📝 Next week's exams ({len(exams)})", inline=False, value="\n".join(
        f"**{fmt_short(exam_date(e))}** {exam_label(e)} — {' '.join((e.get('Content') or '').split())[:100]}"
        for e in exams)[:1024] or "None so far.")
    if homework:
        embed.add_field(name=f"📚 Next week's homework ({len(homework)})", inline=False, value="\n".join(
            f"**{fmt_short(h.get('DeadlineAt') or '')}** {homework_line(h)}" for h in homework[:8])[:1024])
    mistakes = sum(len(m["questions"]) for m in quiz_load()["mistakes"].values())
    if mistakes:
        embed.add_field(name="🧩 Quiz", value=f"{mistakes} saved mistakes waiting before upcoming exams.", inline=False)
    embed.set_footer(text="Vred • weekly digest")
    return embed


@tasks.loop(minutes=1)
async def weekly_digest():
    now   = datetime.now(CET)
    today = today_str(now)
    if not digest_due(now):
        return
    state = load_json(REMINDER_FILE, {})
    if state.get("digest") == today:
        return
    try:
        owner = await bot.fetch_user(OWNER_ID)
        await owner.send(embed=await build_digest(now))
        state["digest"] = today
        save_json(REMINDER_FILE, state)
    except Exception as e:
        print(f"[weekly_digest] {e}")


@weekly_digest.before_loop
async def before_digest():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Grades — DM to the owner (grades are private, never in a channel)
# ---------------------------------------------------------------------------

def fmt_avg(avg: float | None) -> str:
    return f"{avg:.2f}" if avg is not None else "—"


def grade_embed(g: dict, grades: list, fresh_ids: set, modified: bool) -> discord.Embed:
    col     = g.get("Column") or {}
    subject = logic.grade_subject(g)
    same    = [x for x in grades if logic.grade_subject(x) == subject]
    before  = logic.weighted_avg([x for x in same if str(x.get("Id")) not in fresh_ids])
    after   = logic.weighted_avg(same)
    title   = "✏️ Changed grade" if modified else "🎓 New grade"
    embed = discord.Embed(
        title=f"{title}: {g.get('Content') or '?'} — {subject}",
        description=col.get("Name") or None,
        color=subject_color(subject),
    )
    embed.add_field(name="Weight", value=f"{col.get('Weight', 0):g}", inline=True)
    embed.add_field(name="Category", value=(col.get("Category") or {}).get("Name") or "—", inline=True)
    if not modified:
        trend = "" if before is None or after is None else (" 📈" if after > before else " 📉" if after < before else "")
        embed.add_field(name="Average", value=f"{fmt_avg(before)} → **{fmt_avg(after)}**{trend}", inline=True)
    else:
        embed.add_field(name="Average", value=f"**{fmt_avg(after)}**", inline=True)
    if g.get("Comment"):
        embed.add_field(name="Comment", value=g["Comment"][:1024], inline=False)
    embed.set_footer(text=f"{(g.get('Creator') or {}).get('DisplayName', '')} • Vred")
    return embed


def by_subject(grades: list) -> dict[str, list]:
    out: dict[str, list] = {}
    for g in grades:
        out.setdefault(logic.grade_subject(g), []).append(g)
    return out


def edge_embed(subject: str, state: str, grades: list) -> discord.Embed:
    kind, final = state.split(":")
    final = int(final)
    avg = logic.raw_avg(grades) or 0
    if kind == "drop":
        line = final - 1 + logic.ROUND_UP_FROM
        title = f"📉 {subject}: {avg:.2f}, just {avg - line:.2f} above the line for {final}"
        text = f"One weak grade can drop the predicted final from **{final}** to **{final - 1}**."
    else:
        line = final + logic.ROUND_UP_FROM
        title = f"📈 {subject}: {avg:.2f}, only {line - avg:.2f} below {final + 1}"
        text = (f"One good grade can lift the predicted final from **{final}** to **{final + 1}** "
                f"— `/grades target:` shows which grades to fix.")
    embed = discord.Embed(title=title, description=text, color=0xE5534B if kind == "drop" else 0x3FB950)
    embed.set_footer(text=f"Final grade rounds up from x.{int(logic.ROUND_UP_FROM * 100)} • Vred")
    return embed


@tasks.loop(minutes=CHECK_INTERVAL)
async def check_grades():
    try:
        grades = await asyncio.to_thread(get_client().get_grades)
        first_run = not SEEN_GRADES_FILE.exists()
        seen = load_json(SEEN_GRADES_FILE, {})
        new, modified = logic.grade_changes(grades, seen)
        owner = None
        if (new or modified) and not first_run:
            owner = await bot.fetch_user(OWNER_ID)
            fresh_ids = {str(g.get("Id")) for g in new}
            batch = [(g, False) for g in new] + [(g, True) for g in modified]
            for g, is_mod in batch[:10]:
                await owner.send(embed=grade_embed(g, grades, fresh_ids, is_mod))
            if len(batch) > 10:
                await owner.send(f"…and {len(batch) - 10} more grade changes — `/grades`.")
        # The first run only remembers the state, so the DM is not flooded with history.
        seen.update({str(g.get("Id")): g.get("Content") or "" for g in grades})
        save_json(SEEN_GRADES_FILE, seen)

        subjects = by_subject(grades)
        edges = logic.grade_edges(subjects)
        seen_edges = load_json(GRADE_EDGES_FILE, None)
        if seen_edges is not None:
            for subject, state in logic.edge_alerts(edges, seen_edges)[:5]:
                owner = owner or await bot.fetch_user(OWNER_ID)
                await owner.send(embed=edge_embed(subject, state, subjects[subject]))
        save_json(GRADE_EDGES_FILE, edges)
    except Exception as e:
        print(f"[check_grades] {e}")


@check_grades.before_loop
async def before_grades():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Register messages — DM to the owner (personal data, never in a channel)
# ---------------------------------------------------------------------------
# Since 2026-11 eduVULCAN answers the mobile messages endpoint with
# {'Code': 111, 'Message': 'EDUVULCAN_PREMIUM'}: messages are a paid feature.
PREMIUM_ONLY = "EDUVULCAN_PREMIUM"


def fmt_sent(sent_at: str | None) -> str:
    try:
        return datetime.fromisoformat((sent_at or "")[:19]).strftime("%d.%m.%Y %H:%M")
    except ValueError:
        return sent_at or "?"


def message_embed(m: dict, max_len: int = 4000) -> discord.Embed:
    text = logic.html_to_text(m.get("Content"))
    if len(text) > max_len:
        text = text[:max_len] + "\n…(cut — full text in eduVULCAN)"
    embed = discord.Embed(
        title=f"✉️ {(m.get('Subject') or '(no subject)')[:240]}",
        description=text or None,
        color=VRED_COLOR,
    )
    embed.set_author(name=(m.get("Sender") or {}).get("Name") or "?")
    if m.get("Attachments"):
        embed.add_field(name="Attachments", value=f"{len(m['Attachments'])} — open in eduVULCAN", inline=False)
    embed.set_footer(text=f"{fmt_sent(m.get('SentAt'))} • Vred")
    return embed


@tasks.loop(minutes=MESSAGES_INTERVAL)
async def check_messages():
    try:
        messages = await asyncio.to_thread(get_client().get_messages)
        first_run = not SEEN_MESSAGES_FILE.exists()
        seen = set(load_json(SEEN_MESSAGES_FILE, []))
        fresh = logic.new_messages(messages, seen)
        if fresh and not first_run:
            owner = await bot.fetch_user(OWNER_ID)
            for m in fresh[:10]:
                await owner.send(embed=message_embed(m))
            if len(fresh) > 10:
                await owner.send(f"…and {len(fresh) - 10} more messages — `/messages`.")
        # The first run only remembers the inbox, so the DM is not flooded with history.
        seen.update(str(m.get("Id")) for m in messages)
        save_json(SEEN_MESSAGES_FILE, sorted(seen))
    except Exception as e:
        if PREMIUM_ONLY in str(e):
            print("[check_messages] messages need eduVULCAN Premium — polling stopped until restart")
            check_messages.stop()
            return
        print(f"[check_messages] {e}")


@check_messages.before_loop
async def before_messages():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Homework (channel), attendance / notes / proposed grades (DM)
# ---------------------------------------------------------------------------

def homework_line(h: dict) -> str:
    subject = (h.get("Subject") or {}).get("Name", "?")
    return f"**{subject}** — {logic.html_to_text(h.get('Content'))[:300] or 'no description'}"


def homework_embed(h: dict) -> discord.Embed:
    subject = (h.get("Subject") or {}).get("Name", "?")
    deadline = (h.get("DeadlineAt") or "")[:10]
    embed = discord.Embed(
        title=f"📚 Homework — {subject}",
        description=logic.html_to_text(h.get("Content"))[:4000] or None,
        color=subject_color(subject),
    )
    embed.add_field(name="Due", value=fmt_date(deadline) if deadline else "?", inline=True)
    if h.get("IsAnswerRequired"):
        embed.add_field(name="Answer", value="required in eduVULCAN", inline=True)
    if h.get("Attachments"):
        embed.add_field(name="Attachments", value=f"{len(h['Attachments'])} — open in eduVULCAN", inline=True)
    embed.set_footer(text=f"{(h.get('Creator') or {}).get('DisplayName', '')} • Vred")
    return embed


def attendance_embed(l: dict) -> discord.Embed:
    subject = (l.get("Subject") or {}).get("Name", "?")
    slot    = l.get("TimeSlot") or {}
    embed = discord.Embed(
        title=f"🚸 {presence_label(l)} — {subject}",
        description=f"{fmt_date(l.get('DayAt') or '')}, lesson {slot.get('Position', '?')} ({slot.get('Display', '?')})",
        color=0xE5534B,
    )
    if l.get("Topic"):
        embed.add_field(name="Topic", value=l["Topic"][:1024], inline=False)
    embed.set_footer(text="Vred")
    return embed


def note_embed(n: dict) -> discord.Embed:
    positive = bool(n.get("Positive"))
    embed = discord.Embed(
        title=f"{'🌟 Praise' if positive else '⚠️ Remark'} — {(n.get('Category') or {}).get('Name') or 'no category'}",
        description=logic.html_to_text(n.get("Content"))[:4000] or None,
        color=0x3FB950 if positive else 0xE5534B,
    )
    if n.get("Points"):
        embed.add_field(name="Points", value=str(n["Points"]), inline=True)
    embed.set_footer(text=f"{(n.get('Creator') or {}).get('DisplayName', '')} • Vred")
    return embed


def current_period_start() -> datetime:
    for p in get_client().periods:
        if p.get("Current") and p.get("StartAt"):
            return CET.localize(datetime.strptime(p["StartAt"], "%Y-%m-%d"))
    return datetime.now(CET) - timedelta(days=60)


async def _check_section(name: str, state: dict, fn):
    """Each section on its own — one failing endpoint does not block the rest.
    A section missing from the state = first run, only remembers (no history flood)."""
    try:
        state[name] = await fn(name not in state, state.get(name))
    except Exception as e:
        print(f"[check_school:{name}] {e}")


@tasks.loop(minutes=CHECK_INTERVAL)
async def check_school():
    client = get_client()
    now    = datetime.now(CET)
    state  = load_json(SEEN_SCHOOL_FILE, {})
    owner  = await bot.fetch_user(OWNER_ID)

    async def homework(first, seen):
        items = await asyncio.to_thread(client.get_homework, now - timedelta(days=7), now + timedelta(days=60))
        seen = set(seen or [])
        channel = find_channel(EXAMS_CHANNEL)
        if not first and channel:
            for h in logic.new_by_id(items, seen)[:10]:
                await channel.send(embed=homework_embed(h))
        elif not first:
            return sorted(seen)  # no channel: do not mark as sent
        return sorted(seen | {str(h.get("Id")) for h in items})

    async def attendance(first, seen):
        lessons = await asyncio.to_thread(client.get_attendance, now - timedelta(days=14), now)
        seen = seen or {}
        if not first:
            for l in logic.attendance_changes(lessons, seen)[:10]:
                absent = (l.get("PresenceType") or {}).get("Absence")
                view = missed_view(l["DayAt"], l["DayAt"], explain=False) if absent else None
                await owner.send(embed=attendance_embed(l), **({"view": view} if view else {}))
        seen.update({str(l.get("Id")): (l.get("PresenceType") or {}).get("Id")
                     for l in lessons if l.get("PresenceType")})
        return seen

    async def notes(first, seen):
        items = await asyncio.to_thread(client.get_notes)
        seen = set(seen or [])
        if not first:
            for n in logic.new_by_id(items, seen)[:10]:
                await owner.send(embed=note_embed(n))
        return sorted(seen | {str(n.get("Id")) for n in items})

    async def summary(first, seen):
        items = await asyncio.to_thread(client.get_grades_summary)
        if not first:
            for s, label, val in logic.summary_changes(items, seen or {})[:10]:
                subject = (s.get("Subject") or {}).get("Name", "?")
                await owner.send(embed=discord.Embed(
                    title=f"🏁 {label.capitalize()} grade: {val} — {subject}",
                    color=subject_color(subject),
                ).set_footer(text="Vred"))
        return logic.summary_state(items)

    for name, fn in (("homework", homework), ("attendance", attendance),
                     ("notes", notes), ("summary", summary)):
        await _check_section(name, state, fn)
    save_json(SEEN_SCHOOL_FILE, state)


@check_school.before_loop
async def before_school():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Topic archive — kept locally so /find works across terms and school years
# ---------------------------------------------------------------------------
# lesson/byPupil only serves the periods the register still lists; at the start
# of a new school year last year's topics disappear from the API. The archive
# never forgets them. First run backfills each current period from its start.

ARCHIVE_CHUNK_DAYS = 30


def topics_load() -> dict:
    st = load_json(TOPICS_FILE, {})
    st.setdefault("lessons", {})
    st.setdefault("backfilled", [])
    return st


@tasks.loop(hours=6)
async def archive_topics():
    try:
        client = get_client()
        st  = topics_load()
        now = datetime.now(CET)
        added = 0
        for p in client.periods:
            pid = str(p.get("Id"))
            start = p.get("StartAt") or (p.get("Start") or {}).get("Date")
            if pid in st["backfilled"] or not start:
                continue
            cursor = CET.localize(datetime.strptime(start, "%Y-%m-%d"))
            while cursor <= now:
                end = min(cursor + timedelta(days=ARCHIVE_CHUNK_DAYS - 1), now)
                added += logic.archive_lessons(st["lessons"], await asyncio.to_thread(client.get_attendance, cursor, end))
                cursor = end + timedelta(days=1)
            st["backfilled"].append(pid)
        # regular run: the last two weeks catch late-entered topics and edits
        added += logic.archive_lessons(st["lessons"],
                                       await asyncio.to_thread(client.get_attendance, now - timedelta(days=14), now))
        save_json(TOPICS_FILE, st)
        if added:
            print(f"[archive_topics] {added} topics added or updated, {len(st['lessons'])} in total")
    except Exception as e:
        print(f"[archive_topics] {e}")


@archive_topics.before_loop
async def before_archive():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# AI: revision, quiz, missed lessons
# ---------------------------------------------------------------------------

def ai_embed(title: str, text: str, sources: list) -> discord.Embed:
    if len(text) > 3800:
        text = text[:3800] + "\n…(cut)"
    embed = discord.Embed(title=title[:256], description=text or "(empty answer)", color=VRED_COLOR)
    if sources:
        embed.add_field(name="Sources", inline=False, value="\n".join(
            f"[{i}] [{t[:80]}]({u})" for i, (t, u) in enumerate(sources[:8], 1))[:1024])
    embed.set_footer(text=f"Groq • {ai.MODEL} • AI can be wrong — check the sources")
    return embed


async def find_exam(exam_id: int) -> dict | None:
    now   = datetime.now(CET)
    exams = await asyncio.to_thread(get_client().get_exams, now - timedelta(days=1), now + timedelta(weeks=8))
    return next((e for e in exams if e.get("Id") == exam_id), None)


async def upcoming_exams() -> list:
    now   = datetime.now(CET)
    exams = await asyncio.to_thread(get_client().get_exams, now, now + timedelta(weeks=4))
    return sorted(exams, key=lambda e: exam_date(e) or "9999")


async def next_exam(subject: str = "") -> dict | None:
    """The exam picked in the autocomplete (its Id), else the next one whose
    subject contains the typed text, else simply the next one."""
    exams = await upcoming_exams()
    if subject.isdigit():
        picked = next((e for e in exams if str(e.get("Id")) == subject), None)
        if picked:
            return picked
    if subject:
        exams = [e for e in exams if subject.lower() in exam_label(e).lower()]
    return exams[0] if exams else None


# Autocomplete fires on every keystroke — the exam list is cached for a few minutes.
_exam_choices: dict = {"at": 0.0, "exams": []}


async def exam_autocomplete(interaction: discord.Interaction, current: str):
    import time
    if time.monotonic() - _exam_choices["at"] > 300:
        _exam_choices.update(at=time.monotonic(), exams=await upcoming_exams())
    cur, out = current.lower(), []
    for e in _exam_choices["exams"]:
        name = f"{fmt_short(exam_date(e))} · {exam_label(e)} · {(e.get('Content') or '').strip()}"
        name = " ".join(name.split())          # descriptions can be multi-line
        if cur in name.lower():
            out.append(discord.app_commands.Choice(name=name[:100], value=str(e["Id"])))
    return out[:25]


def fail(e: Exception) -> str:
    """AI limits are expected on the free tier — say it plainly, not as a crash."""
    return f"⏳ {e}" if isinstance(e, ai.AIError) else f"❌ `{e}`"


# One revision eats 10-60k tokens against an 8k/min limit — the result is kept in
# memory, and the lock makes two clicks at once generate it only once.
CONTEXT_WEEKS = 8   # lesson-topic window; cut at the last test of the subject anyway
_revision_cache: dict[str, dict] = {}
_revision_locks: dict[str, asyncio.Lock] = {}


async def exam_topics(exam: dict) -> dict:
    """Lesson topics behind the exam — a bare label like 'Unit 8' makes the model
    guess a textbook, the register's topics say what was actually covered."""
    try:
        now     = datetime.now(CET)
        lessons = await asyncio.to_thread(get_client().get_attendance,
                                          now - timedelta(weeks=CONTEXT_WEEKS), now)
        return logic.exam_context(exam, lessons)
    except Exception as e:
        print(f"[revision] no lesson topics: {e}")
        return {"own": [], "other": [], "since": None}


async def revision(exam: dict) -> dict:
    """{'embed', 'text', 'context'} — cached per exam, scope and day."""
    scope = (exam.get("Content") or "").strip() or "no description — only the subject name"
    # the date is in the key so a lesson topic added today reaches the context
    key = f"{exam.get('Id')}:{scope}:{today_str()}"
    async with _revision_locks.setdefault(key, asyncio.Lock()):
        if key not in _revision_cache:
            ctx = await exam_topics(exam)
            context = logic.context_prompt(ctx)
            prompt = (f"Subject: {exam_subject(exam)}. Type: {(exam.get('Type') or 'sprawdzian').lower()}. "
                      f"Scope given by the teacher: {scope}\n\n")
            if context:
                prompt += (context + "\n\nThese lesson topics are the actual scope — build the revision on them. "
                           "Use the search to fill in what these topics contain (rules, formulas, examples), "
                           "not to guess which textbook the teacher's label refers to. "
                           "Skip organisational topics and anything outside this list.\n\n")
            # No check questions here: gpt-oss kept dropping their answers (seen twice on
            # 2026-11-11, even with an explicit spoiler format). The Quiz button does that job.
            prompt += ("Write the revision, under 3000 characters in total: the key points, rules and "
                       "formulas as bullets (max ~12), each with a short example. No questions.")
            text, sources = await asyncio.to_thread(ai.ask, prompt, 2000)
            embed = ai_embed(f"🧠 Revision: {exam_label(exam)} — {fmt_date(exam_date(exam))}", text, sources)
            if ctx["own"] or ctx["other"]:
                used = f"{len(ctx['own'])} lesson topics"
                if ctx["since"]:
                    used += f" since the test on {ctx['since'][8:10]}.{ctx['since'][5:7]}"
                if ctx["other"]:
                    used += f" + {len(ctx['other'])} from the teacher's other subjects"
                embed.add_field(name="Scope from the register", value=used, inline=False)
            _revision_cache[key] = {"embed": embed, "text": text, "context": context}
    return _revision_cache[key]


async def send_revision(send, exam: dict):
    r = await revision(exam)
    view = discord.ui.View(timeout=None)
    view.add_item(QuizStartButton(exam["Id"]))
    await send(embed=r["embed"], view=view)


class RevisionButton(discord.ui.DynamicItem[discord.ui.Button], template=r"vred:powtorka:(?P<id>\d+)"):
    """Button under the evening reminder; custom_id carries the exam Id, so it keeps
    working after a restart (the id prefix is kept from the Polish version)."""

    def __init__(self, exam_id: int, label: str = "Revise"):
        super().__init__(discord.ui.Button(
            label=label[:80], emoji="🧠", style=discord.ButtonStyle.primary,
            custom_id=f"vred:powtorka:{exam_id}"))
        self.exam_id = exam_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["id"]), item.label or "Revise")

    async def callback(self, interaction: discord.Interaction):
        if not await ai_ready(interaction):
            return
        await interaction.response.defer(thinking=True)
        try:
            exam = await find_exam(self.exam_id)
            if not exam:
                await interaction.followup.send("This exam is no longer in the register.")
                return
            await send_revision(interaction.followup.send, exam)
        except Exception as e:
            await interaction.followup.send(fail(e))


# --- quiz --------------------------------------------------------------------
# State in quiz_state.json: quizzes[qid] = one run through the questions;
# mistakes[exam_id] = questions answered wrong in the last run, offered again in
# the evening reminder until the exam. Buttons carry ids, so they survive restarts.

_quiz_lock = asyncio.Lock()


def quiz_load() -> dict:
    st = load_json(QUIZ_FILE, {})
    st.setdefault("quizzes", {})
    st.setdefault("mistakes", {})
    return st


def quiz_save(st: dict):
    today = today_str()
    st["quizzes"] = {k: v for k, v in st["quizzes"].items() if v.get("deadline", "9999") >= today}
    st["mistakes"] = {k: v for k, v in st["mistakes"].items() if v.get("deadline", "9999") >= today}
    save_json(QUIZ_FILE, st)


def quiz_question_embed(qz: dict, feedback: str | None = None) -> discord.Embed:
    i, n = qz["pos"], len(qz["questions"])
    q = qz["questions"][i]
    embed = discord.Embed(
        title=f"🧩 {qz['label']} — question {i + 1}/{n}",
        description=f"**{q['q']}**\n\n" + "\n".join(f"**{L}.** {o}" for L, o in zip(logic.LETTERS, q["options"])),
        color=VRED_COLOR,
    )
    if feedback:
        embed.add_field(name="Previous question", value=feedback[:1024], inline=False)
    embed.set_footer(text=f"Score {qz['score']}/{i} • Vred")
    return embed


def quiz_view(qid: str, qz: dict) -> discord.ui.View:
    view = discord.ui.View(timeout=None)
    for k in range(4):
        view.add_item(QuizAnswerButton(qid, qz["pos"], k))
    return view


def quiz_summary(qz: dict, feedback: str) -> tuple[discord.Embed, discord.ui.View | None]:
    n, score, wrong = len(qz["questions"]), qz["score"], len(qz["wrong"])
    embed = discord.Embed(title=f"🧩 {qz['label']} — {score}/{n}", color=0x3FB950 if not wrong else VRED_COLOR)
    embed.add_field(name="Last question", value=feedback[:1024], inline=False)
    if wrong:
        embed.description = (f"{wrong} mistake{'s' if wrong > 1 else ''} saved — they come back "
                             f"under the evening reminder until the exam.")
        view = discord.ui.View(timeout=None)
        view.add_item(QuizRetryButton(int(qz["exam_id"]), wrong))
    else:
        embed.description = "All correct. 🎉"
        view = None
    embed.set_footer(text="Vred")
    return embed, view


async def build_quiz(exam: dict) -> tuple[str, dict]:
    r = await revision(exam)
    prompt = (
        f"Write {QUIZ_QUESTIONS} multiple-choice questions for a Polish secondary-school student "
        f"revising for: {exam_label(exam)}, scope given by the teacher: {(exam.get('Content') or '').strip()}.\n\n"
        + (r["context"] + "\n\n" if r["context"] else "")
        + f"Revision notes:\n\"\"\"\n{r['text']}\n\"\"\"\n\n"
        "Each question tests one concrete fact, rule or use of a rule from the notes. "
        "4 options, exactly one correct, plausible wrong options, no 'all of the above'. "
        "Check every wrong option: it must be clearly wrong in this exact sentence — if two tenses or "
        "forms could fit, add a time marker or context to the question so only one does. In gap-fill "
        "questions the options fill only the gap and do not repeat the words around it. "
        f"Write questions, options and explanations in {ai.LANGUAGE}; for a foreign-language exam the "
        "sentences being tested stay in that language. Keep options under 80 characters.\n"
        'Return JSON: {"questions": [{"q": "...", "options": ["...", "...", "...", "..."], '
        '"answer": <index 0-3 of the correct option>, "why": "one-sentence explanation"}]}'
    )
    data = await asyncio.to_thread(ai.ask_json, prompt)
    async with _quiz_lock:
        st = quiz_load()
        qid = secrets.token_hex(4)
        questions = logic.parse_quiz(data, qid)
        if len(questions) < 3:
            raise ai.AIError(f"the model gave only {len(questions)} usable questions — try again")
        st["quizzes"][qid] = {"exam_id": str(exam["Id"]), "label": exam_label(exam), "deadline": exam_date(exam),
                              "questions": questions, "pos": 0, "score": 0, "wrong": []}
        quiz_save(st)
    return qid, st["quizzes"][qid]


def quiz_mistakes_due(now: datetime, days: int = 3) -> list[tuple[int, int, str]]:
    """[(exam_id, count, label)] with saved mistakes for exams in the next `days` days."""
    lo, hi = today_str(now), (now + timedelta(days=days)).strftime("%Y-%m-%d")
    return [(int(eid), len(m["questions"]), m["label"]) for eid, m in quiz_load()["mistakes"].items()
            if m["questions"] and lo < m.get("deadline", "") <= hi]


class QuizStartButton(discord.ui.DynamicItem[discord.ui.Button], template=r"vred:quizstart:(?P<id>\d+)"):
    def __init__(self, exam_id: int):
        super().__init__(discord.ui.Button(label="Quiz", emoji="🧩", style=discord.ButtonStyle.secondary,
                                           custom_id=f"vred:quizstart:{exam_id}"))
        self.exam_id = exam_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["id"]))

    async def callback(self, interaction: discord.Interaction):
        if not await ai_ready(interaction):
            return
        await interaction.response.defer(thinking=True)
        try:
            exam = await find_exam(self.exam_id)
            if not exam:
                await interaction.followup.send("This exam is no longer in the register.")
                return
            qid, qz = await build_quiz(exam)
            await interaction.followup.send(embed=quiz_question_embed(qz), view=quiz_view(qid, qz))
        except Exception as e:
            await interaction.followup.send(fail(e))


class QuizAnswerButton(discord.ui.DynamicItem[discord.ui.Button],
                       template=r"vred:qa:(?P<qid>[0-9a-f]+):(?P<i>\d+):(?P<k>[0-3])"):
    def __init__(self, qid: str, i: int, k: int):
        super().__init__(discord.ui.Button(label=logic.LETTERS[k], style=discord.ButtonStyle.secondary,
                                           custom_id=f"vred:qa:{qid}:{i}:{k}"))
        self.qid, self.i, self.k = qid, i, k

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["qid"], int(match["i"]), int(match["k"]))

    async def callback(self, interaction: discord.Interaction):
        async with _quiz_lock:
            st = quiz_load()
            qz = st["quizzes"].get(self.qid)
            if not qz:
                await interaction.response.send_message("This quiz has expired.", ephemeral=True)
                return
            if qz["pos"] != self.i:
                await interaction.response.send_message("Already answered.", ephemeral=True)
                return
            q = qz["questions"][self.i]
            ok = self.k == q["answer"]
            if ok:
                qz["score"] += 1
            else:
                qz["wrong"].append(self.i)
            qz["pos"] += 1
            right = f"**{logic.LETTERS[q['answer']]}. {q['options'][q['answer']]}**"
            feedback = (f"✅ {right}" if ok else f"❌ You picked {logic.LETTERS[self.k]} — it was {right}")
            if q.get("why"):
                feedback += f"\n{q['why']}"
            done = qz["pos"] >= len(qz["questions"])
            if done:
                missed = [qz["questions"][j] for j in qz["wrong"]]
                if missed:
                    st["mistakes"][qz["exam_id"]] = {"label": qz["label"], "deadline": qz["deadline"],
                                                     "questions": missed}
                else:
                    st["mistakes"].pop(qz["exam_id"], None)
            quiz_save(st)
        if done:
            embed, view = quiz_summary(qz, feedback)
            await interaction.response.edit_message(embed=embed, view=view)
        else:
            await interaction.response.edit_message(embed=quiz_question_embed(qz, feedback),
                                                    view=quiz_view(self.qid, qz))


class QuizRetryButton(discord.ui.DynamicItem[discord.ui.Button], template=r"vred:qretry:(?P<id>\d+)"):
    def __init__(self, exam_id: int, count: int = 0, label: str = ""):
        text = label or (f"Retry {count} mistake{'s' if count != 1 else ''}" if count else "Retry mistakes")
        super().__init__(discord.ui.Button(label=text[:80], emoji="🔁", style=discord.ButtonStyle.primary,
                                           custom_id=f"vred:qretry:{exam_id}"))
        self.exam_id = exam_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["id"]), label=item.label or "")

    async def callback(self, interaction: discord.Interaction):
        async with _quiz_lock:
            st = quiz_load()
            m = st["mistakes"].get(str(self.exam_id))
            if not m or not m["questions"]:
                await interaction.response.send_message("No saved mistakes for this exam. ✅", ephemeral=True)
                return
            qid = secrets.token_hex(4)
            questions = logic.parse_quiz({"questions": m["questions"]}, qid)   # reshuffled options
            st["quizzes"][qid] = {"exam_id": str(self.exam_id), "label": f"{m['label']} — mistakes",
                                  "deadline": m["deadline"], "questions": questions,
                                  "pos": 0, "score": 0, "wrong": []}
            qz = st["quizzes"][qid]
            quiz_save(st)
        await interaction.response.send_message(embed=quiz_question_embed(qz), view=quiz_view(qid, qz))


def reminder_view(exams: list, retries: list) -> discord.ui.View | None:
    if not ai.enabled() or not (exams or retries):
        return None
    view = discord.ui.View(timeout=None)
    for e in exams[:5]:
        view.add_item(RevisionButton(e["Id"], f"Revise: {exam_subject(e)}"))
    for exam_id, count, label in retries[:5]:
        view.add_item(QuizRetryButton(exam_id, label=f"Mistakes ({count}): {label}"))
    return view


# --- missed lessons ----------------------------------------------------------

async def missed_report(since: str, until: str) -> tuple[discord.Embed, list]:
    client = get_client()
    now    = datetime.now(CET)
    lo     = CET.localize(datetime.strptime(since, "%Y-%m-%d"))
    hi     = CET.localize(datetime.strptime(until, "%Y-%m-%d"))
    lessons  = await asyncio.to_thread(client.get_attendance, lo, hi)
    missed   = logic.missed_lessons(lessons, since, until)
    exams    = await asyncio.to_thread(client.get_exams, now, now + timedelta(weeks=4))
    homework = await asyncio.to_thread(client.get_homework, now, now + timedelta(weeks=4))
    ex, hw   = logic.missed_followups(missed, exams, homework, today_str(now))

    span = fmt_short(since) if since == until else f"{fmt_short(since)} – {fmt_short(until)}"
    embed = discord.Embed(title=f"🧾 What you missed — {span}", color=VRED_COLOR)
    if not missed:
        embed.description = "No absences in this period. ✅"
        return embed, []
    lines: dict[str, int] = {}          # a double lesson becomes one line "×2"
    for l in missed:
        line = (f"`{fmt_short(l['DayAt'])}` **{(l.get('Subject') or {}).get('Name', '?').strip()}** — "
                f"{(l.get('Topic') or '*no topic*').strip()}")
        lines[line] = lines.get(line, 0) + 1
    embed.description = "\n".join(f"{k} ×{n}" if n > 1 else k for k, n in lines.items())[:4000]
    if ex:
        embed.add_field(name="Upcoming exams in these subjects", inline=False, value="\n".join(
            f"**{fmt_short(exam_date(e))}** {exam_label(e)} — {' '.join((e.get('Content') or '').split())[:120]}"
            for e in ex[:8])[:1024])
    if hw:
        embed.add_field(name="Homework in these subjects", inline=False, value="\n".join(
            f"**{fmt_short(h.get('DeadlineAt') or '')}** {homework_line(h)}" for h in hw[:8])[:1024])
    embed.set_footer(text=f"{len(missed)} missed lessons • Vred")
    return embed, missed


def missed_view(since: str, until: str, explain: bool = True) -> discord.ui.View | None:
    """explain=False: a 'What did I miss?' button (absence DM); True: the AI button."""
    view = discord.ui.View(timeout=None)
    if explain:
        if not ai.enabled():
            return None
        view.add_item(MissedExplainButton(since, until))
    else:
        view.add_item(MissedButton(since, until))
    return view


class MissedButton(discord.ui.DynamicItem[discord.ui.Button],
                   template=r"vred:missed:(?P<a>\d{8}):(?P<b>\d{8})"):
    def __init__(self, since: str, until: str):
        super().__init__(discord.ui.Button(label="What did I miss?", emoji="🧾", style=discord.ButtonStyle.secondary,
                                           custom_id=f"vred:missed:{since.replace('-', '')}:{until.replace('-', '')}"))
        self.since, self.until = since, until

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        d = lambda s: f"{s[:4]}-{s[4:6]}-{s[6:]}"
        return cls(d(match["a"]), d(match["b"]))

    async def callback(self, interaction: discord.Interaction):
        if not await owner_only(interaction, "missed lessons"):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            embed, missed = await missed_report(self.since, self.until)
            view = missed_view(self.since, self.until) if missed else None
            await interaction.followup.send(embed=embed, ephemeral=True, **({"view": view} if view else {}))
        except Exception as e:
            await interaction.followup.send(fail(e), ephemeral=True)


class MissedExplainButton(discord.ui.DynamicItem[discord.ui.Button],
                          template=r"vred:missedai:(?P<a>\d{8}):(?P<b>\d{8})"):
    def __init__(self, since: str, until: str):
        super().__init__(discord.ui.Button(label="Explain the topics (AI)", emoji="🧠",
                                           style=discord.ButtonStyle.primary,
                                           custom_id=f"vred:missedai:{since.replace('-', '')}:{until.replace('-', '')}"))
        self.since, self.until = since, until

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        d = lambda s: f"{s[:4]}-{s[4:6]}-{s[6:]}"
        return cls(d(match["a"]), d(match["b"]))

    async def callback(self, interaction: discord.Interaction):
        if not await owner_only(interaction, "missed lessons") or not await ai_ready(interaction):
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            lo = CET.localize(datetime.strptime(self.since, "%Y-%m-%d"))
            hi = CET.localize(datetime.strptime(self.until, "%Y-%m-%d"))
            lessons = await asyncio.to_thread(get_client().get_attendance, lo, hi)
            topics, seen = [], set()
            for l in logic.missed_lessons(lessons, self.since, self.until):
                t = (l.get("Topic") or "").strip()
                if t and not logic.NOISE_TOPIC.search(t) and t.lower() not in seen:
                    seen.add(t.lower())
                    topics.append(f"- {(l.get('Subject') or {}).get('Name', '?').strip()} "
                                  f"({l['DayAt'][8:10]}.{l['DayAt'][5:7]}): {t}")
            if not topics:
                await interaction.followup.send("The missed lessons have no topics to explain.", ephemeral=True)
                return
            prompt = ("A student missed these lessons. For each topic give 3-5 bullets with the key facts, "
                      "rules or definitions and one short example, so they can catch up. "
                      "Keep it under 3000 characters.\n\nTopics:\n" + "\n".join(topics[:8]))
            text, sources = await asyncio.to_thread(ai.ask, prompt, 2000)
            await interaction.followup.send(embed=ai_embed("🧠 Catch-up on missed topics", text, sources),
                                            ephemeral=True)
        except Exception as e:
            await interaction.followup.send(fail(e), ephemeral=True)


bot.add_dynamic_items(RevisionButton, QuizStartButton, QuizAnswerButton, QuizRetryButton,
                      MissedButton, MissedExplainButton)


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

HELP = [
    ("/today",      "Today's timetable"),
    ("/tomorrow",   "Tomorrow's timetable"),
    ("/day",        "Timetable N days from today (2 = the day after tomorrow, -1 = yesterday)"),
    ("/week",       "Whole week (previous / current / next)"),
    ("/exams",      "Upcoming exams"),
    ("/next",       "Time until the next exam"),
    ("/revise",     "AI revision for the next exam (optionally a subject), scoped by the lesson topics"),
    ("/quiz",       "Multiple-choice quiz for the next exam; mistakes come back before the exam"),
    ("/ask",        "Question for the AI with web search, answer with sources"),
    ("/homework",   "Homework for the coming days"),
    ("/topics",     "Lesson topics of a day (0 = today, -1 = yesterday)"),
    ("/find",       "Search every lesson topic of the year, e.g. `flexbox` — when and in which subject"),
    ("/missed",     "Lessons you missed: topics, upcoming exams and homework, AI catch-up (owner, private)"),
    ("/grades",     "Weighted averages; `target:4.75` says which grades to fix (owner, private)"),
    ("/attendance", "Attendance this term (owner, private)"),
    ("/messages",   "Latest register messages — needs eduVULCAN Premium (owner, private)"),
    ("/setup",      "Create the timetable and exams channels"),
    ("/info",       "Bot status (owner)"),
    ("/sync",       "Force command sync (owner)"),
    ("/shutdown",   "Stop the bot (owner)"),
]


@bot.tree.command(name="help", description="All Vred commands")
async def slash_help(interaction: discord.Interaction):
    embed = discord.Embed(title="Vred — eduVulcan bot",
                          description="Timetable, exams, grades and AI revision from eduVulcan.",
                          color=VRED_COLOR)
    for name, text in HELP:
        embed.add_field(name=name, value=text, inline=False)
    embed.set_footer(text=f"Checks every {CHECK_INTERVAL} min")
    await interaction.response.send_message(embed=embed)


async def day_plan(interaction: discord.Interaction, offset: int, table: bool = False):
    await interaction.response.defer()
    try:
        target   = datetime.now(CET) + timedelta(days=offset)
        date_str = target.strftime("%Y-%m-%d")
        lessons  = await asyncio.to_thread(get_client().get_lessons, target, target)
        day      = [l for l in lessons if lesson_date(l) == date_str]
        if not table:
            await interaction.followup.send(embed=schedule_embed(day, date_str))
            return
        embed = build_schedule_table(day, date_str)
        # Called in the timetable channel: update the pinned message there instead.
        if interaction.channel and interaction.channel.name == SCHEDULE_CHANNEL:
            await post_or_edit_schedule(interaction.channel, embed)
            await interaction.followup.send("✅ Timetable updated.", ephemeral=True)
        else:
            await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(fail(e))


@bot.tree.command(name="today", description="Today's timetable")
async def slash_today(interaction: discord.Interaction):
    await day_plan(interaction, 0, table=True)


@bot.tree.command(name="tomorrow", description="Tomorrow's timetable")
async def slash_tomorrow(interaction: discord.Interaction):
    await day_plan(interaction, 1)


@bot.tree.command(name="day", description="Timetable N days from today (2 = the day after tomorrow, -1 = yesterday)")
async def slash_day(interaction: discord.Interaction, offset: int):
    await day_plan(interaction, offset)


@bot.tree.command(name="week", description="Timetable for a whole week")
@discord.app_commands.describe(which="Which week to show")
@discord.app_commands.choices(which=[
    discord.app_commands.Choice(name="Previous", value="previous"),
    discord.app_commands.Choice(name="Current", value="current"),
    discord.app_commands.Choice(name="Next", value="next"),
])
async def slash_week(interaction: discord.Interaction, which: str = "current"):
    await interaction.response.defer()
    try:
        week_offset = {"previous": -1, "current": 0, "next": 1}.get(which, 0)
        today  = datetime.now(CET)
        monday = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
        lessons = await asyncio.to_thread(get_client().get_lessons, monday, monday + timedelta(days=6))
        await interaction.followup.send(embed=week_embed(lessons, monday, which))
    except Exception as e:
        await interaction.followup.send(fail(e))


@bot.tree.command(name="exams", description="Upcoming exams (2 weeks by default)")
async def slash_exams(interaction: discord.Interaction, weeks: int = 2):
    await interaction.response.defer()
    try:
        now   = datetime.now(CET)
        exams = await asyncio.to_thread(get_client().get_exams, now, now + timedelta(weeks=weeks))
        exams = sorted(exams, key=lambda e: exam_date(e) or "9999")
        if not exams:
            await interaction.followup.send("✅ No exams in this period.")
            return
        header = f"**📝 Exams — next {weeks} week{'s' if weeks != 1 else ''}:**"
        busy = logic.busy_days(exams)
        if busy:
            header += "".join(f"\n⚠️ **{fmt_date(d)}** — {len(es)} at once: "
                              + ", ".join(exam_label(e) for e in es)
                              for d, es in busy.items())
        await interaction.followup.send(header)
        for exam in exams:
            await interaction.followup.send(embed=exam_embed(exam, exams))
    except Exception as e:
        await interaction.followup.send(fail(e))


@bot.tree.command(name="next", description="Time until the next exam")
async def slash_next(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        now  = datetime.now(CET)
        exam = await next_exam()
        if not exam:
            await interaction.followup.send("✅ No upcoming exams.")
            return
        deadline = exam_date(exam)
        try:
            days = days_until(deadline, now)
            time_str = {0: "**today**", 1: "**tomorrow**"}.get(days, f"in **{days} days**")
        except Exception:
            time_str = ""
        embed = discord.Embed(title="⏰ Next exam",
                              description=f"**{exam_subject(exam)}** — {fmt_date(deadline)}\n{time_str}",
                              color=subject_color(exam_subject(exam)))
        embed.set_footer(text=FOOTER)
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(fail(e))


@bot.tree.command(name="revise", description="AI revision for an exam (AI + web search)")
@discord.app_commands.describe(exam="Pick an exam, or type a subject; empty = the next exam")
@discord.app_commands.autocomplete(exam=exam_autocomplete)
async def slash_revise(interaction: discord.Interaction, exam: str = ""):
    if not await ai_ready(interaction):
        return
    await interaction.response.defer()
    try:
        picked = await next_exam(exam)
        if not picked:
            await interaction.followup.send(f"No upcoming exams{f' in “{exam}”' if exam else ''}.")
            return
        await send_revision(interaction.followup.send, picked)
    except Exception as e:
        await interaction.followup.send(fail(e))


@bot.tree.command(name="quiz", description="Multiple-choice quiz for an exam")
@discord.app_commands.describe(exam="Pick an exam, or type a subject; empty = the next exam")
@discord.app_commands.autocomplete(exam=exam_autocomplete)
async def slash_quiz(interaction: discord.Interaction, exam: str = ""):
    if not await ai_ready(interaction):
        return
    await interaction.response.defer()
    try:
        picked = await next_exam(exam)
        if not picked:
            await interaction.followup.send(f"No upcoming exams{f' in “{exam}”' if exam else ''}.")
            return
        qid, qz = await build_quiz(picked)
        await interaction.followup.send(embed=quiz_question_embed(qz), view=quiz_view(qid, qz))
    except Exception as e:
        await interaction.followup.send(fail(e))


@bot.tree.command(name="ask", description="Ask the AI with web search (like an AI overview)")
async def slash_ask(interaction: discord.Interaction, question: str):
    if not await ai_ready(interaction):
        return
    await interaction.response.defer()
    try:
        text, sources = await asyncio.to_thread(ai.ask, question, 1000)
        await interaction.followup.send(embed=ai_embed(f"🔎 {question}", text, sources))
    except Exception as e:
        await interaction.followup.send(fail(e))


@bot.tree.command(name="homework", description="Homework for the coming days (14 by default)")
async def slash_homework(interaction: discord.Interaction, days: int = 14):
    await interaction.response.defer()
    try:
        now   = datetime.now(CET)
        items = await asyncio.to_thread(get_client().get_homework, now, now + timedelta(days=max(1, min(days, 60))))
        items = sorted(items, key=lambda h: h.get("DeadlineAt") or "")
        if not items:
            await interaction.followup.send(f"No homework in the next {days} days. 🎉")
            return
        embed = discord.Embed(title=f"📚 Homework — {days} days", color=VRED_COLOR)
        for h in items[:25]:
            embed.add_field(name=fmt_date((h.get("DeadlineAt") or "")[:10]),
                            value=homework_line(h)[:1024], inline=False)
        embed.set_footer(text=FOOTER)
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(fail(e))


@bot.tree.command(name="topics", description="Lesson topics of a day (0 = today, -1 = yesterday)")
async def slash_topics(interaction: discord.Interaction, offset: int = 0):
    await interaction.response.defer()
    try:
        day     = datetime.now(CET) + timedelta(days=offset)
        lessons = await asyncio.to_thread(get_client().get_attendance, day, day)
        lessons = sorted(lessons, key=lambda l: (l.get("TimeSlot") or {}).get("Position", 99))
        d_str   = day.strftime("%Y-%m-%d")
        if not lessons:
            await interaction.followup.send(f"No lessons entered for {fmt_date(d_str)}.")
            return
        lines = [f"`{(l.get('TimeSlot') or {}).get('Position', '?')}.` **{(l.get('Subject') or {}).get('Name', '?')}** — "
                 f"{l.get('Topic') or '*no topic*'}" for l in lessons]
        embed = discord.Embed(title=f"🧾 Topics — {fmt_date(d_str)}", description="\n".join(lines)[:4000],
                              color=VRED_COLOR)
        embed.set_footer(text=FOOTER)
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(fail(e))


@bot.tree.command(name="find", description="Search every lesson topic of the year")
@discord.app_commands.describe(query="Words to find in topics, e.g. flexbox", subject="Only subjects containing this")
async def slash_find(interaction: discord.Interaction, query: str, subject: str = ""):
    await interaction.response.defer()
    try:
        st = topics_load()
        if not st["lessons"]:
            await interaction.followup.send("The topic archive is still being built — try in a minute.")
            return
        hits = logic.find_topics(st["lessons"], query, subject)
        title = f"🔍 “{query}”" + (f" in {subject}" if subject else "") + f" — {len(hits)} lesson{'s' if len(hits) != 1 else ''}"
        embed = discord.Embed(title=title[:256], color=VRED_COLOR)
        lines = [f"`{fmt_short(d)}` **{subj}** — {topic}" for d, subj, _, topic in hits[:30]]
        embed.description = "\n".join(lines)[:4000] if lines else "No topic matches."
        if hits:
            first = min(h[0] for h in hits)
            embed.set_footer(text=f"First on {fmt_date(first)} • {len(st['lessons'])} topics archived • Vred")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(fail(e))


@bot.tree.command(name="missed",description="Lessons you missed, with topics and what is coming up (owner, private)")
@discord.app_commands.describe(days="How many days back (14 by default)")
async def slash_missed(interaction: discord.Interaction, days: discord.app_commands.Range[int, 1, 120] = 14):
    if not await owner_only(interaction, "missed lessons"):
        return
    await interaction.response.defer(ephemeral=True)
    try:
        now = datetime.now(CET)
        since, until = (now - timedelta(days=days)).strftime("%Y-%m-%d"), today_str(now)
        embed, missed = await missed_report(since, until)
        view = missed_view(since, until) if missed else None
        await interaction.followup.send(embed=embed, ephemeral=True, **({"view": view} if view else {}))
    except Exception as e:
        await interaction.followup.send(fail(e), ephemeral=True)


@bot.tree.command(name="attendance", description="Attendance this term (owner only, only you see it)")
async def slash_attendance(interaction: discord.Interaction):
    if not await owner_only(interaction, "attendance"):
        return
    await interaction.response.defer(ephemeral=True)
    try:
        lessons = await asyncio.to_thread(get_client().get_attendance, current_period_start(), datetime.now(CET))
        stats   = logic.attendance_stats(lessons)
        if "" not in stats:
            await interaction.followup.send("No attendance data this term.", ephemeral=True)
            return
        pct = lambda p, n: f"{100 * p / n:.1f}%"
        p, n = stats.pop("")
        rows = sorted(stats.items(), key=lambda kv: kv[1][0] / kv[1][1])
        embed = discord.Embed(title=f"🚸 Attendance: {pct(p, n)} ({p}/{n})", color=VRED_COLOR,
                              description="\n".join(f"{'⚠️ ' if sp / sn < 0.5 else ''}**{s}** — {pct(sp, sn)} ({sp}/{sn})"
                                                    for s, (sp, sn) in rows)[:4000])
        issues = [l for l in lessons if logic.presence_issue(l)]
        if issues:
            embed.add_field(name=f"Absences and late arrivals ({len(issues)})", inline=False, value="\n".join(
                f"{fmt_date(l.get('DayAt') or '')} — {(l.get('Subject') or {}).get('Name', '?')}: {presence_label(l)}"
                for l in sorted(issues, key=lambda l: l.get("DayAt") or "", reverse=True)[:15])[:1024])
        embed.set_footer(text="Vred • counted: present / (present + absent)")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(fail(e), ephemeral=True)


@bot.tree.command(name="messages", description="Latest register messages (owner only, only you see it)")
async def slash_messages(interaction: discord.Interaction, count: int = 5):
    if not await owner_only(interaction, "messages"):
        return
    await interaction.response.defer(ephemeral=True)
    try:
        messages = await asyncio.to_thread(get_client().get_messages)
        messages = sorted((m for m in messages if not m.get("Withdrawn")),
                          key=lambda m: m.get("SentAt") or "", reverse=True)[:max(1, min(count, 10))]
        if not messages:
            await interaction.followup.send("The inbox is empty.", ephemeral=True)
            return
        await interaction.followup.send(embeds=[message_embed(m, 5000 // len(messages) - 300) for m in messages],
                                        ephemeral=True)
    except Exception as e:
        if PREMIUM_ONLY in str(e):
            await interaction.followup.send("Messages need eduVULCAN Premium since November 2026 — "
                                            "the free account no longer gets them.", ephemeral=True)
            return
        await interaction.followup.send(fail(e), ephemeral=True)


def raised_label(g: dict) -> str:
    """'2' -> '2→3', '4+' -> '4+→5+' (one grade up)."""
    content = (g.get("Content") or "?").strip()
    v = int(g.get("Value") or 0)
    return f"{content}→{v + 1}{content[-1] if content.endswith(('+', '-')) else ''}"


def goal_text(plan: dict, target: float) -> str:
    if plan["current"] is None:
        return "No numeric grades."
    head = f"Now **{plan['current']:.2f}** from {len(plan['finals'])} predicted final grades."
    if not plan["reachable"]:
        return f"{head}\n❌ {target:g} is out of reach without fixing grades to a 6 — at most **{plan['best']:.2f}**."
    if not plan["steps"]:
        return f"{head}\n✅ Target {target:g} already reached."
    fixes = sum(len(gs) for _, gs in plan["steps"].values())
    lines = [f"{head}\nTo reach **{target:g}**: raise **{fixes}** grade{'s' if fixes != 1 else ''} by one:"]
    for s, (new_final, gs) in sorted(plan["steps"].items(), key=lambda x: len(x[1][1])):
        lines.append(f"• {s} {plan['finals'][s]}→{new_final}: `{' '.join(raised_label(g) for g in gs)}`")
    return "\n".join(lines)


@bot.tree.command(name="grades", description="Weighted averages this term (owner only, only you see it)")
@discord.app_commands.describe(target="Target mean of final grades, e.g. 4.75 — says which grades to fix")
async def slash_grades(interaction: discord.Interaction,
                       target: discord.app_commands.Range[float, 1.0, 6.0] | None = None):
    if not await owner_only(interaction, "grades"):
        return
    await interaction.response.defer(ephemeral=True)
    try:
        client  = get_client()
        grades  = await asyncio.to_thread(client.get_grades)
        summary = await asyncio.to_thread(client.get_grades_summary)
        if not grades:
            await interaction.followup.send("No grades this term.", ephemeral=True)
            return
        by_subj = by_subject(grades)
        position = {logic.grade_subject(g): ((g.get("Column") or {}).get("Subject") or {}).get("Position", 999)
                    for g in grades}
        entries = {(x.get("Subject") or {}).get("Name"): x for x in summary}
        plan    = logic.overall_plan(by_subj, target if target is not None else 0)
        edges   = logic.grade_edges(by_subj)

        lines = []
        for s in sorted(by_subj, key=lambda s: (position[s], s)):
            gs      = sorted(by_subj[s], key=lambda g: g.get("CreatedAt") or "")
            marks   = " ".join(g.get("Content") or "?" for g in gs)
            e       = entries.get(s) or {}
            extra   = "".join(f" • {label} **{e[k]}**" for k, label in
                              (("Entry_1", "prop."), ("Entry_2", "final")) if e.get(k))
            final   = f" ({plan['finals'][s]})" if s in plan["finals"] else ""
            edge    = {"drop": " 📉", "rise": " 📈"}.get(edges.get(s, ":").split(":")[0], "")
            lines.append(f"**{fmt_avg(logic.weighted_avg(gs))}**{final}{edge} {s} — `{marks}`{extra}")

        current = f" • finals ~{plan['current']:.2f}" if plan["current"] is not None else ""
        embed = discord.Embed(title=f"📊 Averages — overall {fmt_avg(logic.weighted_avg(grades))}{current}",
                              description="\n".join(lines)[:4096], color=VRED_COLOR)
        if target is not None:
            embed.add_field(name=f"🎯 Target {target:g}", value=goal_text(plan, target)[:1024], inline=False)
        embed.set_footer(text=f"(x) = predicted final, rounds up from x.75 • 📉📈 = within {logic.EDGE} of a "
                              f"threshold • + = +{logic.PLUS_MOD}, − = {logic.MINUS_MOD} • {len(grades)} grades • Vred")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(fail(e), ephemeral=True)


@bot.tree.command(name="info", description="Bot status (owner only)")
async def slash_info(interaction: discord.Interaction):
    if not await owner_only(interaction, "the status"):
        return
    embed = discord.Embed(title="Vred — Status", color=VRED_COLOR)
    embed.add_field(name="Check interval", value=f"{CHECK_INTERVAL} min", inline=True)
    embed.add_field(name="Seen exams",     value=str(len(load_seen_exams())), inline=True)
    embed.add_field(name="Guilds",         value=str(len(bot.guilds)), inline=True)
    embed.add_field(name="Messages",       value="polling" if check_messages.is_running() else "off (Premium)",
                    inline=True)
    embed.add_field(name="AI",             value=f"{ai.MODEL}, answers in {ai.LANGUAGE}" if ai.enabled() else "off",
                    inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="setup", description="Create the timetable and exams channels")
async def slash_setup(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("Server-only command.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("You need the `Manage Channels` permission.", ephemeral=True)
        return
    if not guild.me.guild_permissions.manage_channels:
        await interaction.response.send_message("Vred needs the `Manage Channels` permission.", ephemeral=True)
        return

    await interaction.response.defer()
    created, existing = [], []
    for ch_name, topic in CHANNEL_TOPICS.items():
        if discord.utils.get(guild.text_channels, name=ch_name):
            existing.append(ch_name)
        else:
            ch = await guild.create_text_channel(name=ch_name, topic=topic)
            created.append(ch.mention)
            welcome = discord.Embed(title="Vred is here 👋", description="This channel is managed by Vred.",
                                    color=VRED_COLOR)
            welcome.add_field(name="Commands", value="`/help` — all commands", inline=False)
            await ch.send(embed=welcome)

    embed = discord.Embed(title="Vred setup", color=VRED_COLOR)
    if created:
        embed.add_field(name="✅ Created", value="\n".join(created), inline=False)
    if existing:
        embed.add_field(name="ℹ️ Already there", value="\n".join(f"`{c}`" for c in existing), inline=False)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="sync", description="Force sync slash commands (owner only)")
async def slash_sync(interaction: discord.Interaction):
    if not await owner_only(interaction, "this"):
        return
    await interaction.response.defer(ephemeral=True)
    try:
        synced = await bot.tree.sync()
        if interaction.guild:
            guild_synced = await bot.tree.sync(guild=interaction.guild)
            await interaction.followup.send(f"✅ Synced {len(synced)} global commands\n"
                                            f"✅ Synced {len(guild_synced)} commands to this server", ephemeral=True)
        else:
            await interaction.followup.send(f"✅ Synced {len(synced)} global commands", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Sync failed: {e}", ephemeral=True)


@bot.tree.command(name="shutdown", description="Stop the bot (owner only)")
async def slash_shutdown(interaction: discord.Interaction):
    if not await owner_only(interaction, "this"):
        return
    await interaction.response.send_message("Shutting down…")
    await bot.close()


# ---------------------------------------------------------------------------
# Rotating status
# ---------------------------------------------------------------------------

def days_until(date_str: str, now: datetime) -> int:
    # Calendar-day difference, not (midnight - now).days — that gave -1 for today.
    return (datetime.strptime(date_str, "%Y-%m-%d").date() - now.date()).days


def days_until_label(date_str: str, now: datetime) -> str:
    days = days_until(date_str, now)
    return {0: "today", 1: "tomorrow"}.get(days, f"in {days}d")


status_index = 0


@tasks.loop(minutes=5)
async def rotate_status():
    global status_index
    try:
        now    = datetime.now(CET)
        client = get_client()
        slots  = ["Timetable | /help"]

        lucky = await asyncio.to_thread(client.get_lucky_number)
        if lucky:
            slots.append(f"🍀 Lucky number: {lucky}")

        lessons = await asyncio.to_thread(client.get_lessons, now, now)
        today   = [l for l in lessons if lesson_date(l) == today_str(now)]
        if today:
            slots.append(f"📅 {len(today)} lessons today")

        exams = await asyncio.to_thread(client.get_exams, now, now + timedelta(weeks=8))
        exams = sorted(exams, key=lambda e: exam_date(e) or "9999")
        if exams:
            try:
                slots.append(f"📝 {exam_subject(exams[0])} {days_until_label(exam_date(exams[0]), now)}")
            except Exception:
                slots.append(f"📝 {exam_subject(exams[0])}")

        status = slots[status_index % len(slots)]
        status_index += 1
        await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name=status))
    except Exception as e:
        print(f"[rotate_status] {e}")


@rotate_status.before_loop
async def before_rotate():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Uptime Kuma heartbeat
# ---------------------------------------------------------------------------

@tasks.loop(minutes=1)
async def uptime_ping():
    if not UPTIME_KUMA_URL:
        return
    try:
        req.get(UPTIME_KUMA_URL, timeout=5)
    except Exception as e:
        print(f"[uptime_ping] {e}")


@uptime_ping.before_loop
async def before_uptime():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

async def rename_legacy_channels(guild: discord.Guild):
    for new, old in LEGACY_CHANNELS.items():
        if new == old or discord.utils.get(guild.text_channels, name=new):
            continue
        ch = discord.utils.get(guild.text_channels, name=old)
        if ch is None:
            continue
        try:
            await ch.edit(name=new, topic=CHANNEL_TOPICS[new], reason="Vred switched to English")
            print(f"Renamed #{old} -> #{new} in {guild.name}")
        except discord.HTTPException as e:
            print(f"Could not rename #{old} in {guild.name}: {e}")


@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user}")
    print(f"Connected to {len(bot.guilds)} guilds")
    print(f"Commands registered: {[cmd.name for cmd in bot.tree.get_commands()]}")

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands globally")
        for guild in bot.guilds:
            await bot.tree.sync(guild=guild)
            print(f"Synced to guild: {guild.name}")
        print(f"Command names: {[cmd.name for cmd in synced]}")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    for guild in bot.guilds:
        await rename_legacy_channels(guild)
        channel_names = [c.name for c in guild.text_channels]
        missing = [ch for ch in (SCHEDULE_CHANNEL, EXAMS_CHANNEL) if ch not in channel_names]
        if missing:
            target = guild.system_channel or (guild.text_channels[0] if guild.text_channels else None)
            if target:
                embed = discord.Embed(title="Vred setup required",
                                      description="Vred needs two channels to work properly.", color=0xFF6B6B)
                embed.add_field(name="Option 1: auto-create", value="Use `/setup` and Vred creates them.", inline=False)
                embed.add_field(name="Option 2: manual",
                                value=f"Create channels named `{SCHEDULE_CHANNEL}` and `{EXAMS_CHANNEL}`.", inline=False)
                embed.add_field(name="Missing", value="\n".join(f"`{ch}`" for ch in missing), inline=False)
                try:
                    await target.send(embed=embed)
                except Exception:
                    pass
            print(f"WARNING: Missing channels in {guild.name}: {missing}")

    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching,
                                                        name="Timetable | /help"))

    # on_ready fires again after every full reconnect — a second .start() would raise.
    if daily_schedule.is_running():
        return
    for loop in (daily_schedule, check_exams, rotate_status, uptime_ping, calendar_sync_task,
                 evening_reminder, morning_alert, check_grades, check_messages, check_school,
                 lucky_check, weekly_digest, archive_topics):
        loop.start()
    asyncio.create_task(run_calendar_sync("startup"))


if __name__ == "__main__":
    bot.run(TOKEN)
