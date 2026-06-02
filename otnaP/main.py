import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import os
import httpx

load_dotenv()

TOKEN    = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# ---------------------------------------------------------------------------
# Bot registry — single source of truth for the *red family
# ---------------------------------------------------------------------------

BOTS = {
    "Fred": {
        "id":          int(os.getenv("FRED_ID", 0)),
        "description": "Free Recurrent Epicgames Dump — darmowe gry z Epic Games co tydzień",
        "commands":    ["/games", "/confirmchannel", "/commands"],
        "keywords":    ["epic", "gry", "free", "darmowe", "games"],
        "color":       0x313131,
        "emoji":       "🎮",
    },
    "Qred": {
        "id":          int(os.getenv("QRED_ID", 0)),
        "description": "Quote Recurrent Editor & Dump — cytaty, daily quote, zarządzanie cytatami",
        "commands":    ["/random", "/daily", "/create", "/add", "/mine", "/edit", "/delete"],
        "keywords":    ["cytat", "quote", "cytaty", "said", "słowa", "filozofia"],
        "color":       0x1E3A8A,
        "emoji":       "💬",
    },
    "Tred": {
        "id":          int(os.getenv("TRED_ID", 0)),
        "description": "Trivia Recurrent Editor & Dump — trivia, funfacts, kategorie, statystyki",
        "commands":    ["/random", "/daily", "/category", "/categories", "/create", "/stats", "/search"],
        "keywords":    ["trivia", "funfact", "fakt", "ciekawostka", "wiedza", "quiz"],
        "color":       0x8B5CF6,
        "emoji":       "🧠",
    },
    "Vred": {
        "id":          int(os.getenv("VRED_ID", 0)),
        "description": "Vulcan Recurrent Education Dump — plan lekcji i sprawdziany z eduVulcana",
        "commands":    ["/plan", "/jutro", "/dzien", "/sprawdziany", "/nastepny", "/setup"],
        "keywords":    ["plan", "lekcje", "sprawdzian", "szkoła", "vulcan", "eduvulcan", "jutro"],
        "color":       0x2F6FEB,
        "emoji":       "📚",
    },
    "Pred": {
        "id":          int(os.getenv("PRED_ID", 0)),
        "description": "Poll Recurrent Editor & Dump — ankiety i głosowania",
        "commands":    ["/poll", "/quickpoll", "/endpoll", "/polls"],
        "keywords":    ["ankieta", "poll", "głosowanie", "vote", "wybór"],
        "color":       0xEC4899,
        "emoji":       "📊",
    },
    "Rred": {
        "id":          int(os.getenv("RRED_ID", 0)),
        "description": "Reminder Recurrent Editor & Dump — przypomnienia i timery",
        "commands":    ["/remind", "/reminders", "/cancel"],
        "keywords":    ["przypomnij", "remind", "timer", "alarm", "za", "przypomnienie"],
        "color":       0xEF4444,
        "emoji":       "⏰",
    },
    "Ared": {
        "id":          int(os.getenv("ARED_ID", 0)),
        "description": "Admin Recurrent Editor & Dump — moderacja i zarządzanie serwerem",
        "commands":    ["/kick", "/ban", "/mute", "/warn", "/clear", "/lock"],
        "keywords":    ["ban", "kick", "mute", "warn", "mod", "moderacja", "admin", "wyrzuć", "zbanuj"],
        "color":       0xDC2626,
        "emoji":       "🛡️",
    },
    "Mred": {
        "id":          int(os.getenv("MRED_ID", 0)),
        "description": "Music Recurrent Editor & Dump — eksploracja muzyki przez Last.fm",
        "commands":    ["/search", "/artist", "/toptracks", "/album", "/similar", "/topcharts", "/tag"],
        "keywords":    ["muzyka", "music", "lastfm", "piosenka", "artysta", "album", "gatunek", "podobni"],
        "color":       0x1DB954,
        "emoji":       "🎵",
    },
}

OTNAP_COLOR = 0xF59E0B  # amber — orchestrator gold

# ---------------------------------------------------------------------------
# OpenRouter (Gemini 1.5 Flash przez API) — opcjonalny
# ---------------------------------------------------------------------------

OPENROUTER_URL    = "https://openrouter.ai/api/v1/chat/completions"
OPENROUTER_MODEL  = "google/gemini-flash-1.5"  # darmowy model na OpenRouter

ai_enabled = bool(OPENROUTER_API_KEY)
print(f"[otnaP] AI (/ask): {'enabled — ' + OPENROUTER_MODEL if ai_enabled else 'disabled (brak OPENROUTER_API_KEY)'}")


