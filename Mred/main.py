import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv
import os
import httpx
import base64
from datetime import datetime, timezone

load_dotenv()

TOKEN          = os.getenv("DISCORD_TOKEN")
OWNER_ID       = int(os.getenv("OWNER_ID"))
SPOTIFY_ID     = os.getenv("SPOTIFY_CLIENT_ID", "")
SPOTIFY_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")

MRED_COLOR = 0x1DB954  # Spotify green

intents = discord.Intents.default()
bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)

# ---------------------------------------------------------------------------
# Spotify token (Client Credentials — bez user auth)
# ---------------------------------------------------------------------------

_spotify_token:   str | None = None
_token_expires_at: float     = 0.0

async def get_spotify_token() -> str | None:
    global _spotify_token, _token_expires_at
    if not SPOTIFY_ID or not SPOTIFY_SECRET:
        return None
    now = datetime.now(timezone.utc).timestamp()
    if _spotify_token and now < _token_expires_at - 30:
        return _spotify_token
    creds = base64.b64encode(f"{SPOTIFY_ID}:{SPOTIFY_SECRET}".encode()).decode()
    async with httpx.AsyncClient() as client:
        r = await client.post(
            "https://accounts.spotify.com/api/token",
            headers={"Authorization": f"Basic {creds}"},
            data={"grant_type": "client_credentials"},
        )
        r.raise_for_status()
        data = r.json()
        _spotify_token    = data["access_token"]
        _token_expires_at = now + data["expires_in"]
    return _spotify_token


async def spotify_get(path: str, params: dict = None) -> dict | None:
    token = await get_spotify_token()
    if not token:
        return None
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"https://api.spotify.com/v1/{path}",
            headers={"Authorization": f"Bearer {token}"},
            params=params or {},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

# ---------------------------------------------------------------------------
# Embed helpers
# ---------------------------------------------------------------------------

def track_embed(track: dict, title_prefix: str = "") -> discord.Embed:
    name    = track["name"]
    artists = ", ".join(a["name"] for a in track["artists"])
    album   = track["album"]["name"]
    url     = track["external_urls"].get("spotify", "")
    image   = track["album"]["images"][0]["url"] if track["album"]["images"] else None
    dur_ms  = track["duration_ms"]
    dur     = f"{dur_ms//60000}:{(dur_ms%60000)//1000:02d}"

    embed = discord.Embed(title=f"{title_prefix}{name}", url=url, color=MRED_COLOR)
    embed.add_field(name="Artysta", value=artists, inline=True)
    embed.add_field(name="Album",   value=album,   inline=True)
    embed.add_field(name="Czas",    value=dur,     inline=True)
    if image:
        embed.set_thumbnail(url=image)
    embed.set_footer(text="Mred • Spotify")
    return embed


def artist_embed(artist: dict) -> discord.Embed:
    name       = artist["name"]
    url        = artist["external_urls"].get("spotify", "")
    followers  = artist.get("followers", {}).get("total", 0)
    genres     = ", ".join(artist.get("genres", [])[:4]) or "—"
    popularity = artist.get("popularity", 0)
    image      = artist["images"][0]["url"] if artist.get("images") else None

    embed = discord.Embed(title=name, url=url, color=MRED_COLOR)
    embed.add_field(name="Followersów", value=f"{followers:,}", inline=True)
    embed.add_field(name="Popularność", value=f"{popularity}/100",  inline=True)
    embed.add_field(name="Gatunki",     value=genres,               inline=False)
    if image:
        embed.set_thumbnail(url=image)
    embed.set_footer(text="Mred • Spotify")
    return embed

# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

