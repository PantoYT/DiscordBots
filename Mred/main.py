import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import os
import httpx

load_dotenv()

TOKEN       = os.getenv("DISCORD_TOKEN")
OWNER_ID    = int(os.getenv("OWNER_ID"))
LASTFM_KEY  = os.getenv("LASTFM_API_KEY", "")

MRED_COLOR  = 0xD51007  # Last.fm red

LASTFM_URL  = "https://ws.audioscrobbler.com/2.0/"

intents = discord.Intents.default()
bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)

# ---------------------------------------------------------------------------
# Last.fm helper
# ---------------------------------------------------------------------------

async def lfm(method: str, params: dict) -> dict:
    p = {"method": method, "api_key": LASTFM_KEY, "format": "json", **params}
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(LASTFM_URL, params=p)
        r.raise_for_status()
        return r.json()

def lfm_img(images: list) -> str | None:
    """Zwraca największy dostępny obrazek z Last.fm."""
    for size in ("extralarge", "large", "medium"):
        for img in images:
            if img.get("size") == size and img.get("#text"):
                return img["#text"]
    return None

# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

@bot.tree.command(name="commands", description="Lista komend Mred")
async def slash_commands(interaction: discord.Interaction):
    embed = discord.Embed(title="Mred — Music Bot", description="Eksploracja muzyki przez Last.fm API.", color=MRED_COLOR)
    embed.add_field(name="/search <utwór>",       value="Szukaj utworu na Last.fm",              inline=False)
    embed.add_field(name="/artist <nazwa>",        value="Info o artyście + podobni",             inline=False)
    embed.add_field(name="/toptracks <artysta>",   value="Top tracki artysty",                    inline=False)
    embed.add_field(name="/album <artysta> <alb>", value="Info o albumie + tracklista",           inline=False)
    embed.add_field(name="/similar <artysta>",     value="Podobni artyści",                       inline=False)
    embed.add_field(name="/topcharts",             value="Globalne top tracki tego tygodnia",     inline=False)
    embed.add_field(name="/tag <gatunek>",         value="Top tracki z gatunku",                  inline=False)
    embed.set_footer(text="Mred • Music Recurrent Editor & Dump • Last.fm")
    await interaction.response.send_message(embed=embed)
    if not LASTFM_KEY:
        await interaction.followup.send("⚠️ Brak `LASTFM_API_KEY` w `.env`.", ephemeral=True)


@bot.tree.command(name="search", description="Szukaj utworu na Last.fm")
async def slash_search(interaction: discord.Interaction, utwor: str):
    await interaction.response.defer()
    try:
        data   = await lfm("track.search", {"track": utwor, "limit": 6})
        tracks = data["results"]["trackmatches"]["track"]
        if not tracks:
            await interaction.followup.send("❌ Brak wyników."); return

        embed = discord.Embed(title=f"🔍 Wyniki: {utwor}", color=MRED_COLOR)
        for t in tracks[:6]:
            listeners = t.get("listeners", "?")
            url       = t.get("url", "")
            embed.add_field(
                name=f"{t['name']}",
                value=f"**{t['artist']}**\n👥 {int(listeners):,} słuchaczy\n[Last.fm]({url})",
                inline=True,
            )
        embed.set_footer(text="Mred • Last.fm")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Błąd: `{e}`")


@bot.tree.command(name="artist", description="Info o artyście")
async def slash_artist(interaction: discord.Interaction, nazwa: str):
    await interaction.response.defer()
    try:
        data   = await lfm("artist.getInfo", {"artist": nazwa, "autocorrect": 1})
        artist = data["artist"]

        name      = artist["name"]
        url       = artist["url"]
        listeners = int(artist["stats"]["listeners"])
        playcount = int(artist["stats"]["playcount"])
        bio       = artist.get("bio", {}).get("summary", "Brak opisu.")
        bio       = bio.split("<a href")[0].strip()[:300] + "..." if len(bio) > 300 else bio
        tags      = ", ".join(t["name"] for t in artist.get("tags", {}).get("tag", [])[:5]) or "—"
        image     = lfm_img(artist.get("image", []))

        embed = discord.Embed(title=name, url=url, description=bio, color=MRED_COLOR)
        embed.add_field(name="Słuchaczy",   value=f"{listeners:,}", inline=True)
        embed.add_field(name="Odtworzeń",   value=f"{playcount:,}", inline=True)
        embed.add_field(name="Gatunki",     value=tags,             inline=False)
        if image:
            embed.set_thumbnail(url=image)
        embed.set_footer(text="Mred • Last.fm")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Błąd: `{e}`")


@bot.tree.command(name="toptracks", description="Top tracki artysty")
async def slash_toptracks(interaction: discord.Interaction, artysta: str):
    await interaction.response.defer()
    try:
        data   = await lfm("artist.getTopTracks", {"artist": artysta, "autocorrect": 1, "limit": 8})
        tracks = data["toptracks"]["track"]
        if not tracks:
            await interaction.followup.send("❌ Brak wyników."); return

        name  = tracks[0]["artist"]["name"]
        embed = discord.Embed(title=f"🎵 Top tracki — {name}", color=MRED_COLOR)
        for i, t in enumerate(tracks, 1):
            plays = int(t.get("playcount", 0))
            url   = t.get("url", "")
            embed.add_field(
                name=f"{i}. {t['name']}",
                value=f"▶️ {plays:,} odtworzeń\n[Last.fm]({url})",
                inline=True,
            )
        embed.set_footer(text="Mred • Last.fm")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Błąd: `{e}`")