def build_system_prompt() -> str:
    lines = [
        "Jesteś otnaP — orkiestrator rodziny botów Discordowych *red.",
        "Odpowiedz krótko po polsku (max 3 zdania). Wskaż który bot pomoże i jaką komendą.",
        "Jeśli potrzeba kilku botów — wymień je wszystkie.\n",
        "Dostępne boty:\n",
    ]
    for name, data in BOTS.items():
        cmds = ", ".join(data["commands"])
        lines.append(f"- {data['emoji']} {name}: {data['description']}")
        lines.append(f"  Komendy: {cmds}")
    return "\n".join(lines)


async def ask_ai(query: str) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/panto-discord",
        "X-Title": "otnaP Discord Bot",
    }
    payload = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system",  "content": build_system_prompt()},
            {"role": "user",    "content": query},
        ],
        "max_tokens": 300,
    }
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(OPENROUTER_URL, headers=headers, json=payload)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()


def keyword_route(query: str) -> list[str]:
    q = query.lower()
    matches = []
    for name, data in BOTS.items():
        if any(kw in q for kw in data["keywords"]):
            matches.append(name)
    return matches

# ---------------------------------------------------------------------------
# Discord setup
# ---------------------------------------------------------------------------

intents = discord.Intents.default()
# Presence/Members intent wymaga włączenia w Discord Developer Portal:
# discord.com/developers/applications → Bot → Privileged Gateway Intents
# Bez tego /status nie pokazuje online/offline innych botów
PRESENCE_ENABLED = os.getenv("PRESENCE_INTENT", "false").lower() == "true"
if PRESENCE_ENABLED:
    intents.members   = True
    intents.presences = True

bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)


async def get_bot_status(guild: discord.Guild, bot_id: int) -> str:
    if not bot_id:
        return "❓ nieznany"
    member = guild.get_member(bot_id)
    if not member:
        return "⚫ offline"
    if member.status == discord.Status.online:
        return "🟢 online"
    if member.status == discord.Status.idle:
        return "🟡 idle"
    if member.status == discord.Status.dnd:
        return "🔴 dnd"
    return "⚫ offline"

# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

@bot.tree.command(name="commands", description="Lista komend otnaP")
async def slash_commands(interaction: discord.Interaction):
    embed = discord.Embed(
        title="otnaP — Orkiestrator",
        description="Centrum dowodzenia rodziny botów \\*red.",
        color=OTNAP_COLOR,
    )
    embed.add_field(name="/bots",   value="Lista wszystkich botów i ich funkcji",             inline=False)
    embed.add_field(name="/status", value="Status każdego bota (online/offline)",             inline=False)
    embed.add_field(name="/ask",    value="Zapytaj co który bot potrafi (Gemini AI)",         inline=False)
    embed.add_field(name="/route",  value="Keyword routing — znajdź bota bez AI",            inline=False)
    embed.add_field(name="/ping",   value="Latencja otnaP",                                  inline=False)
    embed.add_field(name="/sync",   value="Force sync slash commands (owner only)",           inline=False)
    embed.add_field(name="/shutdown", value="Wyłącz otnaP (owner only)",                    inline=False)
    embed.set_footer(text="otnaP • Panto Infrastructure")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="bots", description="Lista wszystkich botów *red i ich funkcji")
async def slash_bots(interaction: discord.Interaction):
    embed = discord.Embed(
        title="Rodzina botów \\*red",
        description="Każdy bot ma jedno zadanie. otnaP łączy je w całość.",
        color=OTNAP_COLOR,
    )
    for name, data in BOTS.items():
        cmds = " · ".join(f"`{c}`" for c in data["commands"][:4])
        embed.add_field(
            name=f"{data['emoji']} {name}",
            value=f"{data['description']}\n{cmds}",
            inline=False,
        )
    embed.set_footer(text="otnaP • użyj /status żeby sprawdzić czy są online")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="status", description="Status wszystkich botów *red na tym serwerze")
