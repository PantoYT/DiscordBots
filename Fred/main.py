import discord
from discord.ext import commands, tasks
import aiohttp
import os
import pathlib
import socket
from dotenv import load_dotenv
from datetime import datetime, timedelta
import json
import asyncio
import pytz

# -------------------------------
# Single-instance guard: a second copy (e.g. a stray autostart entry) binds the
# same localhost port, fails, and exits instead of double-posting on one token.
# -------------------------------
_singleton = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    _singleton.bind(("127.0.0.1", 47921))
except OSError:
    print("[Fred] Another instance is already running — exiting.")
    raise SystemExit(0)

# -------------------------------
# Load environment
# -------------------------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
EPIC_API_KEY = os.getenv("EPIC_API_KEY")
EPIC_API_URL = "https://epic-games-store-free-games.p.rapidapi.com/free?country=PL"
HEADERS = {
    "x-rapidapi-key": EPIC_API_KEY,
    "x-rapidapi-host": "epic-games-store-free-games.p.rapidapi.com"
}

BASE_DIR = pathlib.Path(__file__).parent
POSTED_FILE = BASE_DIR / "posted_games.json"
CHANNEL_NAME = "free-games"
CET = pytz.timezone('Europe/Warsaw')
API_CALL_LOG = BASE_DIR / "api_calls.json"

# -------------------------------
# API call tracking
# -------------------------------
def get_api_call_count():
    try:
        with open(API_CALL_LOG, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("count", 0), data.get("month", "")
    except (FileNotFoundError, json.JSONDecodeError):
        return 0, ""

def increment_api_calls():
    now = datetime.now(CET)
    current_month = now.strftime("%Y-%m")
    count, last_month = get_api_call_count()
    if last_month != current_month:
        count = 0
    count += 1
    tmp = API_CALL_LOG.parent / (API_CALL_LOG.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"count": count, "month": current_month}, f)
    os.replace(tmp, API_CALL_LOG)
    return count

# -------------------------------
# Discord bot setup
# -------------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

pending_confirmations = {}

