import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import os
import json
import pathlib
import re
from datetime import datetime, timedelta, timezone

load_dotenv()

TOKEN    = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))

REMINDERS_FILE = pathlib.Path(__file__).parent / "reminders.json"
RRED_COLOR     = 0xEF4444

intents = discord.Intents.default()
bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def load_reminders() -> list:
    try:
        with open(REMINDERS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []

def save_reminders(data: list):
    with open(REMINDERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def next_id(reminders: list) -> int:
    return max((r["id"] for r in reminders), default=0) + 1

# ---------------------------------------------------------------------------
# Time parsing
# Formaty: 30s, 10m, 2h, 1d, 1h30m, DD/MM/YYYY HH:MM
# ---------------------------------------------------------------------------

TIME_PATTERN = re.compile(
    r'(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?'
)
DATE_PATTERN = re.compile(
    r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})\s+(\d{1,2}):(\d{2})'
)

def parse_time(s: str) -> datetime | None:
    """Parsuje czas względny (1h30m) lub absolutny (01/06/2026 15:30). Zwraca UTC datetime."""
    now = datetime.now(timezone.utc)

    # Absolutny
    m = DATE_PATTERN.match(s.strip())
    if m:
        try:
            dt = datetime(int(m[3]), int(m[2]), int(m[1]), int(m[4]), int(m[5]),
                          tzinfo=timezone.utc)
            return dt if dt > now else None
        except ValueError:
            return None

    # Względny
    m = TIME_PATTERN.match(s.strip())
    if not m or not any(m.groups()):
        return None
    days    = int(m[1] or 0)
    hours   = int(m[2] or 0)
    minutes = int(m[3] or 0)
    seconds = int(m[4] or 0)
    delta   = timedelta(days=days, hours=hours, minutes=minutes, seconds=seconds)
    if delta.total_seconds() <= 0:
        return None
    return now + delta

def fmt_delta(dt: datetime) -> str:
    now   = datetime.now(timezone.utc)
    secs  = int((dt - now).total_seconds())
    if secs < 60:
        return f"{secs}s"
    if secs < 3600:
        return f"{secs//60}m {secs%60}s"
    if secs < 86400:
        return f"{secs//3600}h {(secs%3600)//60}m"
    return f"{secs//86400}d {(secs%86400)//3600}h"

# ---------------------------------------------------------------------------
# Background task
# ---------------------------------------------------------------------------

@tasks.loop(seconds=30)
async def check_reminders():
    reminders = load_reminders()
    now       = datetime.now(timezone.utc)
    remaining = []
    changed   = False

    for r in reminders:
        due = datetime.fromisoformat(r["due"])
        if due <= now:
            changed = True
            try:
                user = await bot.fetch_user(r["user_id"])
                embed = discord.Embed(
                    title="⏰ Przypomnienie!",
                    description=r["message"],
                    color=RRED_COLOR,
                )
                embed.set_footer(text=f"Ustawione: {r['created_at'][:16].replace('T', ' ')} UTC • Rred")
                await user.send(embed=embed)
                # Też wyślij na kanał jeśli był podany
                if r.get("channel_id"):
                    ch = bot.get_channel(r["channel_id"])
                    if ch:
                        await ch.send(f"<@{r['user_id']}>", embed=embed)
            except Exception as e:
                print(f"[Rred] Reminder send error: {e}")
        else:
            remaining.append(r)

    if changed:
        save_reminders(remaining)

@check_reminders.before_loop
async def before_check():
    await bot.wait_until_ready()

# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

@bot.tree.command(name="commands", description="Lista komend Rred")
async def slash_commands(interaction: discord.Interaction):
    embed = discord.Embed(title="Rred — Reminder Bot", description="Przypomnienia i timery.", color=RRED_COLOR)
    embed.add_field(name="/remind <czas> <wiadomość>", value="Ustaw przypomnienie\nCzas: `30m`, `2h`, `1d`, `1h30m`, `DD/MM/YYYY HH:MM`", inline=False)
    embed.add_field(name="/reminders",                 value="Lista twoich przypomnień",                inline=False)
    embed.add_field(name="/cancel <id>",               value="Anuluj przypomnienie",                    inline=False)
    embed.set_footer(text="Rred • Reminder Recurrent Editor & Dump")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="remind", description="Ustaw przypomnienie (np. 30m, 2h, 1d, DD/MM/YYYY HH:MM)")
