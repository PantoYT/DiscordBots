import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import os
import json
import pathlib
import asyncio
from datetime import datetime

load_dotenv()

TOKEN    = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))

POLLS_FILE = pathlib.Path(__file__).parent / "polls.json"
PRED_COLOR = 0xEC4899

REACTION_EMOJIS = ["🇦", "🇧", "🇨", "🇩"]
YES_NO_EMOJIS   = ["✅", "❌"]

intents = discord.Intents.default()
intents.message_content = True
intents.reactions = True
bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)

# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def load_polls() -> dict:
    try:
        with open(POLLS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_polls(data: dict):
    with open(POLLS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def poll_embed(question: str, options: list[str], author: discord.User | discord.Member, ended=False) -> discord.Embed:
    title = ("📊 Ankieta" if not ended else "📊 Ankieta — zakończona")
    embed = discord.Embed(title=title, description=f"**{question}**", color=PRED_COLOR)
    for i, opt in enumerate(options):
        embed.add_field(name=f"{REACTION_EMOJIS[i]} Opcja {chr(65+i)}", value=opt, inline=False)
    embed.set_footer(text=f"Autor: {author.display_name} • {'zakończona' if ended else 'zagłosuj reakcją'}")
    return embed

def yesno_embed(question: str, author: discord.User | discord.Member, ended=False) -> discord.Embed:
    embed = discord.Embed(
        title="🗳️ Szybka ankieta" + (" — zakończona" if ended else ""),
        description=f"**{question}**\n\n✅ Tak  ·  ❌ Nie",
        color=PRED_COLOR,
    )
    embed.set_footer(text=f"Autor: {author.display_name} • {'zakończona' if ended else 'zagłosuj reakcją'}")
    return embed

# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

@bot.tree.command(name="commands", description="Lista komend Pred")
async def slash_commands(interaction: discord.Interaction):
    embed = discord.Embed(title="Pred — Poll Bot", description="Ankiety i głosowania.", color=PRED_COLOR)
    embed.add_field(name="/poll",      value="Utwórz ankietę (2–4 opcje)",         inline=False)
    embed.add_field(name="/quickpoll", value="Szybka ankieta tak/nie",             inline=False)
    embed.add_field(name="/endpoll",   value="Zakończ ankietę i pokaż wyniki",     inline=False)
    embed.add_field(name="/polls",     value="Lista aktywnych ankiet na serwerze", inline=False)
    embed.set_footer(text="Pred • Poll Recurrent Editor & Dump")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="poll", description="Utwórz ankietę z 2–4 opcjami")
async def slash_poll(
    interaction: discord.Interaction,
    pytanie: str,
    opcja_a: str,
    opcja_b: str,
    opcja_c: str = None,
    opcja_d: str = None,
):
    options = [o for o in [opcja_a, opcja_b, opcja_c, opcja_d] if o]
    embed   = poll_embed(pytanie, options, interaction.user)
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()

    for i in range(len(options)):
        await msg.add_reaction(REACTION_EMOJIS[i])

    polls = load_polls()
    polls[str(msg.id)] = {
        "question": pytanie,
        "options":  options,
        "type":     "multi",
        "author_id": interaction.user.id,
        "channel_id": interaction.channel.id,
        "guild_id":   interaction.guild.id if interaction.guild else None,
        "created_at": datetime.utcnow().isoformat(),
        "ended": False,
    }
    save_polls(polls)


@bot.tree.command(name="quickpoll", description="Szybka ankieta tak/nie")
async def slash_quickpoll(interaction: discord.Interaction, pytanie: str):
    embed = yesno_embed(pytanie, interaction.user)
    await interaction.response.send_message(embed=embed)
    msg = await interaction.original_response()
    await msg.add_reaction("✅")
    await msg.add_reaction("❌")

    polls = load_polls()
    polls[str(msg.id)] = {
        "question":   pytanie,
        "options":    ["Tak", "Nie"],
        "type":       "yesno",
        "author_id":  interaction.user.id,
        "channel_id": interaction.channel.id,
        "guild_id":   interaction.guild.id if interaction.guild else None,
        "created_at": datetime.utcnow().isoformat(),
        "ended": False,
    }
    save_polls(polls)


@bot.tree.command(name="endpoll", description="Zakończ ankietę i pokaż wyniki (podaj ID wiadomości)")
async def slash_endpoll(interaction: discord.Interaction, message_id: str):
    polls = load_polls()
    poll  = polls.get(message_id)

    if not poll:
        await interaction.response.send_message("❌ Nie znaleziono ankiety o tym ID.", ephemeral=True)
        return

    if poll["ended"]:
        await interaction.response.send_message("❌ Ta ankieta jest już zakończona.", ephemeral=True)
        return

    is_owner  = interaction.user.id == OWNER_ID
    is_author = interaction.user.id == poll["author_id"]
    if not (is_owner or is_author):
        await interaction.response.send_message("❌ Tylko autor ankiety może ją zakończyć.", ephemeral=True)
        return

    await interaction.response.defer()

    try:
        channel = bot.get_channel(poll["channel_id"])
        msg     = await channel.fetch_message(int(message_id))
    except Exception:
        await interaction.followup.send("❌ Nie mogę pobrać wiadomości z ankietą.")
        return

    # Count reactions
    emojis   = YES_NO_EMOJIS if poll["type"] == "yesno" else REACTION_EMOJIS
    options  = poll["options"]
    results  = []
    for i, opt in enumerate(options):
        emoji  = emojis[i]
        rxn    = discord.utils.get(msg.reactions, emoji=emoji)
        count  = (rxn.count - 1) if rxn else 0  # -1 for bot's own reaction
        results.append((opt, count, emoji))

    total = sum(r[1] for r in results)

    embed = discord.Embed(
        title="📊 Wyniki ankiety",
        description=f"**{poll['question']}**",
        color=PRED_COLOR,
    )
    for opt, count, emoji in results:
        pct = round(count / total * 100) if total > 0 else 0
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        embed.add_field(
            name=f"{emoji} {opt}",
            value=f"`{bar}` {count} głosów ({pct}%)",
            inline=False,
        )
    embed.set_footer(text=f"Łącznie głosów: {total} • Pred")

    await interaction.followup.send(embed=embed)

    # Mark ended
    polls[message_id]["ended"] = True
    save_polls(polls)


@bot.tree.command(name="polls", description="Lista aktywnych ankiet na tym serwerze")
async def slash_polls(interaction: discord.Interaction):
    polls  = load_polls()
    guild_id = interaction.guild.id if interaction.guild else None
    active = [
        (mid, p) for mid, p in polls.items()
        if not p["ended"] and p.get("guild_id") == guild_id
    ]

    if not active:
        await interaction.response.send_message("Brak aktywnych ankiet.", ephemeral=True)
        return

    embed = discord.Embed(title="📋 Aktywne ankiety", color=PRED_COLOR)
    for mid, p in active[-10:]:
        embed.add_field(
            name=p["question"][:50],
            value=f"ID: `{mid}` · <#{p['channel_id']}>",
            inline=False,
        )
    embed.set_footer(text=f"Użyj /endpoll <ID> żeby zakończyć • Pred")
    await interaction.response.send_message(embed=embed)


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


@bot.tree.command(name="shutdown", description="Wyłącz Pred (owner only)")
async def slash_shutdown(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Nie masz uprawnień.", ephemeral=True)
        return
    await interaction.response.send_message("Wyłączam Pred...")
    await bot.close()

# ---------------------------------------------------------------------------
# Status rotation
# ---------------------------------------------------------------------------

_status_idx = 0
_status_slots = ["Ankiety | /poll", "Szybkie głosowania | /quickpoll", "Poll Recurrent Editor & Dump"]

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
    print(f"[Pred] Logged in as {bot.user}")
    print(f"[Pred] Guilds: {len(bot.guilds)}")
    try:
        synced = await bot.tree.sync()
        print(f"[Pred] Synced {len(synced)} commands")
        for guild in bot.guilds:
            await bot.tree.sync(guild=guild)
    except Exception as e:
        print(f"[Pred] Sync error: {e}")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="Ankiety | /poll"
    ))
    rotate_status.start()

if __name__ == "__main__":
    bot.run(TOKEN)