# -------------------------------
# Load or initialize posted games
# -------------------------------
try:
    with open(POSTED_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        posted_games = data.get("current", [])
        posted_upcoming = data.get("upcoming", [])
        last_daily_run = data.get("last_daily_run", None)
        message_ids = data.get("message_ids", {})  # { channel_id: { "current_header": id, "current_embeds": [...], ... } }
except (FileNotFoundError, json.JSONDecodeError):
    posted_games = []
    posted_upcoming = []
    last_daily_run = None
    message_ids = {}

def save_posted():
    current_titles = {g.get("title") for g in posted_games}
    clean_upcoming = [g for g in posted_upcoming if g.get("title") not in current_titles]
    tmp = POSTED_FILE.parent / (POSTED_FILE.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({
            "current": posted_games,
            "upcoming": clean_upcoming,
            "last_daily_run": last_daily_run,
            "message_ids": message_ids
        }, f, ensure_ascii=False, indent=2)
    os.replace(tmp, POSTED_FILE)

# -------------------------------
# Helper functions
# -------------------------------
def get_free_game_channels():
    channels = []
    for guild in bot.guilds:
        for channel in guild.text_channels:
            if channel.name == CHANNEL_NAME:
                channels.append(channel)
    return channels

async def fetch_games():
    try:
        call_count = increment_api_calls()
        print(f"API call #{call_count}/60")
        if call_count > 58:
            print("WARNING: Approaching API limit!")
        timeout = aiohttp.ClientTimeout(total=10)
        async with aiohttp.ClientSession(headers=HEADERS, timeout=timeout) as session:
            async with session.get(EPIC_API_URL) as resp:
                if resp.status != 200:
                    print(f"API error: {resp.status}")
                    return None
                return await resp.json()
    except Exception as e:
        print(f"Error fetching games: {e}")
        return None

def make_embeds(games, ctx_mention=None, upcoming=False, wide_image=False):
    embeds = []
    for g in games:
        title = g.get("title", "Unknown Game")
        desc = g.get("description", "No description")
        seller = g.get("seller", {}).get("name", "Unknown")
        slug = g.get("urlSlug")
        url = f"https://www.epicgames.com/store/p/{slug}" if slug else "No link"

        date_field = None
        if upcoming:
            date_field = g.get("effectiveDate", "Unknown start")
            if date_field:
                try:
                    dt = datetime.fromisoformat(date_field.replace("Z", "+00:00")) + timedelta(hours=1)
                    date_field = dt.strftime("%Y-%m-%d %H:%M")
                except:
                    pass
        else:
            promos = g.get("promotions", {}).get("promotionalOffers", [])
            if promos and promos[0].get("promotionalOffers"):
                end_raw = promos[0]["promotionalOffers"][0].get("endDate")
                if end_raw:
                    try:
                        dt = datetime.fromisoformat(end_raw.replace("Z", "+00:00")) + timedelta(hours=1)
                        date_field = dt.strftime("%Y-%m-%d %H:%M")
                    except:
                        pass

        image_url = None
        thumbnail_url = None
        for img in g.get("keyImages", []):
            img_type = img.get("type")
            if wide_image and img_type in ["DieselStoreFrontWide", "OfferImageWide"]:
                image_url = img.get("url")
                break
            elif img_type == "Thumbnail":
                thumbnail_url = img.get("url")
        if wide_image and not image_url:
            image_url = thumbnail_url

        embed = discord.Embed(title=title, url=url, description=desc, color=0x1E3A8A)
        embed.add_field(name="Seller", value=seller, inline=True)
        if date_field:
            label = "Available From" if upcoming else "Available Until"
            embed.add_field(name=label, value=date_field, inline=True)
        if wide_image and image_url:
            embed.set_image(url=image_url)
        elif thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)
        if ctx_mention:
            embed.set_footer(text=f"Checked by {ctx_mention}")
        embeds.append(embed)
    return embeds

def are_games_same(new_games, old_games):
    new_titles = {g.get("title") for g in new_games}
    old_titles = {g.get("title") for g in old_games}
    return new_titles == old_titles

# -------------------------------
# Core: send or edit messages in channel
# -------------------------------
async def update_channel_messages(channel, current_games, upcoming_games, ctx_mention=None):
    """
    Edits existing messages if possible, otherwise sends new ones.
    Deletes extra stale messages when game count decreases.
    """
    global message_ids

    channel_key = str(channel.id)
    ids = message_ids.get(channel_key, {})

    embeds_current = make_embeds(current_games, ctx_mention=ctx_mention, upcoming=False, wide_image=True)
    embeds_upcoming = make_embeds(upcoming_games, ctx_mention=ctx_mention, upcoming=True, wide_image=True)

    async def delete_message(msg_id):
        try:
            msg = await channel.fetch_message(msg_id)
            await msg.delete()
        except (discord.NotFound, discord.HTTPException):
            pass

    async def edit_or_send(existing_id, content=None, embed=None):
        if existing_id:
            try:
                msg = await channel.fetch_message(existing_id)
                await msg.edit(content=content, embed=embed)
                return msg.id
            except (discord.NotFound, discord.HTTPException):
                pass
        msg = await channel.send(content=content, embed=embed)
        return msg.id

    # --- Current games header ---
    ids["current_header"] = await edit_or_send(
        ids.get("current_header"),
        content="**🎮 Current Free Games:**"
    )

    # --- Current game embeds ---
    old_current_ids = ids.get("current_embeds", [])
    new_current_ids = []
    for i, embed in enumerate(embeds_current):
        existing_id = old_current_ids[i] if i < len(old_current_ids) else None
        msg_id = await edit_or_send(existing_id, embed=embed)
        new_current_ids.append(msg_id)
    # Delete extra stale embeds if game count shrank
    for old_id in old_current_ids[len(embeds_current):]:
        await delete_message(old_id)
    ids["current_embeds"] = new_current_ids

    # --- Upcoming games ---
    old_upcoming_ids = ids.get("upcoming_embeds", [])
    if embeds_upcoming:
        ids["upcoming_header"] = await edit_or_send(
            ids.get("upcoming_header"),
            content="**📅 Upcoming Free Games:**"
        )
        new_upcoming_ids = []
        for i, embed in enumerate(embeds_upcoming):
            existing_id = old_upcoming_ids[i] if i < len(old_upcoming_ids) else None
            msg_id = await edit_or_send(existing_id, embed=embed)
            new_upcoming_ids.append(msg_id)
        # Delete extra stale upcoming embeds
        for old_id in old_upcoming_ids[len(embeds_upcoming):]:
            await delete_message(old_id)
        ids["upcoming_embeds"] = new_upcoming_ids
    else:
        upcoming_header_id = ids.get("upcoming_header")
        if upcoming_header_id:
            try:
                msg = await channel.fetch_message(upcoming_header_id)
                await msg.edit(content="**📅 Upcoming Free Games:** *(none listed yet)*")
            except (discord.NotFound, discord.HTTPException):
                pass
        # Delete old upcoming embeds when none remain
        for old_id in old_upcoming_ids:
            await delete_message(old_id)
        ids["upcoming_embeds"] = []

    message_ids[channel_key] = ids

    # --- Reconcile: remove any leftover/untracked bot messages so the channel
    #     shows only the current live set. This catches pre-migration weekly
    #     posts, orphaned embeds from earlier bugs, and stray command replies —
    #     the same effect as /cleanup, but without deleting the messages we just
    #     edited (no flicker, no reposting). ---
    live_ids = set()
    if ids.get("current_header"):
        live_ids.add(ids["current_header"])
    live_ids.update(ids.get("current_embeds", []))
    if ids.get("upcoming_header"):
        live_ids.add(ids["upcoming_header"])
    live_ids.update(ids.get("upcoming_embeds", []))

    try:
        async for msg in channel.history(limit=500):
            if msg.author == bot.user and msg.id not in live_ids:
                try:
                    await msg.delete()
                    await asyncio.sleep(0.5)  # avoid rate limits
                except (discord.NotFound, discord.HTTPException):
                    pass
    except discord.HTTPException:
        pass

# -------------------------------
# Main check logic
# -------------------------------
async def run_check(ctx_mention=None, force=False, interaction_channel=None, is_auto_check=False):
    global last_daily_run, posted_games, posted_upcoming

    data = await fetch_games()
    if not data:
        print("Failed to fetch games")
        return False

    if interaction_channel:
        channels = [interaction_channel]
    else:
        channels = get_free_game_channels()

    if not channels:
        print("No channels found to post to")
        return False

    current_games = data.get("currentGames", [])
    next_games = data.get("nextGames", [])
    current_titles = {g.get("title") for g in current_games}

    games_changed = not are_games_same(current_games, posted_games)

    # Manual /check with no changes: don't repost, just offer /confirm.
    # The daily auto-check deliberately falls through even when the game list is
    # unchanged, so it can reconcile every channel and clear stale/old messages
    # (e.g. channels that were left behind when posted_games was updated elsewhere).
    if not games_changed and not force and not is_auto_check:
        if ctx_mention and interaction_channel:
            pending_confirmations[ctx_mention] = datetime.now(CET) + timedelta(minutes=1)
            await interaction_channel.send(
                f"{ctx_mention}, games are the same as last check. Use `/confirm` within 1 min to see them again."
            )
        return True

    posted_games = current_games.copy()
    # Use only what the API currently says is upcoming — don't accumulate historical entries
    posted_upcoming = [g for g in next_games if g.get("title") not in current_titles]

    if is_auto_check:
        last_daily_run = str(datetime.now(CET).date())

    save_posted()

    for channel in channels:
        try:
            await update_channel_messages(channel, current_games, posted_upcoming, ctx_mention=ctx_mention)
            save_posted()  # save updated message_ids after each channel
            print(f"Updated {channel.guild.name} - #{channel.name}")
        except Exception as e:
            print(f"Failed to update {channel.guild.name} - #{channel.name}: {e}")

    return True

# -------------------------------
# Events
# -------------------------------
@bot.event
async def on_ready():
    global last_daily_run
    now = datetime.now(CET)
    print(f"Bot logged in as {bot.user}")
    print(f"Connected to {len(bot.guilds)} guilds")

    detected_channels = []
    guilds_without_channel = []

    for guild in bot.guilds:
        channel_found = False
        for channel in guild.text_channels:
            if channel.name == CHANNEL_NAME:
                detected_channels.append(channel.id)
                channel_found = True
                print(f"Found channel '{CHANNEL_NAME}' in {guild.name} (ID: {channel.id})")
                break
        if not channel_found:
            guilds_without_channel.append(guild)
            print(f"WARNING: No '{CHANNEL_NAME}' channel in {guild.name}")

    for guild in guilds_without_channel:
        try:
            target_channel = guild.system_channel or (guild.text_channels[0] if guild.text_channels else None)
            if target_channel:
                embed = discord.Embed(
                    title="Fred Setup Required",
                    description=f"Fred needs a channel named `{CHANNEL_NAME}` to post Epic Games updates.",
                    color=0xFF6B6B
                )
                embed.add_field(name="Option 1: Auto-create", value="Use `/setup` and Fred will create the channel for you.", inline=False)
                embed.add_field(name="Option 2: Manual", value=f"Create a channel named `{CHANNEL_NAME}` yourself.", inline=False)
                await target_channel.send(embed=embed)
        except Exception as e:
            print(f"Could not send setup message to {guild.name}: {e}")

    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
    except Exception as e:
        print(f"Failed to sync commands: {e}")

    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching,
        name="Watching for free games | /commands"
    ))

    today_str = str(now.date())
    target_time = now.replace(hour=17, minute=1, second=0, microsecond=0)

    print(f"Current time: {now.strftime('%Y-%m-%d %H:%M:%S CET')}")
    print(f"Last daily run: {last_daily_run}")

    if now >= target_time and last_daily_run != today_str:
        print("Bot started after 17:01 and check hasn't run today - running now")
        result = await run_check(is_auto_check=True)
        print("Startup check completed" if result else "Startup check failed")
    else:
        print(f"No startup check needed (last run: {last_daily_run})")

    daily_check.start()