@bot.tree.command(name="album", description="Info o albumie i tracklista")
async def slash_album(interaction: discord.Interaction, artysta: str, album: str):
    await interaction.response.defer()
    try:
        data  = await lfm("album.getInfo", {"artist": artysta, "album": album, "autocorrect": 1})
        alb   = data["album"]

        name      = alb["name"]
        artist    = alb["artist"]
        url       = alb["url"]
        playcount = int(alb.get("playcount", 0))
        listeners = int(alb.get("listeners", 0))
        tags      = ", ".join(t["name"] for t in alb.get("tags", {}).get("tag", [])[:4]) or "—"
        image     = lfm_img(alb.get("image", []))
        tracks    = alb.get("tracks", {}).get("track", [])[:10]

        embed = discord.Embed(title=f"{name}", url=url, color=MRED_COLOR)
        embed.add_field(name="Artysta",    value=artist,          inline=True)
        embed.add_field(name="Słuchaczy",  value=f"{listeners:,}", inline=True)
        embed.add_field(name="Odtworzeń",  value=f"{playcount:,}", inline=True)
        embed.add_field(name="Gatunki",    value=tags,            inline=False)

        if tracks:
            tlist = "\n".join(
                f"`{t['@attr']['rank']}.` {t['name']}" if isinstance(t, dict) and "@attr" in t
                else f"`{i}.` {t['name']}"
                for i, t in enumerate(tracks, 1)
            )
            embed.add_field(name="Tracklista", value=tlist[:1024], inline=False)

        if image:
            embed.set_thumbnail(url=image)
        embed.set_footer(text="Mred • Last.fm")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Błąd: `{e}`")


@bot.tree.command(name="similar", description="Artyści podobni do podanego")
async def slash_similar(interaction: discord.Interaction, artysta: str):
    await interaction.response.defer()
    try:
        data    = await lfm("artist.getSimilar", {"artist": artysta, "autocorrect": 1, "limit": 8})
        similar = data["similarartists"]["artist"]
        if not similar:
            await interaction.followup.send("❌ Brak podobnych artystów."); return

        embed = discord.Embed(title=f"🎸 Podobni do {artysta}", color=MRED_COLOR)
        for a in similar:
            match = round(float(a.get("match", 0)) * 100)
            url   = a.get("url", "")
            embed.add_field(
                name=a["name"],
                value=f"Zgodność: {match}%\n[Last.fm]({url})",
                inline=True,
            )
        embed.set_footer(text="Mred • Last.fm")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Błąd: `{e}`")


@bot.tree.command(name="topcharts", description="Globalne top tracki tego tygodnia")
async def slash_topcharts(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        data   = await lfm("chart.getTopTracks", {"limit": 10})
        tracks = data["tracks"]["track"]

        embed = discord.Embed(title="🌍 Globalne top tracki", color=MRED_COLOR)
        for i, t in enumerate(tracks, 1):
            plays = int(t.get("playcount", 0))
            url   = t.get("url", "")
            embed.add_field(
                name=f"{i}. {t['name']}",
                value=f"**{t['artist']['name']}**\n▶️ {plays:,}\n[Last.fm]({url})",
                inline=True,
            )
        embed.set_footer(text="Mred • Last.fm")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Błąd: `{e}`")


@bot.tree.command(name="tag", description="Top tracki z gatunku/tagu (np. rock, jazz, pop)")
async def slash_tag(interaction: discord.Interaction, gatunek: str):
    await interaction.response.defer()
    try:
        data   = await lfm("tag.getTopTracks", {"tag": gatunek, "limit": 8})
        tracks = data["tracks"]["track"]
        if not tracks:
            await interaction.followup.send(f"❌ Brak wyników dla tagu `{gatunek}`."); return

        embed = discord.Embed(title=f"🏷️ Top tracki — {gatunek}", color=MRED_COLOR)
        for t in tracks:
            url = t.get("url", "")
            embed.add_field(
                name=t["name"],
                value=f"**{t['artist']['name']}**\n[Last.fm]({url})",
                inline=True,
            )
        embed.set_footer(text="Mred • Last.fm")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Błąd: `{e}`")


@bot.tree.command(name="sync", description="Force sync (owner only)")
async def slash_sync(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Tylko właściciel.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    synced = await bot.tree.sync()
    if interaction.guild:
        await bot.tree.sync(guild=interaction.guild)
    await interaction.followup.send(f"✅ {len(synced)} komend", ephemeral=True)


@bot.tree.command(name="shutdown", description="Wyłącz Mred (owner only)")
async def slash_shutdown(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Nie masz uprawnień.", ephemeral=True); return
    await interaction.response.send_message("Wyłączam Mred...")
    await bot.close()

# ---------------------------------------------------------------------------
# Status rotation
# ---------------------------------------------------------------------------

_status_idx   = 0
_status_slots = ["Muzyka Last.fm | /search", "Top tracki | /topcharts", "Music Recurrent Editor & Dump"]

@tasks.loop(minutes=5)
async def rotate_status():
    global _status_idx
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening,
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
    print(f"[Mred] Logged in as {bot.user}")
    print(f"[Mred] Guilds: {len(bot.guilds)}")
    print(f"[Mred] Last.fm: {'enabled' if LASTFM_KEY else 'disabled (brak LASTFM_API_KEY)'}")
    try:
        synced = await bot.tree.sync()
        print(f"[Mred] Synced {len(synced)} commands")
        for guild in bot.guilds:
            await bot.tree.sync(guild=guild)
    except Exception as e:
        print(f"[Mred] Sync error: {e}")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening, name="Muzyka Last.fm | /search"
    ))
    rotate_status.start()

if __name__ == "__main__":
    bot.run(TOKEN)
