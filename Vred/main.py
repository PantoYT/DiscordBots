import discord
from discord.ext import commands, tasks
import os
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
import pytz

from client import VulcanClient

load_dotenv()

TOKEN            = os.getenv("DISCORD_TOKEN")
OWNER_ID         = int(os.getenv("OWNER_ID"))
SCHEDULE_CHANNEL = os.getenv("SCHEDULE_CHANNEL", "plan-lekcji")
EXAMS_CHANNEL    = os.getenv("EXAMS_CHANNEL", "sprawdziany")
CHECK_INTERVAL   = int(os.getenv("CHECK_INTERVAL", 60))

CET             = pytz.timezone("Europe/Warsaw")
SEEN_EXAMS_FILE = "seen_exams.json"

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


def save_seen(seen: set):
    with open(SEEN_EXAMS_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f)


def get_client() -> VulcanClient:
    return VulcanClient()


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


def exam_embed(exam: dict) -> discord.Embed:
    subject = exam.get("Subject", {}).get("Name", "?")
    embed = discord.Embed(
        title=f"📝 {subject}",
        description=exam.get("Content") or "Brak opisu",
        color=subject_color(subject),
    )
    deadline = exam.get("Deadline", {})
    embed.add_field(name="Data",       value=fmt_date(deadline.get("Date", "?")), inline=True)
    embed.add_field(name="Typ",        value=exam.get("Type") or "Sprawdzian",    inline=True)
    creator = exam.get("Creator", {})
    if creator:
        embed.add_field(name="Nauczyciel", value=creator.get("DisplayName", "?"), inline=True)
    embed.set_footer(text="Vred • eduVulcan bot")
    return embed


def lesson_line(lesson: dict) -> str:
    slot     = lesson.get("TimeSlot", {})
    pos      = slot.get("Position", "?")
    time     = slot.get("Display", "?")
    name     = lesson.get("Subject", {}).get("Name", "?")
    room     = lesson.get("Room")
    room_str = f" • sala {room['Code']}" if room else ""
    change   = lesson.get("Change")
    sub_str  = " ⚠️ zastępstwo" if change else ""
    return f"`{pos}.` **{time}** {name}{room_str}{sub_str}"


def schedule_embed(lessons: list, date_str: str) -> discord.Embed:
    embed = discord.Embed(
        title=f"📅 Plan lekcji — {fmt_date(date_str)}",
        color=VRED_COLOR,
    )
    if not lessons:
        embed.description = "Brak lekcji tego dnia."
        return embed
    sorted_lessons = sorted(lessons, key=lambda l: l.get("TimeSlot", {}).get("Position", 99))
    embed.description = "\n".join(lesson_line(l) for l in sorted_lessons)
    embed.set_footer(text="Vred • eduVulcan bot")
    return embed


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
        exams  = client.get_exams(now, now + timedelta(weeks=4))
        seen   = load_seen()
        for exam in exams:
            eid = str(exam["Id"])
            if eid not in seen:
                await channel.send(embed=exam_embed(exam))
                seen.add(eid)
        save_seen(seen)
    except Exception as e:
        print(f"[check_exams] Błąd: {e}")


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
    embed.add_field(name="/sprawdziany", value="Nadchodzące sprawdziany",          inline=False)
    embed.add_field(name="/nastepny",    value="Czas do następnego sprawdzianu",   inline=False)
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
        lessons  = client.get_lessons(target, target)
        day      = [l for l in lessons if l.get("Date", {}).get("Date") == date_str]
        await interaction.followup.send(embed=schedule_embed(day, date_str))
    except Exception as e:
        await interaction.followup.send(f"❌ `{e}`")


@bot.tree.command(name="jutro", description="Plan lekcji na jutro")
async def slash_jutro(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        target   = datetime.now(CET) + timedelta(days=1)
        date_str = target.strftime("%Y-%m-%d")
        client   = get_client()
        lessons  = client.get_lessons(target, target)
        day      = [l for l in lessons if l.get("Date", {}).get("Date") == date_str]
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
        lessons  = client.get_lessons(target, target)
        day      = [l for l in lessons if l.get("Date", {}).get("Date") == date_str]
        await interaction.followup.send(embed=schedule_embed(day, date_str))
    except Exception as e:
        await interaction.followup.send(f"❌ `{e}`")


@bot.tree.command(name="sprawdziany", description="Nadchodzące sprawdziany (domyślnie 2 tygodnie)")
async def slash_sprawdziany(interaction: discord.Interaction, tygodnie: int = 2):
    await interaction.response.defer()
    try:
        now    = datetime.now(CET)
        client = get_client()
        exams  = client.get_exams(now, now + timedelta(weeks=tygodnie))
        exams  = sorted(exams, key=lambda e: e.get("Deadline", {}).get("Date", "9999"))
        if not exams:
            await interaction.followup.send("✅ Brak sprawdzianów w tym okresie.")
            return
        await interaction.followup.send(f"**📝 Sprawdziany — najbliższe {tygodnie} tygodnie:**")
        for exam in exams:
            await interaction.followup.send(embed=exam_embed(exam))
    except Exception as e:
        await interaction.followup.send(f"❌ `{e}`")


@bot.tree.command(name="nastepny", description="Czas do następnego sprawdzianu")
async def slash_nastepny(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        now    = datetime.now(CET)
        client = get_client()
        exams  = client.get_exams(now, now + timedelta(weeks=8))
        exams  = sorted(exams, key=lambda e: e.get("Deadline", {}).get("Date", "9999"))
        if not exams:
            await interaction.followup.send("✅ Brak nadchodzących sprawdzianów.")
            return
        exam     = exams[0]
        deadline = exam.get("Deadline", {}).get("Date", "")
        subject  = exam.get("Subject", {}).get("Name", "?")
        try:
            d    = datetime.strptime(deadline, "%Y-%m-%d").replace(tzinfo=CET)
            diff = d - now
            days = diff.days
            time_str = f"za **{days} dni**" if days > 0 else "**dziś**"
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
        lucky = client.get_lucky_number()
        if lucky:
            slots.append(f"🍀 Szczęśliwy numerek: {lucky}")

        # Slot 3: ile lekcji dziś
        date_str = now.strftime("%Y-%m-%d")
        lessons  = client.get_lessons(now, now)
        today    = [l for l in lessons if l.get("Date", {}).get("Date") == date_str]
        if today:
            slots.append(f"📅 Dziś {len(today)} lekcji")

        # Slot 4: następny sprawdzian
        exams = client.get_exams(now, now + timedelta(weeks=8))
        exams = sorted(exams, key=lambda e: e.get("Deadline", {}).get("Date", "9999"))
        if exams:
            e    = exams[0]
            subj = e.get("Subject", {}).get("Name", "?")
            date = e.get("Deadline", {}).get("Date", "")
            try:
                d    = datetime.strptime(date, "%Y-%m-%d")
                diff = (d - now.replace(tzinfo=None)).days
                slots.append(f"📝 {subj} za {diff}d")
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

    check_exams.start()
    rotate_status.start()


# -------------------------------
# Run the bot
# -------------------------------
if __name__ == "__main__":
    bot.run(TOKEN)