# -------------------------------
# Commands
# -------------------------------
@bot.tree.command(name="commands", description="Show all available commands")
async def commands_slash(interaction: discord.Interaction):
    embed = discord.Embed(title="Fred - Epic Games Tracker", description="Track free Epic Games automatically.", color=0x1E3A8A)
    embed.add_field(name="/current", value="Show current free games", inline=False)
    embed.add_field(name="/upcoming", value="Show upcoming free games", inline=False)
    embed.add_field(name="/next", value="Time until next check", inline=False)
    embed.add_field(name="/confirm", value="Show games again if unchanged", inline=False)
    embed.add_field(name="/setup", value="Create free-games channel", inline=False)
    embed.add_field(name="/check", value="Manual check (owner only)", inline=False)
    embed.add_field(name="/cleanup", value="Delete old messages and repost fresh (owner only)", inline=False)
    embed.add_field(name="/shutdown", value="Shut down bot (owner only)", inline=False)
    embed.set_footer(text="Daily check at 17:01 CET")
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="current", description="Show current free games")
async def current_slash(interaction: discord.Interaction):
    await interaction.response.defer()
    embeds = make_embeds(posted_games, ctx_mention=interaction.user.mention, upcoming=False, wide_image=True)
    if embeds:
        await interaction.followup.send("**🎮 Current Free Games:**")
        for e in embeds:
            await interaction.followup.send(embed=e)
    else:
        await interaction.followup.send("No current games cached yet.")