async def slash_remind(interaction: discord.Interaction, czas: str, wiadomosc: str):
    due = parse_time(czas)
    if not due:
        await interaction.response.send_message(
            "❌ Nieprawidłowy format czasu.\nPrzykłady: `30m`, `2h`, `1d`, `1h30m`, `01/06/2026 15:30`",
            ephemeral=True,
        )
        return

    reminders = load_reminders()
    rid       = next_id(reminders)
    reminders.append({
        "id":         rid,
        "user_id":    interaction.user.id,
        "channel_id": interaction.channel.id if interaction.guild else None,
        "message":    wiadomosc,
        "due":        due.isoformat(),
        "created_at": datetime.now(timezone.utc).isoformat(),
    })
    save_reminders(reminders)

    embed = discord.Embed(
        title="✅ Przypomnienie ustawione",
        description=f"**{wiadomosc}**",
        color=RRED_COLOR,
    )
    embed.add_field(name="Za", value=fmt_delta(due), inline=True)
    embed.add_field(name="O",  value=f"<t:{int(due.timestamp())}:f>", inline=True)
    embed.add_field(name="ID", value=str(rid), inline=True)
    embed.set_footer(text="Dostaniesz DM + wiadomość na kanale • Rred")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="reminders", description="Lista twoich aktywnych przypomnień")
async def slash_reminders(interaction: discord.Interaction):
    reminders = load_reminders()
    mine      = [r for r in reminders if r["user_id"] == interaction.user.id]

    if not mine:
        await interaction.response.send_message("Nie masz żadnych przypomnień.", ephemeral=True)
        return

    embed = discord.Embed(title="⏰ Twoje przypomnienia", color=RRED_COLOR)
    for r in mine[:10]:
        due = datetime.fromisoformat(r["due"])
        embed.add_field(
            name=f"#{r['id']} — za {fmt_delta(due)}",
            value=f"{r['message'][:80]}\n<t:{int(due.timestamp())}:f>",
            inline=False,
        )
    embed.set_footer(text=f"Łącznie: {len(mine)} • Rred")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="cancel", description="Anuluj przypomnienie po ID")
async def slash_cancel(interaction: discord.Interaction, id: int):
    reminders = load_reminders()
    target    = next((r for r in reminders if r["id"] == id and r["user_id"] == interaction.user.id), None)

    if not target and interaction.user.id == OWNER_ID:
        target = next((r for r in reminders if r["id"] == id), None)

    if not target:
        await interaction.response.send_message("❌ Nie znaleziono przypomnienia.", ephemeral=True)
        return

    reminders.remove(target)
    save_reminders(reminders)
    await interaction.response.send_message(f"✅ Anulowano przypomnienie #{id}: *{target['message'][:50]}*")


@bot.tree.command(name="sync", description="Force sync (owner only)")
async def slash_sync(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Tylko właściciel.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    synced = await bot.tree.sync()
    if interaction.guild:
        await bot.tree.sync(guild=interaction.guild)
    await interaction.followup.send(f"✅ {len(synced)} komend", ephemeral=True)


@bot.tree.command(name="shutdown", description="Wyłącz Rred (owner only)")
async def slash_shutdown(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Nie masz uprawnień.", ephemeral=True)
        return
    await interaction.response.send_message("Wyłączam Rred...")
    await bot.close()

# ---------------------------------------------------------------------------
# Status rotation
# ---------------------------------------------------------------------------

_status_idx   = 0
_status_slots = ["Przypomnienia | /remind", "Timery i alerty | /commands", "Reminder Recurrent Editor & Dump"]

@tasks.loop(minutes=5)
async def rotate_status():
    global _status_idx
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name=_status_slots[_status_idx % len(_status_slots)],
    ))
    _status_idx += 1

@rotate_status.before_loop
async def before_rotate():
    await bot.wait_until_ready()

# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@bot.event
async def on_ready():
    print(f"[Rred] Logged in as {bot.user}")
    print(f"[Rred] Guilds: {len(bot.guilds)}")
    print(f"[Rred] Pending reminders: {len(load_reminders())}")
    try:
        synced = await bot.tree.sync()
        print(f"[Rred] Synced {len(synced)} commands")
        for guild in bot.guilds:
            await bot.tree.sync(guild=guild)
    except Exception as e:
        print(f"[Rred] Sync error: {e}")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="Przypomnienia | /remind"
    ))
    check_reminders.start()
    rotate_status.start()

if __name__ == "__main__":
    bot.run(TOKEN)