async def slash_status(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("Komenda tylko na serwerze.", ephemeral=True)
        return

    await interaction.response.defer()

    embed = discord.Embed(
        title="Status — rodzina \\*red",
        color=OTNAP_COLOR,
    )

    all_online = True
    for name, data in BOTS.items():
        status = await get_bot_status(guild, data["id"])
        if "online" not in status:
            all_online = False
        embed.add_field(
            name=f"{data['emoji']} {name}",
            value=status,
            inline=True,
        )

    otnap_latency = round(bot.latency * 1000)
    embed.add_field(name="🟡 otnaP (ja)", value=f"🟢 online ({otnap_latency}ms)", inline=True)

    embed.set_footer(
        text="✅ Wszystkie systemy operacyjne" if all_online else "⚠️ Niektóre boty offline",
    )
    await interaction.followup.send(embed=embed)


@bot.tree.command(name="route", description="Znajdź bota do swojego zadania (bez AI, keyword matching)")
async def slash_route(interaction: discord.Interaction, zapytanie: str):
    matches = keyword_route(zapytanie)

    if not matches:
        embed = discord.Embed(
            title="🤷 Nie znaleziono dopasowania",
            description=f"Żaden bot nie pasuje do: *{zapytanie}*\n\nSpróbuj `/ask` z Gemini AI lub `/bots` żeby przejrzeć wszystkie.",
            color=0xFF6B6B,
        )
        await interaction.response.send_message(embed=embed)
        return

    embed = discord.Embed(
        title="📡 Routing",
        description=f"Dla zapytania: *{zapytanie}*",
        color=OTNAP_COLOR,
    )
    for name in matches:
        data = BOTS[name]
        cmds = " · ".join(f"`{c}`" for c in data["commands"][:3])
        embed.add_field(
            name=f"{data['emoji']} {name}",
            value=f"{data['description']}\n{cmds}",
            inline=False,
        )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="ask", description="Zapytaj otnaP co który bot potrafi (Gemini AI via OpenRouter)")
async def slash_ask(interaction: discord.Interaction, zapytanie: str):
    if not ai_enabled:
        # Fallback — keyword routing
        matches = keyword_route(zapytanie)
        if matches:
            embed = discord.Embed(
                title="📡 Routing (keyword)",
                description=f"*(AI niedostępne — keyword matching)*\n\nDla: *{zapytanie}*",
                color=OTNAP_COLOR,
            )
            for name in matches:
                data = BOTS[name]
                embed.add_field(name=f"{data['emoji']} {name}", value=data["description"], inline=False)
        else:
            embed = discord.Embed(
                title="❓ Nie wiem",
                description=f"Brak AI i keyword routing nie znalazł dopasowania.\nUżyj `/bots` żeby przejrzeć boty.",
                color=0xFF6B6B,
            )
        await interaction.response.send_message(embed=embed)
        return

    await interaction.response.defer()
    try:
        answer = await ask_ai(zapytanie)
        embed = discord.Embed(
            title="🤖 otnaP odpowiada",
            description=answer,
            color=OTNAP_COLOR,
        )
        embed.set_footer(text=f"Gemini via OpenRouter • /bots dla pełnej listy")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ AI error: `{e}`")


@bot.tree.command(name="ping", description="Sprawdź latencję otnaP")
async def slash_ping(interaction: discord.Interaction):
    latency = round(bot.latency * 1000)
    embed = discord.Embed(
        title="🏓 Pong!",
        description=f"Latencja: **{latency}ms**",
        color=OTNAP_COLOR,
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="sync", description="Force sync slash commands (owner only)")
async def slash_sync(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Tylko właściciel.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    try:
        synced = await bot.tree.sync()
        if interaction.guild:
            guild_synced = await bot.tree.sync(guild=interaction.guild)
            await interaction.followup.send(
                f"✅ {len(synced)} global · {len(guild_synced)} guild",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(f"✅ {len(synced)} global", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ {e}", ephemeral=True)


@bot.tree.command(name="shutdown", description="Wyłącz otnaP (owner only)")
async def slash_shutdown(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Nie masz uprawnień.", ephemeral=True)
        return
    await interaction.response.send_message("Wyłączam otnaP...")
    await bot.close()

# ---------------------------------------------------------------------------
# Rotating status
# ---------------------------------------------------------------------------

_status_slots = [
    "Panto Infrastructure | /bots",
    f"Zarządzam {len(BOTS)} botami",
    "Routing requests | /ask",
    "All systems operational",
]
_status_idx = 0

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
    print(f"[otnaP] Logged in as {bot.user}")
    print(f"[otnaP] Guilds: {len(bot.guilds)}")
    print(f"[otnaP] Commands: {[cmd.name for cmd in bot.tree.get_commands()]}")
    print(f"[otnaP] AI: {'enabled' if ai_enabled else 'disabled'}")

    try:
        synced = await bot.tree.sync()
        print(f"[otnaP] Synced {len(synced)} commands")
        for guild in bot.guilds:
            await bot.tree.sync(guild=guild)
    except Exception as e:
        print(f"[otnaP] Sync error: {e}")

    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="Panto Infrastructure | /bots",
    ))
    rotate_status.start()


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    bot.run(TOKEN)