@bot.tree.command(name="upcoming", description="Show upcoming free games")
async def upcoming_slash(interaction: discord.Interaction):
    await interaction.response.defer()
    embeds = make_embeds(posted_upcoming, ctx_mention=interaction.user.mention, upcoming=True, wide_image=True)
    if embeds:
        await interaction.followup.send("**📅 Upcoming Free Games:**")
        for e in embeds:
            await interaction.followup.send(embed=e)
    else:
        await interaction.followup.send("No upcoming games cached yet.")

@bot.tree.command(name="next", description="Time until next automatic check")
async def next_slash(interaction: discord.Interaction):
    now = datetime.now(CET)
    target = now.replace(hour=17, minute=1, second=0, microsecond=0)
    if now >= target:
        target += timedelta(days=1)
    time_diff = target - now
    hours = int(time_diff.total_seconds() // 3600)
    minutes = int((time_diff.total_seconds() % 3600) // 60)
    embed = discord.Embed(title="Next Automatic Check", description=f"Next check: **{target.strftime('%H:%M')} CET**", color=0x1E3A8A)
    embed.add_field(name="Time Remaining", value=f"{hours}h {minutes}m", inline=True)
    embed.add_field(name="Date", value=target.strftime('%Y-%m-%d'), inline=True)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="check", description="Manual check for new games (owner only)")
async def check_slash(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Owner-only command.", ephemeral=True)
        return
    await interaction.response.send_message(f"Manual check triggered by {interaction.user.mention}")
    result = await run_check(ctx_mention=interaction.user.mention, force=False, interaction_channel=interaction.channel, is_auto_check=False)
    if not result:
        await interaction.followup.send("Failed to fetch games.")

@bot.tree.command(name="confirm", description="Show games again if unchanged")
async def confirm_slash(interaction: discord.Interaction):
    await interaction.response.defer()
    now = datetime.now(CET)
    expiry = pending_confirmations.get(interaction.user.mention)
    if expiry and now <= expiry:
        pending_confirmations.pop(interaction.user.mention)
        embeds = make_embeds(posted_games, ctx_mention=interaction.user.mention, upcoming=False, wide_image=True)
        if embeds:
            await interaction.followup.send("**🎮 Current Free Games:**")
            for e in embeds:
                await interaction.followup.send(embed=e)
        else:
            await interaction.followup.send("No current games to display.")
    else:
        await interaction.followup.send("No pending confirmation or it expired.")

@bot.tree.command(name="setup", description="Create free-games channel")
async def setup_slash(interaction: discord.Interaction):
    guild = interaction.guild
    if not guild:
        await interaction.response.send_message("Must be used in a server.", ephemeral=True)
        return
    for channel in guild.text_channels:
        if channel.name == CHANNEL_NAME:
            await interaction.response.send_message(f"Channel `{CHANNEL_NAME}` already exists.", ephemeral=True)
            return
    if not guild.me.guild_permissions.manage_channels:
        await interaction.response.send_message("Fred needs 'Manage Channels' permission.", ephemeral=True)
        return
    if not interaction.user.guild_permissions.manage_channels:
        await interaction.response.send_message("You need 'Manage Channels' permission.", ephemeral=True)
        return
    try:
        new_channel = await guild.create_text_channel(
            name=CHANNEL_NAME,
            topic="Free games from Epic Games Store - Updated daily by Fred"
        )
        embed = discord.Embed(title="Channel Created", description=f"Fred will post updates in {new_channel.mention}", color=0x4CAF50)
        embed.add_field(name="Daily Updates", value="Automatic check at 17:01 CET", inline=False)
        embed.add_field(name="Commands", value="Use `/commands` to see all commands", inline=False)
        await interaction.response.send_message(embed=embed)
        welcome_embed = discord.Embed(title="Welcome to Free Games", description="Daily Epic Games Store updates at 17:01 CET", color=0x1E3A8A)
        welcome_embed.add_field(name="Quick Commands", value="`/current` - Current games\n`/upcoming` - Upcoming games\n`/commands` - All commands", inline=False)
        await new_channel.send(embed=welcome_embed)
        print(f"Created channel '{CHANNEL_NAME}' in {guild.name}")
    except Exception as e:
        await interaction.response.send_message(f"Failed to create channel: {e}", ephemeral=True)

@bot.tree.command(name="cleanup", description="Delete all old bot messages and repost fresh (owner only)")
async def cleanup_slash(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Owner-only command.", ephemeral=True)
        return
    await interaction.response.defer(ephemeral=True)
    global message_ids
    channel = interaction.channel
    channel_key = str(channel.id)

    # Delete ALL bot messages in the channel (not just tracked ones)
    deleted = 0
    async for msg in channel.history(limit=500):
        if msg.author == bot.user:
            try:
                await msg.delete()
                deleted += 1
                await asyncio.sleep(0.5)  # avoid rate limits
            except (discord.NotFound, discord.HTTPException):
                pass

    # Reset tracked IDs for this channel
    message_ids[channel_key] = {}
    save_posted()

    await interaction.followup.send(f"Deleted {deleted} old messages. Running fresh check...", ephemeral=True)
    result = await run_check(ctx_mention=interaction.user.mention, force=True, interaction_channel=channel, is_auto_check=False)
    if not result:
        await interaction.followup.send("Failed to fetch games.", ephemeral=True)

@bot.tree.command(name="shutdown", description="Shut down bot (owner only)")
async def shutdown_slash(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("You don't have permission.", ephemeral=True)
        return
    await interaction.response.send_message("Shutting down...")
    await bot.close()

# -------------------------------
# Daily scheduled task at 17:01 CET
# -------------------------------
@tasks.loop(minutes=15)
async def daily_check():
    global last_daily_run
    now = datetime.now(CET)
    today_str = str(now.date())
    target_time = now.replace(hour=17, minute=1, second=0, microsecond=0)
    if now >= target_time and last_daily_run != today_str:
        print(f"Running daily check at {now.strftime('%Y-%m-%d %H:%M:%S')}")
        result = await run_check(is_auto_check=True)
        if result:
            print(f"Daily check done. Next at 17:01 tomorrow.")
        else:
            print("Daily check failed, will retry in 15 minutes")

@daily_check.before_loop
async def before_daily_check():
    await bot.wait_until_ready()
    print("Daily check task started - will run after 17:01 CET every day")

# -------------------------------
# Run the bot
# -------------------------------
if __name__ == "__main__":
    bot.run(TOKEN)