@bot.tree.command(name="commands", description="Lista komend Mred")
async def slash_commands(interaction: discord.Interaction):
    embed = discord.Embed(title="Mred — Music Bot", description="Eksploracja muzyki przez Spotify API.", color=MRED_COLOR)
    embed.add_field(name="/search <zapytanie>",      value="Szukaj utworu na Spotify",              inline=False)
    embed.add_field(name="/artist <nazwa>",          value="Info o artyście + top tracki",          inline=False)
    embed.add_field(name="/album <nazwa> [artysta]", value="Info o albumie",                        inline=False)
    embed.add_field(name="/recommend <gatunek>",     value="Polecane tracki z gatunku",             inline=False)
    embed.add_field(name="/genres",                  value="Lista dostępnych gatunków Spotify",     inline=False)
    embed.add_field(name="/new",                     value="Nowe wydania w Polsce",                 inline=False)
    embed.set_footer(text="Mred • Music Recurrent Editor & Dump • Spotify API")
    await interaction.response.send_message(embed=embed)

    if not SPOTIFY_ID:
        await interaction.followup.send("⚠️ Brak `SPOTIFY_CLIENT_ID` w `.env` — komendy muzyczne nie działają.", ephemeral=True)


@bot.tree.command(name="search", description="Szukaj utworu na Spotify")
async def slash_search(interaction: discord.Interaction, zapytanie: str):
    await interaction.response.defer()
    try:
        data = await spotify_get("search", {"q": zapytanie, "type": "track", "limit": 5, "market": "PL"})
        tracks = data["tracks"]["items"]
        if not tracks:
            await interaction.followup.send("❌ Brak wyników."); return

        embed = discord.Embed(title=f"🔍 Wyniki: {zapytanie}", color=MRED_COLOR)
        for i, t in enumerate(tracks, 1):
            artists = ", ".join(a["name"] for a in t["artists"])
            url     = t["external_urls"].get("spotify", "")
            dur_ms  = t["duration_ms"]
            dur     = f"{dur_ms//60000}:{(dur_ms%60000)//1000:02d}"
            embed.add_field(
                name=f"{i}. {t['name']}",
                value=f"{artists} · {t['album']['name']} · {dur}\n[Otwórz Spotify]({url})",
                inline=False,
            )
        image = tracks[0]["album"]["images"][0]["url"] if tracks[0]["album"]["images"] else None
        if image:
            embed.set_thumbnail(url=image)
        embed.set_footer(text="Mred • Spotify")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Błąd Spotify: `{e}`")


@bot.tree.command(name="artist", description="Info o artyście i jego top tracki")
async def slash_artist(interaction: discord.Interaction, nazwa: str):
    await interaction.response.defer()
    try:
        # Search for artist
        data    = await spotify_get("search", {"q": nazwa, "type": "artist", "limit": 1, "market": "PL"})
        artists = data["artists"]["items"]
        if not artists:
            await interaction.followup.send("❌ Nie znaleziono artysty."); return

        artist   = artists[0]
        artist_id = artist["id"]
        top_data  = await spotify_get(f"artists/{artist_id}/top-tracks", {"market": "PL"})
        top       = top_data["tracks"][:5]

        embed = artist_embed(artist)
        if top:
            tracks_str = "\n".join(
                f"`{i}.` [{t['name']}]({t['external_urls'].get('spotify','')})"
                for i, t in enumerate(top, 1)
            )
            embed.add_field(name="🎵 Top tracki", value=tracks_str, inline=False)
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Błąd Spotify: `{e}`")


@bot.tree.command(name="album", description="Info o albumie")
async def slash_album(interaction: discord.Interaction, nazwa: str, artysta: str = None):
    await interaction.response.defer()
    try:
        query = f"{nazwa} {artysta}" if artysta else nazwa
        data  = await spotify_get("search", {"q": query, "type": "album", "limit": 1, "market": "PL"})
        albums = data["albums"]["items"]
        if not albums:
            await interaction.followup.send("❌ Nie znaleziono albumu."); return

        album    = albums[0]
        album_id = album["id"]
        details  = await spotify_get(f"albums/{album_id}", {"market": "PL"})

        name     = details["name"]
        artists  = ", ".join(a["name"] for a in details["artists"])
        released = details["release_date"]
        tracks   = details["total_tracks"]
        url      = details["external_urls"].get("spotify", "")
        image    = details["images"][0]["url"] if details["images"] else None

        embed = discord.Embed(title=name, url=url, color=MRED_COLOR)
        embed.add_field(name="Artysta",   value=artists,  inline=True)
        embed.add_field(name="Wydany",    value=released, inline=True)
        embed.add_field(name="Tracki",    value=str(tracks), inline=True)

        top_tracks = details["tracks"]["items"][:5]
        if top_tracks:
            tlist = "\n".join(
                f"`{t['track_number']}.` {t['name']} — {t['duration_ms']//60000}:{(t['duration_ms']%60000)//1000:02d}"
                for t in top_tracks
            )
            embed.add_field(name="Tracklista (pierwsze 5)", value=tlist, inline=False)

        if image:
            embed.set_thumbnail(url=image)
        embed.set_footer(text="Mred • Spotify")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Błąd Spotify: `{e}`")


