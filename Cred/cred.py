"""
Cred — the Claude bot of the family (Ared, Fred, Mred, otnaP, Pred, Qred, Rred,
Tred, Vred … and now Cred). Cred reports on the autonomous Amberfall project: it
DMs the owner an Amberfall status + latest render every 30 min, answers /raport on
demand, and records the owner's verdict via /odpowiedz so the autonomous loop can
read it. discord.py, slash commands only (no privileged intents). Accent: amber.

Config in .env: DISCORD_TOKEN, OWNER_ID, AMBERFALL_DIR, REPORT_INTERVAL_MIN,
EMBED_COLOR, REPORT_CHANNEL_ID (optional).
"""
import os
import re
import glob
import time
import pathlib

import discord
from discord import app_commands
from discord.ext import commands, tasks
from dotenv import load_dotenv

load_dotenv(pathlib.Path(__file__).with_name(".env"))

TOKEN = os.environ["DISCORD_TOKEN"]
OWNER_ID = int(os.environ.get("OWNER_ID", "0"))
AMBERFALL_DIR = pathlib.Path(os.environ.get("AMBERFALL_DIR", os.path.expanduser("~/amberfall")))
INTERVAL_MIN = int(os.environ.get("REPORT_INTERVAL_MIN", "30"))
EMBED_COLOR = int(os.environ.get("EMBED_COLOR", "0xFFB13B"), 16) if isinstance(
    os.environ.get("EMBED_COLOR", "0xFFB13B"), str) else 0xFFB13B
CHANNEL_ID = int(os.environ["REPORT_CHANNEL_ID"]) if os.environ.get("REPORT_CHANNEL_ID") else 0

PROGRESS = AMBERFALL_DIR / "PROGRESS.md"
MILESTONES = AMBERFALL_DIR / "preview" / "milestones"
VERDICT_FILE = AMBERFALL_DIR / "preview" / "owner_verdict.txt"
ALIVE_FILE = pathlib.Path(__file__).with_name("cred.alive")

intents = discord.Intents.none()
intents.guilds = True
bot = commands.Bot(command_prefix="!cred ", intents=intents)


def heartbeat() -> None:
    """Touch a liveness file so the keepalive cron knows Cred is connected."""
    try:
        ALIVE_FILE.write_text(str(int(time.time())))
    except OSError:
        pass


def latest_milestone() -> pathlib.Path | None:
    shots = sorted(glob.glob(str(MILESTONES / "*.png")), key=os.path.getmtime)
    return pathlib.Path(shots[-1]) if shots else None


def last_progress_block() -> str:
    """Most recent report block (deploy/report.sh writes '<!-- report ... -->'),
    else the last dated section heading + a few lines."""
    if not PROGRESS.exists():
        return "Brak PROGRESS.md — Amberfall jeszcze nie raportował."
    text = PROGRESS.read_text(errors="replace")
    blocks = list(re.finditer(r"<!-- report .*?-->", text))
    if blocks:
        tail = text[blocks[-1].end():].strip()
        return tail[:1500] or "(pusty raport)"
    # fallback: last "## " section, trimmed
    sections = text.split("\n## ")
    return ("## " + sections[-1]).strip()[:1500] if len(sections) > 1 else text[-1500:]


def presence_text() -> str:
    """Short custom status — reflects the latest Amberfall render so Cred isn't naked."""
    shot = latest_milestone()
    if shot:
        return f"🌥️ Amberfall · {shot.stem}"
    return "🌥️ Amberfall · /commands"


async def refresh_presence() -> None:
    try:
        await bot.change_presence(
            status=discord.Status.online,
            activity=discord.CustomActivity(name=presence_text()),
        )
    except discord.HTTPException:
        pass


def build_report() -> tuple[discord.Embed, discord.File | None]:
    embed = discord.Embed(
        title="🌥️  Amberfall — raport",
        description=last_progress_block(),
        color=EMBED_COLOR,
    )
    shot = latest_milestone()
    f = None
    if shot:
        f = discord.File(str(shot), filename=shot.name)
        embed.set_image(url=f"attachment://{shot.name}")
        embed.add_field(name="Render", value=shot.name, inline=False)
    embed.set_footer(text="Cred • Amberfall  ·  /raport  /odpowiedz  /status  /commands")
    return embed, f


