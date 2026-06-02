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

WARNS_FILE = pathlib.Path(__file__).parent / "warnings.json"
ARED_COLOR = 0xDC2626

intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)

# ---------------------------------------------------------------------------
# Storage — ostrzeżenia
# ---------------------------------------------------------------------------

def load_warns() -> dict:
    try:
        with open(WARNS_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_warns(data: dict):
    with open(WARNS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def get_user_warns(warns: dict, guild_id: int, user_id: int) -> list:
    return warns.get(str(guild_id), {}).get(str(user_id), [])

def add_warn(warns: dict, guild_id: int, user_id: int, reason: str, moderator: str):
    g = str(guild_id)
    u = str(user_id)
    warns.setdefault(g, {}).setdefault(u, [])
    warns[g][u].append({
        "reason":     reason,
        "moderator":  moderator,
        "date":       datetime.now(timezone.utc).strftime("%d/%m/%Y %H:%M"),
    })

# ---------------------------------------------------------------------------
# Duration parser — "10m", "1h", "7d"
# ---------------------------------------------------------------------------

DURATION_RE = re.compile(r'^(\d+)(s|m|h|d)$')

def parse_duration(s: str) -> timedelta | None:
    m = DURATION_RE.match(s.strip().lower())
    if not m:
        return None
    n = int(m[1])
    unit = m[2]
    return {"s": timedelta(seconds=n), "m": timedelta(minutes=n),
            "h": timedelta(hours=n),   "d": timedelta(days=n)}[unit]

# ---------------------------------------------------------------------------
# Permission checks
# ---------------------------------------------------------------------------

def is_mod(interaction: discord.Interaction) -> bool:
    if interaction.user.id == OWNER_ID:
        return True
    if not interaction.guild:
        return False
    perms = interaction.user.guild_permissions
    return perms.kick_members or perms.ban_members or perms.manage_messages

async def check_mod(interaction: discord.Interaction) -> bool:
    if not is_mod(interaction):
        await interaction.response.send_message("❌ Potrzebujesz uprawnień moderatora.", ephemeral=True)
        return False
    return True

# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

@bot.tree.command(name="commands", description="Lista komend Ared")
async def slash_commands(interaction: discord.Interaction):
    embed = discord.Embed(title="Ared — Admin Bot", description="Moderacja i zarządzanie serwerem.", color=ARED_COLOR)
    embed.add_field(name="/kick <user> [powód]",         value="Wyrzuć użytkownika",            inline=False)
    embed.add_field(name="/ban <user> [powód]",          value="Zbanuj użytkownika",             inline=False)
    embed.add_field(name="/unban <user_id>",             value="Odbanuj użytkownika",            inline=False)
    embed.add_field(name="/mute <user> <czas> [powód]",  value="Wycisz (timeout): 10m, 1h, 7d", inline=False)
    embed.add_field(name="/unmute <user>",               value="Zdejmij wyciszenie",             inline=False)
    embed.add_field(name="/clear <ilość>",               value="Usuń wiadomości (1–100)",        inline=False)
    embed.add_field(name="/warn <user> <powód>",         value="Ostrzeż użytkownika",            inline=False)
    embed.add_field(name="/warnings <user>",             value="Pokaż ostrzeżenia użytkownika",  inline=False)
    embed.add_field(name="/clearwarns <user>",           value="Wyczyść ostrzeżenia (mod only)", inline=False)
    embed.add_field(name="/slowmode <sekundy>",          value="Ustaw slowmode (0 = wyłącz)",    inline=False)
    embed.add_field(name="/lock",                        value="Zablokuj kanał",                 inline=False)
    embed.add_field(name="/unlock",                      value="Odblokuj kanał",                 inline=False)
    embed.set_footer(text="Ared • Admin Recurrent Editor & Dump")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="kick", description="Wyrzuć użytkownika z serwera")
async def slash_kick(interaction: discord.Interaction, user: discord.Member, powod: str = "Brak powodu"):
    if not await check_mod(interaction): return
    if not interaction.guild.me.guild_permissions.kick_members:
        await interaction.response.send_message("❌ Nie mam uprawnień do kickowania.", ephemeral=True); return
    try:
        await user.kick(reason=f"{powod} (przez {interaction.user})")
        embed = discord.Embed(title="👢 Kick", description=f"**{user}** został wyrzucony.\nPowód: {powod}", color=ARED_COLOR)
        embed.set_footer(text=f"Mod: {interaction.user} • Ared")
        await interaction.response.send_message(embed=embed)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Nie mogę wyrzucić tego użytkownika.", ephemeral=True)


@bot.tree.command(name="ban", description="Zbanuj użytkownika")
async def slash_ban(interaction: discord.Interaction, user: discord.Member, powod: str = "Brak powodu"):
    if not await check_mod(interaction): return
    if not interaction.guild.me.guild_permissions.ban_members:
        await interaction.response.send_message("❌ Nie mam uprawnień do banowania.", ephemeral=True); return
    try:
        await user.ban(reason=f"{powod} (przez {interaction.user})", delete_message_days=0)
        embed = discord.Embed(title="🔨 Ban", description=f"**{user}** został zbanowany.\nPowód: {powod}", color=ARED_COLOR)
        embed.set_footer(text=f"Mod: {interaction.user} • Ared")
        await interaction.response.send_message(embed=embed)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Nie mogę zbanować tego użytkownika.", ephemeral=True)


@bot.tree.command(name="unban", description="Odbanuj użytkownika po ID")
async def slash_unban(interaction: discord.Interaction, user_id: str):
    if not await check_mod(interaction): return
    if not interaction.guild.me.guild_permissions.ban_members:
        await interaction.response.send_message("❌ Nie mam uprawnień.", ephemeral=True); return
    try:
        user = await bot.fetch_user(int(user_id))
        await interaction.guild.unban(user)
        await interaction.response.send_message(f"✅ Odbanowano **{user}**.")
    except (ValueError, discord.NotFound):
        await interaction.response.send_message("❌ Nie znaleziono użytkownika.", ephemeral=True)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Nie mam uprawnień.", ephemeral=True)


@bot.tree.command(name="mute", description="Wycisz użytkownika (timeout): 10m, 1h, 7d")
async def slash_mute(interaction: discord.Interaction, user: discord.Member, czas: str, powod: str = "Brak powodu"):
    if not await check_mod(interaction): return
    delta = parse_duration(czas)
    if not delta:
        await interaction.response.send_message("❌ Zły format czasu. Użyj np. `10m`, `1h`, `7d`.", ephemeral=True); return
    if delta.total_seconds() > 60 * 60 * 24 * 28:
        await interaction.response.send_message("❌ Maksymalny timeout to 28 dni.", ephemeral=True); return
    try:
        await user.timeout(delta, reason=f"{powod} (przez {interaction.user})")
        embed = discord.Embed(title="🔇 Mute", description=f"**{user}** wyciszony na `{czas}`.\nPowód: {powod}", color=ARED_COLOR)
        embed.set_footer(text=f"Mod: {interaction.user} • Ared")
        await interaction.response.send_message(embed=embed)
    except discord.Forbidden:
        await interaction.response.send_message("❌ Nie mogę wyciszyć tego użytkownika.", ephemeral=True)


@bot.tree.command(name="unmute", description="Zdejmij wyciszenie użytkownika")
async def slash_unmute(interaction: discord.Interaction, user: discord.Member):
    if not await check_mod(interaction): return
    try:
        await user.timeout(None)
        await interaction.response.send_message(f"✅ Wyciszenie **{user}** zdjęte.")
    except discord.Forbidden:
        await interaction.response.send_message("❌ Nie mam uprawnień.", ephemeral=True)


@bot.tree.command(name="clear", description="Usuń wiadomości z kanału (1–100)")
async def slash_clear(interaction: discord.Interaction, ilosc: int):
    if not await check_mod(interaction): return
    if not (1 <= ilosc <= 100):
        await interaction.response.send_message("❌ Podaj liczbę 1–100.", ephemeral=True); return
    if not interaction.guild.me.guild_permissions.manage_messages:
        await interaction.response.send_message("❌ Nie mam uprawnień.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    deleted = await interaction.channel.purge(limit=ilosc)
    await interaction.followup.send(f"✅ Usunięto {len(deleted)} wiadomości.", ephemeral=True)


@bot.tree.command(name="warn", description="Ostrzeż użytkownika")
async def slash_warn(interaction: discord.Interaction, user: discord.Member, powod: str):
    if not await check_mod(interaction): return
    warns = load_warns()
    add_warn(warns, interaction.guild.id, user.id, powod, str(interaction.user))
    save_warns(warns)
    count = len(get_user_warns(warns, interaction.guild.id, user.id))
    embed = discord.Embed(
        title="⚠️ Ostrzeżenie",
        description=f"**{user}** otrzymał ostrzeżenie #{count}.\nPowód: {powod}",
        color=ARED_COLOR,
    )
    embed.set_footer(text=f"Mod: {interaction.user} • Ared")
    await interaction.response.send_message(embed=embed)
    try:
        await user.send(embed=discord.Embed(
            title=f"⚠️ Ostrzeżenie na {interaction.guild.name}",
            description=f"Powód: {powod}\nOstrzeżenie #{count}",
            color=ARED_COLOR,
        ))
    except Exception:
        pass


@bot.tree.command(name="warnings", description="Pokaż ostrzeżenia użytkownika")
async def slash_warnings(interaction: discord.Interaction, user: discord.Member):
    warns = load_warns()
    user_warns = get_user_warns(warns, interaction.guild.id, user.id)
    if not user_warns:
        await interaction.response.send_message(f"**{user}** nie ma ostrzeżeń. ✅", ephemeral=True); return
    embed = discord.Embed(title=f"⚠️ Ostrzeżenia — {user}", color=ARED_COLOR)
    for i, w in enumerate(user_warns, 1):
        embed.add_field(name=f"#{i} — {w['date']}", value=f"{w['reason']}\nMod: {w['moderator']}", inline=False)
    embed.set_footer(text=f"Łącznie: {len(user_warns)} • Ared")
    await interaction.response.send_message(embed=embed, ephemeral=True)


@bot.tree.command(name="clearwarns", description="Wyczyść ostrzeżenia użytkownika (mod only)")
async def slash_clearwarns(interaction: discord.Interaction, user: discord.Member):
    if not await check_mod(interaction): return
    warns = load_warns()
    g, u  = str(interaction.guild.id), str(user.id)
    count = len(warns.get(g, {}).get(u, []))
    if count == 0:
        await interaction.response.send_message(f"**{user}** nie ma ostrzeżeń.", ephemeral=True); return
    warns.get(g, {}).pop(u, None)
    save_warns(warns)
    await interaction.response.send_message(f"✅ Wyczyszczono {count} ostrzeżeń **{user}**.")


@bot.tree.command(name="slowmode", description="Ustaw slowmode na kanale (0 = wyłącz, max 21600s)")
async def slash_slowmode(interaction: discord.Interaction, sekundy: int):
    if not await check_mod(interaction): return
    if not (0 <= sekundy <= 21600):
        await interaction.response.send_message("❌ Podaj wartość 0–21600.", ephemeral=True); return
    await interaction.channel.edit(slowmode_delay=sekundy)
    msg = f"✅ Slowmode {'wyłączony' if sekundy == 0 else f'ustawiony na {sekundy}s'}."
    await interaction.response.send_message(msg)


@bot.tree.command(name="lock", description="Zablokuj kanał (usuń prawo do pisania @everyone)")
async def slash_lock(interaction: discord.Interaction):
    if not await check_mod(interaction): return
    overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = False
    await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    await interaction.response.send_message("🔒 Kanał zablokowany.")


@bot.tree.command(name="unlock", description="Odblokuj kanał")
async def slash_unlock(interaction: discord.Interaction):
    if not await check_mod(interaction): return
    overwrite = interaction.channel.overwrites_for(interaction.guild.default_role)
    overwrite.send_messages = None
    await interaction.channel.set_permissions(interaction.guild.default_role, overwrite=overwrite)
    await interaction.response.send_message("🔓 Kanał odblokowany.")


@bot.tree.command(name="sync", description="Force sync (owner only)")
async def slash_sync(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Tylko właściciel.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    synced = await bot.tree.sync()
    if interaction.guild:
        await bot.tree.sync(guild=interaction.guild)
    await interaction.followup.send(f"✅ {len(synced)} komend", ephemeral=True)


@bot.tree.command(name="shutdown", description="Wyłącz Ared (owner only)")
async def slash_shutdown(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Nie masz uprawnień.", ephemeral=True); return
    await interaction.response.send_message("Wyłączam Ared...")
    await bot.close()

# ---------------------------------------------------------------------------
# Status rotation
# ---------------------------------------------------------------------------

_status_idx   = 0
_status_slots = ["Moderacja | /commands", "Ostrzeżenia | /warn", "Admin Recurrent Editor & Dump"]

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
    print(f"[Ared] Logged in as {bot.user}")
    print(f"[Ared] Guilds: {len(bot.guilds)}")
    try:
        synced = await bot.tree.sync()
        print(f"[Ared] Synced {len(synced)} commands")
        for guild in bot.guilds:
            await bot.tree.sync(guild=guild)
    except Exception as e:
        print(f"[Ared] Sync error: {e}")
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="Moderacja | /commands"
    ))
    rotate_status.start()

if __name__ == "__main__":
    bot.run(TOKEN)