@bot.tree.command(name="recommend", description="Polecane tracki z wybranego gatunku")
async def slash_recommend(interaction: discord.Interaction, gatunek: str):
    await interaction.response.defer()
    try:
        data   = await spotify_get("recommendations", {
            "seed_genres": gatunek.lower().replace(" ", "-"),
            "limit":       8,
            "market":      "PL",
        })
        tracks = data.get("tracks", [])
        if not tracks:
            await interaction.followup.send(f"❌ Brak rekomendacji dla gatunku `{gatunek}`. Sprawdź `/genres`."); return

        embed = discord.Embed(title=f"🎲 Rekomendacje — {gatunek}", color=MRED_COLOR)
        for t in tracks:
            artists = ", ".join(a["name"] for a in t["artists"])
            url     = t["external_urls"].get("spotify", "")
            embed.add_field(
                name=t["name"],
                value=f"{artists}\n[Spotify]({url})",
                inline=True,
            )
        image = tracks[0]["album"]["images"][0]["url"] if tracks[0]["album"]["images"] else None
        if image:
            embed.set_thumbnail(url=image)
        embed.set_footer(text="Mred • Spotify Recommendations")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Błąd: `{e}`\nSprawdź `/genres` po listę dostępnych gatunków.")


@bot.tree.command(name="genres", description="Lista dostępnych gatunków Spotify dla /recommend")
async def slash_genres(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        data   = await spotify_get("recommendations/available-genre-seeds")
        genres = data.get("genres", [])
        chunks = [genres[i:i+30] for i in range(0, min(len(genres), 90), 30)]
        embed  = discord.Embed(title="🎵 Gatunki Spotify", color=MRED_COLOR)
        for i, chunk in enumerate(chunks):
            embed.add_field(name=f"Strona {i+1}", value=", ".join(f"`{g}`" for g in chunk), inline=False)
        embed.set_footer(text="Użyj nazwy gatunku w /recommend • Mred")
        await interaction.followup.send(embed=embed)
    except Exception as e:
        await interaction.followup.send(f"❌ Błąd: `{e}`")


@bot.tree.command(name="new", description="Nowe wydania albumów w Polsce")
async def slash_new(interaction: discord.Interaction):
    await interaction.response.defer()
    try:
        data   = await spotify_get("browse/new-releases", {"country": "PL", "limit": 8})
        albums = data["albums"]["items"]
        embed  = discord.Embed(title="🆕 Nowe wydania — Polska", color=MRED_COLOR)
        for a in albums:
            artists = ", ".join(ar["name"] for ar in a["artists"])
            url     = a["external_urls"].get("spotify", "")
            embed.add_field(
                name=a["name"],
                value=f"{artists} · {a['release_date']}\n[Spotify]({url})",
                inline=True,
            )
        image = albums[0]["images"][0]["url"] if albums and albums[0]["images"] else None
        if image:
            embed.set_thumbnail(url=image)
        embed.set_footer(text="Mred • Spotify")
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
_status_slots = ["Muzyka Spotify | /search", "Rekomendacje | /recommend", "Music Recurrent Editor & Dump"]

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
    print(f"[Mred] Spotify: {'enabled' if SPOTIFY_ID else 'disabled (brak SPOTIFY_CLIENT_ID)'}")
    try:
        synced = await bot.tree.sync()
        print(f"[Mred] Synced {len(synced)} commands")
        for guild in bot.guilds:
            await bot.tree.sync(guild=guild)
    except Exception as e:
        print(f"[Mred] Sync error: {e}")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.listening, name="Muzyka Spotify | /search"
    ))
    rotate_status.start()

if __name__ == "__main__":
    bot.run(TOKEN)