async def deliver_report() -> None:
    embed, f = build_report()
    target = None
    if CHANNEL_ID:
        target = bot.get_channel(CHANNEL_ID)
    if target is None and OWNER_ID:
        target = await bot.fetch_user(OWNER_ID)
    if target is not None:
        await target.send(embed=embed, file=f) if f else await target.send(embed=embed)


def is_owner_interaction(interaction: discord.Interaction) -> bool:
    return interaction.user.id == OWNER_ID


# --------------------------------------------------------------------------- #
@bot.event
async def on_ready() -> None:
    heartbeat()
    try:
        await bot.tree.sync()
    except discord.HTTPException:
        pass
    await refresh_presence()
    if not periodic_report.is_running():
        periodic_report.start()
    print(f"Cred online as {bot.user} — reporting every {INTERVAL_MIN} min")


@tasks.loop(minutes=INTERVAL_MIN)
async def periodic_report() -> None:
    heartbeat()
    await refresh_presence()
    try:
        await deliver_report()
    except discord.HTTPException as e:
        print(f"periodic_report failed: {e}")


@periodic_report.before_loop
async def _before() -> None:
    await bot.wait_until_ready()


@bot.tree.command(name="commands", description="Lista komend Creda")
async def commands_cmd(interaction: discord.Interaction) -> None:
    embed = discord.Embed(title="Cred — komendy", color=EMBED_COLOR)
    embed.description = (
        "**/raport** — natychmiastowy raport Amberfall (render + status)\n"
        "**/odpowiedz** `tekst` — Twój werdykt 👍/👎/uwagi (czyta go autonomiczny loop)\n"
        "**/status** — krótki status tekstowy\n"
        "**/shutdown** — wyłącz Creda (tylko właściciel)\n"
        f"\nRaport automatyczny co **{INTERVAL_MIN} min**."
    )
    embed.set_footer(text="Cred • Amberfall")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="raport", description="Natychmiastowy raport Amberfall")
async def raport_cmd(interaction: discord.Interaction) -> None:
    if not is_owner_interaction(interaction):
        await interaction.response.send_message("Tylko właściciel.", ephemeral=True)
        return
    await interaction.response.defer(thinking=True, ephemeral=False)
    embed, f = build_report()
    await interaction.followup.send(embed=embed, file=f) if f else await interaction.followup.send(embed=embed)


@bot.tree.command(name="odpowiedz", description="Zapisz werdykt dla autonomicznego Amberfall (np. 👍 / 👎 / uwagi)")
@app_commands.describe(tekst="Twój werdykt lub uwagi do ostatniego milestone'a")
async def odpowiedz_cmd(interaction: discord.Interaction, tekst: str) -> None:
    if not is_owner_interaction(interaction):
        await interaction.response.send_message("Tylko właściciel.", ephemeral=True)
        return
    VERDICT_FILE.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    with VERDICT_FILE.open("a") as fh:
        fh.write(f"[{stamp}] {tekst}\n")
    await interaction.response.send_message(
        f"Zapisano werdykt — autonomiczny loop go odczyta:\n> {tekst}", ephemeral=True)


@bot.tree.command(name="status", description="Krótki status tekstowy Amberfall")
async def status_cmd(interaction: discord.Interaction) -> None:
    block = last_progress_block()
    short = block if len(block) < 1000 else block[:1000] + " …"
    embed = discord.Embed(title="Amberfall — status", description=short, color=EMBED_COLOR)
    embed.set_footer(text="Cred • Amberfall")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="shutdown", description="Wyłącz Creda (tylko właściciel)")
async def shutdown_cmd(interaction: discord.Interaction) -> None:
    if not is_owner_interaction(interaction):
        await interaction.response.send_message("Tylko właściciel.", ephemeral=True)
        return
    await interaction.response.send_message("Cred się wyłącza. 🌙", ephemeral=True)
    await bot.close()


if __name__ == "__main__":
    bot.run(TOKEN)
