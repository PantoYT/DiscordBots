import discord
from discord.ext import commands, tasks
import asyncio
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
import pytz
import requests as req

from pathlib import Path

from client import VulcanClient
import calendar_sync
import logic

# Stan i sekrety (credentials.json, token Google, seen_*.json) leza w DATA_DIR —
# domyslnie obok skryptu, w kontenerze na wolumenie (VRED_DATA_DIR=/data).
DATA_DIR = Path(os.getenv("VRED_DATA_DIR") or Path(__file__).resolve().parent)
load_dotenv(DATA_DIR / ".env")

TOKEN            = os.getenv("DISCORD_TOKEN")
OWNER_ID         = int(os.getenv("OWNER_ID"))
SCHEDULE_CHANNEL = os.getenv("SCHEDULE_CHANNEL", "plan-lekcji")
EXAMS_CHANNEL    = os.getenv("EXAMS_CHANNEL", "sprawdziany")
CHECK_INTERVAL   = int(os.getenv("CHECK_INTERVAL", 60))

CET               = pytz.timezone("Europe/Warsaw")
SEEN_EXAMS_FILE   = DATA_DIR / "seen_exams.json"
SCHEDULE_MSG_FILE = DATA_DIR / "schedule_message.json"
SEEN_GRADES_FILE  = DATA_DIR / "seen_grades.json"
REMINDER_FILE     = DATA_DIR / "reminder_state.json"
CREDENTIALS_FILE  = DATA_DIR / "credentials.json"
DAILY_HOUR        = int(os.getenv("DAILY_HOUR", 7))
REMINDER_HOUR     = int(os.getenv("REMINDER_HOUR", 19))
CALENDAR_SYNC_HOUR = int(os.getenv("CALENDAR_SYNC_HOUR", 20))
UPTIME_KUMA_URL   = os.getenv("UPTIME_KUMA_URL", "")
last_schedule_run: str | None = None
last_calendar_sync: str | None = None

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_seen() -> set:
    try:
        with open(SEEN_EXAMS_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    except (FileNotFoundError, json.JSONDecodeError):
        return set()


def save_json(path: Path, data):
    """Zapis atomowy — padniecie w polowie nie zostawi pustego pliku stanu."""
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


def save_seen(seen: set):
    save_json(SEEN_EXAMS_FILE, list(seen))


def get_client() -> VulcanClient:
    return VulcanClient(str(CREDENTIALS_FILE))


def load_schedule_msg() -> dict:
    try:
        with open(SCHEDULE_MSG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_schedule_msg(data: dict):
    save_json(SCHEDULE_MSG_FILE, data)


def build_schedule_table(lessons: list, date_str: str) -> discord.Embed:
    date_fmt = fmt_date(date_str)
    embed = discord.Embed(title=f"📅 Plan lekcji — {date_fmt}", color=VRED_COLOR)

    if not lessons:
        embed.description = "```\nBrak lekcji tego dnia.\n```"
        embed.set_footer(text="Vred • eduVulcan bot")
        return embed

    views = sorted((logic.lesson_view(l) for l in lessons), key=lambda v: v["pos"])

    # Build monospace table
    rows = []
    changes = []
    for v in views:
        flag = {"cancelled": " x", "subst": " !"}.get(v["kind"], "  ")
        rows.append((str(v["pos"]), v["time"], v["subject"][:24], v["room"] or "  -  ", flag))
        if v["kind"] != "normal":
            changes.append(f"`{v['pos']}.` **{v['subject']}** {logic.change_text(v)}")

    # Column widths
    w_pos  = max(len(r[0]) for r in rows)
    w_time = max(len(r[1]) for r in rows)
    w_subj = max(len(r[2]) for r in rows)
    w_room = max(len(r[3]) for r in rows)

    header = f"{'Nr':<{w_pos}}  {'Godziny':<{w_time}}  {'Przedmiot':<{w_subj}}  {'Sala':<{w_room}}"
    sep    = "─" * len(header)
    lines  = [header, sep]
    for pos, time, subj, room, flag in rows:
        lines.append(f"{pos:<{w_pos}}  {time:<{w_time}}  {subj:<{w_subj}}  {room:<{w_room}}{flag}")

    embed.description = f"```\n{chr(10).join(lines)}\n```"
    if changes:
        embed.add_field(name="Zmiany", value="\n".join(changes)[:1024], inline=False)
        embed.set_footer(text="! = zastępstwo  •  x = odwołane  •  Vred • eduVulcan bot")
    else:
        embed.set_footer(text="Vred • eduVulcan bot")
    return embed


async def post_or_edit_schedule(channel: discord.TextChannel, embed: discord.Embed):
    """Edytuje istniejącą wiadomość lub wysyła nową — jedna wiadomość na kanał."""
    data    = load_schedule_msg()
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
    save_schedule_msg(data)


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


WEEKDAYS_PL = ["Poniedziałek", "Wtorek", "Środa", "Czwartek", "Piątek", "Sobota", "Niedziela"]

def fmt_date(date_str: str) -> str:
    try:
        d = datetime.strptime(date_str, "%Y-%m-%d")
        return f"{d.strftime('%d.%m.%Y')} ({WEEKDAYS_PL[d.weekday()]})"
    except Exception:
        return date_str


def exam_label(exam: dict) -> str:
    return f"{exam.get('Subject', {}).get('Name', '?')} ({(exam.get('Type') or 'sprawdzian').lower()})"


def exam_embed(exam: dict, all_exams: list | None = None) -> discord.Embed:
    """all_exams — jesli podane, dokleja ostrzezenie o innych sprawdzianach tego dnia."""
    subject = exam.get("Subject", {}).get("Name", "?")
    embed = discord.Embed(
        title=f"📝 {subject}",
        description=exam.get("Content") or "Brak opisu",
        color=subject_color(subject),
    )
    embed.add_field(name="Data",       value=fmt_date(exam_date(exam) or "?"), inline=True)
    embed.add_field(name="Typ",        value=exam.get("Type") or "Sprawdzian",    inline=True)
    creator = exam.get("Creator", {})
    if creator:
        embed.add_field(name="Nauczyciel", value=creator.get("DisplayName", "?"), inline=True)
    if all_exams:
        others = [e for e in all_exams
                  if exam_date(e) == exam_date(exam) and e.get("Id") != exam.get("Id")]
        if others:
            embed.add_field(name=f"⚠️ Tego dnia też ({len(others)})",
                            value="\n".join(exam_label(e) for e in others), inline=False)
    embed.set_footer(text="Vred • eduVulcan bot")
    return embed


def exam_date(exam: dict) -> str:
    """API przeszła z zagnieżdżonego Deadline.Date na płaskie DeadlineAt — obsłuż oba."""
    return exam.get("DeadlineAt") or (exam.get("Deadline") or {}).get("Date") or ""


def lesson_date(lesson: dict) -> str | None:
    """API przeszła z zagnieżdżonego Date.Date na płaskie DateAt — obsłuż oba."""
    return lesson.get("DateAt") or lesson.get("Date", {}).get("Date")


def lesson_line(lesson: dict) -> str:
    v        = logic.lesson_view(lesson)
    room_str = f" • sala {v['room']}" if v["room"] else ""
    name     = f"~~{v['subject']}~~" if v["kind"] == "cancelled" else v["subject"]
    change   = logic.change_text(v)
    return f"`{v['pos']}.` **{v['time']}** {name}{room_str}{' ' + change if change else ''}"


def lesson_sort_key(lesson: dict) -> int:
    return logic.lesson_view(lesson)["pos"]


def schedule_embed(lessons: list, date_str: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"📅 Plan lekcji — {fmt_date(date_str)}",
        color=VRED_COLOR,
    )
    if not lessons:
        embed.description = "Brak lekcji tego dnia."
        return embed
    sorted_lessons = sorted(lessons, key=lesson_sort_key)
    embed.description = "\n".join(lesson_line(l) for l in sorted_lessons)
    embed.set_footer(text="Vred • eduVulcan bot")
    return embed


WEEK_LABELS = {"poprzedni": "Poprzedni tydzień", "obecny": "Ten tydzień", "nastepny": "Następny tydzień"}


def week_embed(lessons: list, monday: datetime, ktory: str) -> discord.Embed:
    sunday = monday + timedelta(days=6)
    embed = discord.Embed(
        title=f"📅 {WEEK_LABELS.get(ktory, 'Plan tygodnia')} — "
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
        date_str = day.strftime("%Y-%m-%d")
        day_lessons = sorted(by_date.get(date_str, []), key=lesson_sort_key)
        name = f"{WEEKDAYS_PL[offset]} {day.strftime('%d.%m')}"
        value = "\n".join(lesson_line(l) for l in day_lessons) if day_lessons else "Brak lekcji."
        embed.add_field(name=name, value=value[:1024], inline=False)

    embed.set_footer(text="Vred • eduVulcan bot")
    return embed


# ---------------------------------------------------------------------------
# Daily schedule post
# ---------------------------------------------------------------------------

@tasks.loop(minutes=1)
async def daily_schedule():
    global last_schedule_run
    now      = datetime.now(CET)
    today    = now.strftime("%Y-%m-%d")
    if now.hour < DAILY_HOUR:
        return
    if last_schedule_run == today:
        return
    last_schedule_run = today

    channel = discord.utils.get(bot.get_all_channels(), name=SCHEDULE_CHANNEL)
    if not channel:
        return
    try:
        client   = get_client()
        lessons  = await asyncio.to_thread(client.get_lessons, now, now)
        date_str = today
        day      = [l for l in lessons if lesson_date(l) == date_str]
        embed    = build_schedule_table(day, date_str)
        await post_or_edit_schedule(channel, embed)
    except Exception as e:
        print(f"[daily_schedule] {e}")


@daily_schedule.before_loop
async def before_daily():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Synchronizacja Google Calendar (kolorowy plan lekcji)
# ---------------------------------------------------------------------------

async def run_calendar_sync(reason: str):
    """Blokujaca robota sieciowa calendar_sync.sync() w osobnym watku, zeby nie
    zamrazac gateway'a Discorda. Przy wygasnieciu OAuth (Testing = ~7 dni)
    wysyla DM do wlasciciela z instrukcja odnowienia."""
    global last_calendar_sync
    last_calendar_sync = datetime.now(CET).strftime("%Y-%m-%d")
    try:
        result = await asyncio.to_thread(calendar_sync.sync)
        print(f"[calendar_sync:{reason}] {result}")
    except calendar_sync.CalendarAuthError as e:
        print(f"[calendar_sync:{reason}] AUTORYZACJA WYGASLA: {e}")
        try:
            owner = await bot.fetch_user(OWNER_ID)
            await owner.send(
                "📅 Synchronizacja kalendarza Google wygasła.\n"
                "Na PC w folderze Vred: `py -3.12 calendar_auth.py`, potem\n"
                "`scp google_calendar_token.json ubuntu@100.117.148.97:~/vred/data/` "
                "i `docker restart vred` na serwerze.\n"
                "Żeby nie wracało co 7 dni: aplikacja OAuth w Google Cloud → *In production*."
            )
        except Exception as dm_err:
            print(f"[calendar_sync:{reason}] nie udalo sie wyslac DM: {dm_err}")
    except Exception as e:
        print(f"[calendar_sync:{reason}] Blad: {e}")


@tasks.loop(minutes=1)
async def calendar_sync_task():
    now = datetime.now(CET)
    today = now.strftime("%Y-%m-%d")
    if last_calendar_sync == today:
        return
    if now.hour < CALENDAR_SYNC_HOUR:
        return
    await run_calendar_sync("daily")


@calendar_sync_task.before_loop
async def before_calendar_sync():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Background task — nowe sprawdziany
# ---------------------------------------------------------------------------

@tasks.loop(minutes=CHECK_INTERVAL)
async def check_exams():
    await bot.wait_until_ready()
    channel = discord.utils.get(bot.get_all_channels(), name=EXAMS_CHANNEL)
    if not channel:
        return
    try:
        now    = datetime.now(CET)
        client = get_client()
        exams  = await asyncio.to_thread(client.get_exams, now, now + timedelta(weeks=4))
        seen   = load_seen()
        for exam in exams:
            eid = str(exam["Id"])
            if eid not in seen:
                await channel.send(embed=exam_embed(exam, exams))
                seen.add(eid)
        save_seen(seen)
    except Exception as e:
        print(f"[check_exams] Błąd: {e}")


# ---------------------------------------------------------------------------
# Wieczorne przypomnienie — co jutro (sprawdziany + zmiany w planie)
# ---------------------------------------------------------------------------

async def build_reminder(now: datetime) -> discord.Embed | None:
    client   = get_client()
    tomorrow = now + timedelta(days=1)
    t_str    = tomorrow.strftime("%Y-%m-%d")
    exams    = await asyncio.to_thread(client.get_exams, tomorrow, tomorrow + timedelta(days=7))
    lessons  = await asyncio.to_thread(client.get_lessons, tomorrow, tomorrow)

    embed = discord.Embed(title=f"🔔 Jutro — {fmt_date(t_str)}", color=VRED_COLOR)
    t_exams = [e for e in exams if exam_date(e) == t_str]
    if t_exams:
        warn = " ⚠️" if len(t_exams) >= 2 else ""
        embed.add_field(
            name=f"📝 Sprawdziany ({len(t_exams)}){warn}",
            value="\n".join(f"**{exam_label(e)}** — {e.get('Content') or 'brak opisu'}"
                            for e in t_exams)[:1024],
            inline=False,
        )
    changes = []
    for v in sorted((logic.lesson_view(l) for l in lessons if lesson_date(l) == t_str),
                    key=lambda v: v["pos"]):
        if v["kind"] != "normal":
            changes.append(f"`{v['pos']}.` **{v['subject']}** {logic.change_text(v)}")
    if changes:
        embed.add_field(name="🔀 Zmiany w planie", value="\n".join(changes)[:1024], inline=False)

    # W niedziele: podglad calego tygodnia i dni z kilkoma sprawdzianami naraz
    if now.weekday() == 6:
        week = logic.exams_by_day(exams)
        if week:
            lines = []
            for d, es in week.items():
                mark = " ⚠️" if len(es) >= 2 else ""
                lines.append(f"**{fmt_date(d)}**{mark}: " + ", ".join(exam_label(e) for e in es))
            embed.add_field(name="🗓️ Ten tydzień", value="\n".join(lines)[:1024], inline=False)

    if not embed.fields:
        return None
    embed.set_footer(text="Vred • eduVulcan bot")
    return embed


@tasks.loop(minutes=1)
async def evening_reminder():
    now   = datetime.now(CET)
    today = now.strftime("%Y-%m-%d")
    if now.hour < REMINDER_HOUR:
        return
    state = load_json(REMINDER_FILE, {})
    if state.get("last") == today:
        return
    channel = discord.utils.get(bot.get_all_channels(), name=EXAMS_CHANNEL)
    if not channel:
        return
    try:
        embed = await build_reminder(now)
        if embed:
            await channel.send(embed=embed)
        # Zapis dopiero po sukcesie — przy bledzie Vulcana sprobuje za minute.
        save_json(REMINDER_FILE, {"last": today})
    except Exception as e:
        print(f"[evening_reminder] {e}")


@evening_reminder.before_loop
async def before_reminder():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Nowe oceny — DM do wlasciciela (oceny sa prywatne, nie na kanal)
# ---------------------------------------------------------------------------

def fmt_avg(avg: float | None) -> str:
    return f"{avg:.2f}" if avg is not None else "—"


def grade_embed(g: dict, grades: list, fresh_ids: set, modified: bool) -> discord.Embed:
    col     = g.get("Column") or {}
    subject = logic.grade_subject(g)
    same    = [x for x in grades if logic.grade_subject(x) == subject]
    before  = logic.weighted_avg([x for x in same if str(x.get("Id")) not in fresh_ids])
    after   = logic.weighted_avg(same)
    title   = "✏️ Zmieniona ocena" if modified else "🎓 Nowa ocena"
    embed = discord.Embed(
        title=f"{title}: {g.get('Content') or '?'} — {subject}",
        description=col.get("Name") or None,
        color=subject_color(subject),
    )
    embed.add_field(name="Waga", value=f"{col.get('Weight', 0):g}", inline=True)
    embed.add_field(name="Kategoria", value=(col.get("Category") or {}).get("Name") or "—", inline=True)
    if not modified:
        trend = "" if before is None or after is None else (" 📈" if after > before else " 📉" if after < before else "")
        embed.add_field(name="Średnia", value=f"{fmt_avg(before)} → **{fmt_avg(after)}**{trend}", inline=True)
    else:
        embed.add_field(name="Średnia", value=f"**{fmt_avg(after)}**", inline=True)
    if g.get("Comment"):
        embed.add_field(name="Komentarz", value=g["Comment"][:1024], inline=False)
    embed.set_footer(text=f"{(g.get('Creator') or {}).get('DisplayName', '')} • Vred")
    return embed


@tasks.loop(minutes=CHECK_INTERVAL)
async def check_grades():
    try:
        client = get_client()
        grades = await asyncio.to_thread(client.get_grades)
        first_run = not SEEN_GRADES_FILE.exists()
        seen = load_json(SEEN_GRADES_FILE, {})
        new, modified = logic.grade_changes(grades, seen)
        if (new or modified) and not first_run:
            owner = await bot.fetch_user(OWNER_ID)
            fresh_ids = {str(g.get("Id")) for g in new}
            batch = [(g, False) for g in new] + [(g, True) for g in modified]
            for g, is_mod in batch[:10]:
                await owner.send(embed=grade_embed(g, grades, fresh_ids, is_mod))
            if len(batch) > 10:
                await owner.send(f"…i jeszcze {len(batch) - 10} zmian w ocenach — `/srednie`.")
        # Pierwszy przebieg tylko zapamietuje stan, zeby nie zasypac DM-a historia.
        seen.update({str(g.get("Id")): g.get("Content") or "" for g in grades})
        save_json(SEEN_GRADES_FILE, seen)
    except Exception as e:
        print(f"[check_grades] {e}")


@check_grades.before_loop
async def before_grades():
    await bot.wait_until_ready()


# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

@bot.tree.command(name="commands", description="Lista wszystkich komend Vreda")
async def slash_commands(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Vred — eduVulcan Bot",
        description="Automatyczne powiadomienia o sprawdzianach i plan lekcji.",
        color=VRED_COLOR,
    )
    embed.add_field(name="/plan",        value="Plan lekcji na dziś",              inline=False)
    embed.add_field(name="/jutro",       value="Plan lekcji na jutro",             inline=False)
    embed.add_field(name="/dzien",       value="Plan lekcji na wybrany dzień (+N)", inline=False)
    embed.add_field(name="/tydzien",     value="Plan lekcji na cały tydzień (poprzedni/obecny/następny)", inline=False)
    embed.add_field(name="/sprawdziany", value="Nadchodzące sprawdziany",          inline=False)
    embed.add_field(name="/nastepny",    value="Czas do następnego sprawdzianu",   inline=False)
    embed.add_field(name="/srednie",     value="Średnie ważone i oceny (owner only, prywatnie)", inline=False)
    embed.add_field(name="/setup",       value="Utwórz kanały plan-lekcji i sprawdziany", inline=False)
    embed.add_field(name="/info",        value="Status bota (owner only)",         inline=False)
    embed.add_field(name="/sync",        value="Force sync komend (owner only)",   inline=False)
    embed.add_field(name="/shutdown",    value="Wyłącz bota (owner only)",         inline=False)
    embed.set_footer(text=f"Automatyczne sprawdzanie co {CHECK_INTERVAL} min")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="plan", description="Plan lekcji na dziś")
async def slash_plan(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        target   = datetime.now(CET)
        date_str = target.strftime("%Y-%m-%d")
        client   = get_client()
        lessons  = await asyncio.to_thread(client.get_lessons, target, target)
        day      = [l for l in lessons if lesson_date(l) == date_str]
        embed    = build_schedule_table(day, date_str)
        # Aktualizuj wiadomość na kanale plan-lekcji jeśli komenda tam wywołana
        if interaction.channel and interaction.channel.name == SCHEDULE_CHANNEL:
            await post_or_edit_schedule(interaction.channel, embed)
            await interaction.followup.send("✅ Plan zaktualizowany.", ephemeral=True)
        else:
            await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ `{e}`")


@bot.tree.command(name="jutro", description="Plan lekcji na jutro")
async def slash_jutro(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        target   = datetime.now(CET) + timedelta(days=1)
        date_str = target.strftime("%Y-%m-%d")
        client   = get_client()
        lessons  = await asyncio.to_thread(client.get_lessons, target, target)
        day      = [l for l in lessons if lesson_date(l) == date_str]
        await interaction.followup.send(embed=schedule_embed(day, date_str))
    except Exception as e:
        await interaction.followup.send(f"❌ `{e}`")


@bot.tree.command(name="dzien", description="Plan lekcji za N dni od dziś (np. 2 = pojutrze, -1 = wczoraj)")
async def slash_dzien(interaction: discord.Interaction, offset: int):
    await interaction.response.defer()
    try:
        target   = datetime.now(CET) + timedelta(days=offset)
        date_str = target.strftime("%Y-%m-%d")
        client   = get_client()
        lessons  = await asyncio.to_thread(client.get_lessons, target, target)
        day      = [l for l in lessons if lesson_date(l) == date_str]
        await interaction.followup.send(embed=schedule_embed(day, date_str))
    except Exception as e:
        await interaction.followup.send(f"❌ `{e}`")


@bot.tree.command(name="tydzien", description="Plan lekcji na cały tydzień")
@discord.app_commands.describe(ktory="Który tydzień pokazać")
@discord.app_commands.choices(ktory=[
    discord.app_commands.Choice(name="Poprzedni", value="poprzedni"),
    discord.app_commands.Choice(name="Obecny", value="obecny"),
    discord.app_commands.Choice(name="Następny", value="nastepny"),
])
async def slash_tydzien(interaction: discord.Interaction, ktory: str = "obecny"):
    await interaction.response.defer()
    try:
        week_offset = {"poprzedni": -1, "obecny": 0, "nastepny": 1}.get(ktory, 0)
        today  = datetime.now(CET)
        monday = today - timedelta(days=today.weekday()) + timedelta(weeks=week_offset)
        sunday = monday + timedelta(days=6)
        client  = get_client()
        lessons = await asyncio.to_thread(client.get_lessons, monday, sunday)
        await interaction.followup.send(embed=week_embed(lessons, monday, ktory))
    except Exception as e:
        await interaction.followup.send(f"❌ `{e}`")


@bot.tree.command(name="sprawdziany", description="Nadchodzące sprawdziany (domyślnie 2 tygodnie)")
async def slash_sprawdziany(interaction: discord.Interaction, tygodnie: int = 2):
    await interaction.response.defer()
    try:
        now    = datetime.now(CET)
        client = get_client()
        exams  = await asyncio.to_thread(client.get_exams, now, now + timedelta(weeks=tygodnie))
        exams  = sorted(exams, key=lambda e: exam_date(e) or "9999")
        if not exams:
            await interaction.followup.send("✅ Brak sprawdzianów w tym okresie.")
            return
        header = f"**📝 Sprawdziany — najbliższe {tygodnie} tygodnie:**"
        busy = logic.busy_days(exams)
        if busy:
            header += "".join(f"\n⚠️ **{fmt_date(d)}** — {len(es)} naraz: "
                              + ", ".join(exam_label(e) for e in es)
                              for d, es in busy.items())
        await interaction.followup.send(header)
        for exam in exams:
            await interaction.followup.send(embed=exam_embed(exam, exams))
    except Exception as e:
        await interaction.followup.send(f"❌ `{e}`")


@bot.tree.command(name="nastepny", description="Czas do następnego sprawdzianu")
async def slash_nastepny(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        now    = datetime.now(CET)
        client = get_client()
        exams  = await asyncio.to_thread(client.get_exams, now, now + timedelta(weeks=8))
        exams  = sorted(exams, key=lambda e: exam_date(e) or "9999")
        if not exams:
            await interaction.followup.send("✅ Brak nadchodzących sprawdzianów.")
            return
        exam     = exams[0]
        deadline = exam_date(exam)
        subject  = exam.get("Subject", {}).get("Name", "?")
        try:
            days = days_until(deadline, now)
            time_str = {0: "**dziś**", 1: "**jutro**"}.get(days, f"za **{days} dni**")
        except Exception:
            time_str = ""
        embed = discord.Embed(
            title="⏰ Następny sprawdzian",
            description=f"**{subject}** — {fmt_date(deadline)}\n{time_str}",
            color=subject_color(subject),
        )
        embed.set_footer(text="Vred • eduVulcan bot")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ `{e}`")


@bot.tree.command(name="srednie", description="Średnie ważone z bieżącego okresu (tylko właściciel, widzisz tylko ty)")
async def slash_srednie(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Tylko właściciel może zobaczyć oceny.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        client  = get_client()
        grades  = await asyncio.to_thread(client.get_grades)
        summary = await asyncio.to_thread(client.get_grades_summary)
        if not grades:
            await interaction.followup.send("Brak ocen w tym okresie.", ephemeral=True)
            return
        by_subj: dict[str, list] = {}
        position: dict[str, int] = {}
        for g in grades:
            s = logic.grade_subject(g)
            by_subj.setdefault(s, []).append(g)
            position[s] = ((g.get("Column") or {}).get("Subject") or {}).get("Position", 999)
        entries = {(x.get("Subject") or {}).get("Name"): x for x in summary}

        lines = []
        for s in sorted(by_subj, key=lambda s: (position[s], s)):
            gs      = sorted(by_subj[s], key=lambda g: g.get("CreatedAt") or "")
            marks   = " ".join(g.get("Content") or "?" for g in gs)
            e       = entries.get(s) or {}
            extra   = "".join(f" • {label} **{e[k]}**" for k, label in
                              (("Entry_1", "prop."), ("Entry_2", "końc.")) if e.get(k))
            lines.append(f"**{fmt_avg(logic.weighted_avg(gs))}** {s} — `{marks}`{extra}")

        embed = discord.Embed(
            title=f"📊 Średnie — ogólna {fmt_avg(logic.weighted_avg(grades))}",
            description="\n".join(lines)[:4096],
            color=VRED_COLOR,
        )
        embed.set_footer(text=f"+ = +{logic.PLUS_MOD}, − = {logic.MINUS_MOD} • {len(grades)} ocen • Vred")
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ `{e}`", ephemeral=True)


@bot.tree.command(name="info", description="Status bota (owner only)")
async def slash_info(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Tylko właściciel może użyć tej komendy.", ephemeral=True)
        return
    embed = discord.Embed(title="Vred — Status", color=VRED_COLOR)
    embed.add_field(name="Check interval", value=f"{CHECK_INTERVAL} min", inline=True)
    embed.add_field(name="Seen exams",     value=str(len(load_seen())),   inline=True)
    embed.add_field(name="Guilds",         value=str(len(bot.guilds)),     inline=True)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="setup", description="Utwórz kanały plan-lekcji i sprawdziany")
async def slash_setup(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("Komenda tylko na serwerze.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("Potrzebujesz uprawnienia `Manage Channels`.", ephemeral=True)
        return
    if not guild.me.guild_permissions.manage_channels:
        await interaction.response.send_message("Vred potrzebuje uprawnienia `Manage Channels`.", ephemeral=True)
        return

    await interaction.response.defer()
    created = []
    existing = []

    for ch_name, topic in (
        (SCHEDULE_CHANNEL, "Plan lekcji — aktualizowany przez Vreda"),
        (EXAMS_CHANNEL,    "Sprawdziany i klasówki — powiadomienia od Vreda"),
    ):
        if discord.utils.get(guild.text_channels, name=ch_name):
            existing.append(ch_name)
        else:
            ch = await guild.create_text_channel(name=ch_name, topic=topic)
            created.append(ch.mention)
            welcome = discord.Embed(
                title="Vred jest tutaj 👋",
                description="Ten kanał jest zarządzany przez Vreda.",
                color=VRED_COLOR,
            )
            welcome.add_field(name="Komendy", value="`/commands` — lista wszystkich komend", inline=False)
            await ch.send(embed=welcome)

    embed = discord.Embed(title="Vred Setup", color=VRED_COLOR)
    if created:
        embed.add_field(name="✅ Utworzono", value="\n".join(created), inline=False)
    if existing:
        embed.add_field(name="ℹ️ Już istnieją", value="\n".join(f"`{c}`" for c in existing), inline=False)
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="sync", description="Force sync slash commands (owner only)")
async def slash_sync(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("You don't have permission.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        synced = await bot.tree.sync()
        if interaction.guild:
            guild_synced = await bot.tree.sync(guild=interaction.guild)
            await interaction.followup.send(
                f"✅ Synced {len(synced)} global commands\n"
                f"✅ Synced {len(guild_synced)} commands to this server\n"
                f"Commands should appear immediately!",
                ephemeral=True
            )
        else:
            await interaction.followup.send(f"✅ Synced {len(synced)} global commands", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Sync failed: {e}", ephemeral=True)


@bot.tree.command(name="shutdown", description="Wyłącz bota (owner only)")
async def slash_shutdown(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Nie masz uprawnień.", ephemeral=True)
        return
    await interaction.response.send_message("Wyłączam...")
    await bot.close()


# ---------------------------------------------------------------------------
# Rotating status
# ---------------------------------------------------------------------------

def days_until(date_str: str, now: datetime) -> int:
    # Kalendarzowa roznica dni, nie (polnoc - teraz).days — tamto dawalo -1 dla dzisiaj.
    return (datetime.strptime(date_str, "%Y-%m-%d").date() - now.date()).days


def days_until_label(date_str: str, now: datetime) -> str:
    days = days_until(date_str, now)
    return {0: "dziś", 1: "jutro"}.get(days, f"za {days}d")


status_index = 0

@tasks.loop(minutes=5)
async def rotate_status():
    global status_index
    try:
        now    = datetime.now(CET)
        client = get_client()
        slots  = []

        # Slot 1: domyślny
        slots.append("Plan lekcji | /commands")

        # Slot 2: szczęśliwy numerek
        lucky = await asyncio.to_thread(client.get_lucky_number)
        if lucky:
            slots.append(f"🍀 Szczęśliwy numerek: {lucky}")

        # Slot 3: ile lekcji dziś
        date_str = now.strftime("%Y-%m-%d")
        lessons  = await asyncio.to_thread(client.get_lessons, now, now)
        today    = [l for l in lessons if lesson_date(l) == date_str]
        if today:
            slots.append(f"📅 Dziś {len(today)} lekcji")

        # Slot 4: następny sprawdzian
        exams = await asyncio.to_thread(client.get_exams, now, now + timedelta(weeks=8))
        exams = sorted(exams, key=lambda e: exam_date(e) or "9999")
        if exams:
            e    = exams[0]
            subj = e.get("Subject", {}).get("Name", "?")
            date = exam_date(e)
            try:
                slots.append(f"📝 {subj} {days_until_label(date, now)}")
            except Exception:
                slots.append(f"📝 {subj}")

        status = slots[status_index % len(slots)]
        status_index += 1

        await bot.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=status,
        ))
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

@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user}")
    print(f"Connected to {len(bot.guilds)} guilds")
    print(f"Commands registered: {[cmd.name for cmd in bot.tree.get_commands()]}")

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands globally")
        # Also sync to each guild immediately
        for guild in bot.guilds:
            await bot.tree.sync(guild=guild)
            print(f"Synced to guild: {guild.name}")
        print(f"Command names: {[cmd.name for cmd in synced]}")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    # Check for required channels in every guild
    for guild in bot.guilds:
        channel_names = [c.name for c in guild.text_channels]
        missing = [ch for ch in (SCHEDULE_CHANNEL, EXAMS_CHANNEL) if ch not in channel_names]
        if missing:
            target = guild.system_channel or (guild.text_channels[0] if guild.text_channels else None)
            if target:
                embed = discord.Embed(
                    title="Vred Setup Required",
                    description=f"Vred needs two channels to work properly.",
                    color=0xFF6B6B,
                )
                embed.add_field(name="Option 1: Auto-create", value="Use `/setup` and Vred will create the channels for you.", inline=False)
                embed.add_field(name="Option 2: Manual", value=f"Create channels named `{SCHEDULE_CHANNEL}` and `{EXAMS_CHANNEL}` yourself.", inline=False)
                embed.add_field(name="Missing", value="\n".join(f"`{ch}`" for ch in missing), inline=False)
                try:
                    await target.send(embed=embed)
                except Exception:
                    pass
            print(f"WARNING: Missing channels in {guild.name}: {missing}")

    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="Plan lekcji | /commands",
    ))

    # on_ready wraca po kazdym pelnym reconnectcie — drugi .start() rzucilby RuntimeError.
    if daily_schedule.is_running():
        return
    for loop in (daily_schedule, check_exams, rotate_status, uptime_ping,
                 calendar_sync_task, evening_reminder, check_grades):
        loop.start()
    asyncio.create_task(run_calendar_sync("startup"))


# -------------------------------
# Run the bot
# -------------------------------
if __name__ == "__main__":
    bot.run(TOKEN)
