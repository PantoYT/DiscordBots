import discord
from discord.ext import commands
from dotenv import load_dotenv
import json
import os
from datetime import datetime
import pathlib
import hashlib
import re
import asyncio
import random
import socket

# -------------------------------
# Single-instance guard: a second copy (e.g. a stray autostart entry) binds the
# same localhost port, fails, and exits instead of double-posting on one token.
# -------------------------------
_singleton = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    _singleton.bind(("127.0.0.1", 47922))
except OSError:
    print("[Qred] Druga instancja juz dziala — wychodze.")
    raise SystemExit(0)

# -------------------------------
# Load environment
# -------------------------------
load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
QUOTE_FILE = pathlib.Path(__file__).parent / "quotes.json"

# -------------------------------
# Discord bot setup
# -------------------------------
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)

# Rave mode state
rave_mode_active = False
rave_task = None
annoy_user_id = None

# -------------------------------
# Helper functions
# -------------------------------
def load_quotes():
    if QUOTE_FILE.exists():
        try:
            with open(QUOTE_FILE, "r", encoding="utf-8") as f:
                quotes = json.load(f)
                needs_save = False
                next_id = max([q.get("id", 0) for q in quotes], default=0) + 1
                for q in quotes:
                    if "id" not in q:
                        q["id"] = next_id
                        next_id += 1
                        needs_save = True
                if needs_save:
                    save_quotes(quotes)
                return quotes
        except json.JSONDecodeError as e:
            print(f"Error loading quotes: {e}")
            return []
    return []

def save_quotes(quotes):
    try:
        tmp = QUOTE_FILE.parent / (QUOTE_FILE.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(quotes, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, QUOTE_FILE)
    except Exception as e:
        print(f"Error saving quotes: {e}")

def get_next_id(quotes):
    if not quotes:
        return 1
    return max([q.get("id", 0) for q in quotes]) + 1

def find_quote_by_id(quotes, quote_id):
    for q in quotes:
        if q.get("id") == quote_id:
            return q
    return None

def quote_exists(quotes, text, author):
    t = text.strip()
    a = author.strip().lower()
    return any(
        q.get("text", "").strip() == t and q.get("author", "").strip().lower() == a
        for q in quotes
    )

def format_author_name(name):
    return name.strip()

def categorize_author(count):
    if count <= 5:
        return "Początkujący filozof"
    elif count <= 15:
        return "Sokrates"
    elif count <= 30:
        return "Platon"
    elif count <= 50:
        return "Arystoteles"
    elif count <= 75:
        return "Konfucjusz"
    elif count <= 100:
        return "Seneka"
    else:
        return "Marcus Aurelius"

def clean_quote_text(text):
    """Remove Discord mentions and clean text for status"""
    # Remove user mentions <@123456789> or <@!123456789>
    text = re.sub(r'<@!?\d+>', '', text)
    # Remove role mentions <@&123456789>
    text = re.sub(r'<@&\d+>', '', text)
    # Remove channel mentions <#123456789>
    text = re.sub(r'<#\d+>', '', text)
    # Clean up extra spaces
    text = ' '.join(text.split())
    return text.strip()

def get_daily_quote_index(quotes):
    if not quotes:
        return 0
    
    today = datetime.now().strftime("%Y-%m-%d")
    hash_obj = hashlib.md5(today.encode())
    hash_int = int(hash_obj.hexdigest(), 16)
    
    return hash_int % len(quotes)

def can_modify_quote(interaction, quote, owner_id):
    """Check if user can modify this quote"""
    if interaction.user.id == owner_id:
        return True
    
    author_names = [a.strip() for a in quote["author"].split(",")]
    return interaction.user.name in author_names

def get_valid_status_quotes(quotes):
    """Filter quotes that fit in status (max 128 chars after cleaning)"""
    valid = []
    for q in quotes:
        cleaned_text = clean_quote_text(q["text"])
        status_text = f'"{cleaned_text}" - {q["author"]}'
        if len(status_text) <= 128:
            valid.append(q)
    return valid

async def set_status_to_quote(quote):
    """Set bot status to a specific quote"""
    cleaned_text = clean_quote_text(quote["text"])
    status_text = f'"{cleaned_text}" - {quote["author"]}'
    
    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=status_text
        )
    )
    print(f"Status set to: {status_text}")

def format_rave_message(quote):
    """Format quote message for rave mode (simple text, no embeds)"""
    return f'**RAVE MODE** 🎉\n"{quote["text"]}" - {quote["author"]} (#{quote["id"]})'

async def rave_mode_loop(channel_to_spam=None):
    """Main rave mode loop - cycles quotes every 5 seconds"""
    global rave_mode_active, annoy_user_id
    
    quotes = load_quotes()
    valid_quotes = get_valid_status_quotes(quotes)
    
    if not valid_quotes:
        valid_quotes = quotes  # Fallback to all quotes
    
    index = 0
    
    while rave_mode_active:
        try:
            quote = valid_quotes[index % len(valid_quotes)]
            
            # Update status
            await set_status_to_quote(quote)
            
            # Send message to channel if provided
            if channel_to_spam:
                message_text = format_rave_message(quote)
                
                # Add ping if set
                if annoy_user_id == "everyone":
                    message_text = f"@everyone\n{message_text}"
                elif annoy_user_id:
                    message_text = f"<@{annoy_user_id}>\n{message_text}"
                
                await channel_to_spam.send(message_text)
            
            index += 1
            await asyncio.sleep(5)
            
        except Exception as e:
            print(f"Rave mode error: {e}")
            await asyncio.sleep(5)

# -------------------------------
# Events
# -------------------------------
@bot.event
async def on_ready():
    print(f"Bot logged in as {bot.user}")
    
    # List all registered commands BEFORE sync
    print(f"Commands registered: {[cmd.name for cmd in bot.tree.get_commands()]}")
    
    try:
        synced = await bot.tree.sync()
        print(f"Synced {len(synced)} slash commands")
        print(f"Command names: {[cmd.name for cmd in synced]}")
    except Exception as e:
        print(f"Failed to sync commands: {e}")
    
    quotes = load_quotes()
    if quotes:
        valid_quotes = get_valid_status_quotes(quotes)
        
        if valid_quotes:
            index = get_daily_quote_index(valid_quotes)
            daily_quote = valid_quotes[index]
            await set_status_to_quote(daily_quote)
        else:
            await bot.change_presence(
                activity=discord.Activity(
                    type=discord.ActivityType.watching,
                    name="Tracking your quotes | /commands"
                )
            )
    else:
        await bot.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Tracking your quotes | /commands"
            )
        )

# -------------------------------
# Commands
# -------------------------------
@bot.tree.command(name="commands", description="Show all available commands")
async def commands_slash(interaction: discord.Interaction):
    embed = discord.Embed(title="Qred - Quote Tracker", description="Track your best Quotes.", color=0x1E3A8A)
    embed.add_field(name="/random", value="Display a random quote", inline=False)
    embed.add_field(name="/daily", value="Show today's quote", inline=False)
    embed.add_field(name="/add", value="Add quote(s) from recent messages", inline=False)
    embed.add_field(name="/create", value="Add a new quote manually", inline=False)
    embed.add_field(name="/mine", value="Show all your quotes", inline=False)
    embed.add_field(name="/edit", value="Edit one of your quotes", inline=False)
    embed.add_field(name="/delete", value="Delete one of your quotes", inline=False)
    embed.add_field(name="/cycle", value="Cycle to next status quote (owner only)", inline=False)
    embed.add_field(name="/rave", value="🎉 Toggle RAVE MODE - quotes every 5s! (owner only)", inline=False)
    embed.add_field(name="/all", value="Show all quotes (owner only)", inline=False)
    embed.add_field(name="/shutdown", value="Shut down the bot (owner only)", inline=False)
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="add", description="Add quote(s) from recent messages")
async def add_slash(
    interaction: discord.Interaction,
    messages: int = 1,
    author: str = None,
    skip: int = 0
):
    await interaction.response.defer()
    
    quotes_data = load_quotes()
    
    all_messages = [msg async for msg in interaction.channel.history(limit=50)]
    
    non_bot_messages = [msg for msg in all_messages if not msg.author.bot]
    
    if not non_bot_messages:
        await interaction.followup.send("No suitable messages found in recent history.")
        return
    
    if skip >= len(non_bot_messages):
        await interaction.followup.send(f"Cannot skip {skip} messages, only {len(non_bot_messages)} available.")
        return
    
    available_messages = non_bot_messages[skip:]
    
    if messages > len(available_messages):
        await interaction.followup.send(f"Cannot get {messages} messages, only {len(available_messages)} available after skip.")
        return
    
    selected_messages = available_messages[:messages]
    selected_messages.reverse()
    
    if author:
        author_lower = author.lower()
        selected_messages = [msg for msg in selected_messages if msg.author.name.lower() == author_lower]
        
        if not selected_messages:
            await interaction.followup.send(f"No messages found from author '{author}' in the selected range.")
            return
    
    if not selected_messages:
        await interaction.followup.send("No valid messages to add as quote.")
        return
    
    valid_messages = [msg for msg in selected_messages if msg.content.strip()]
    if not valid_messages:
        await interaction.followup.send("Cannot add empty messages as quote.")
        return
    
    quote_lines = []
    authors = []
    seen_authors = set()
    
    # Check if all messages are from the same author
    first_author = valid_messages[0].author.name.lower()
    all_same_author = all(msg.author.name.lower() == first_author for msg in valid_messages)
    
    for msg in valid_messages:
        if all_same_author:
            # If all from same author, just add the text
            quote_lines.append(msg.content.strip())
        else:
            # If from different authors, format as "text - author"
            quote_lines.append(f"{msg.content.strip()} - {msg.author.name}")
        
        author_lower = msg.author.name.lower()
        if author_lower not in seen_authors:
            authors.append(msg.author.name)
            seen_authors.add(author_lower)
    
    combined_text = "\n".join(quote_lines)
    
    if len(combined_text) > 500:
        await interaction.followup.send("Combined quote too long (max 500 characters).")
        return
    
    if len(authors) == 1:
        author_str = authors[0]
    else:
        author_str = ", ".join(authors)
    
    date_str = datetime.now().strftime("%d/%m/%Y")
    
    if quote_exists(quotes_data, combined_text, author_str):
        await interaction.followup.send("Taki cytat juz istnieje.")
        return

    new_quote = {
        "id": get_next_id(quotes_data),
        "text": combined_text,
        "author": author_str,
        "date": date_str
    }
    
    quotes_data.append(new_quote)
    save_quotes(quotes_data)
    
    preview = combined_text if len(combined_text) <= 100 else combined_text[:97] + "..."
    await interaction.followup.send(f'Quote #{new_quote["id"]} added: "{preview}" - {author_str} ({date_str})')

@bot.tree.command(name="create", description="Add a new quote manually")
async def create_slash(interaction: discord.Interaction, quote: str, author: str = None):
    if not quote.strip():
        await interaction.response.send_message("Quote cannot be empty.", ephemeral=True)
        return
    
    if len(quote) > 500:
        await interaction.response.send_message("Quote too long (max 500 characters).", ephemeral=True)
        return
    
    quotes = load_quotes()
    
    author_name = format_author_name(author) if author else interaction.user.name
    date_str = datetime.now().strftime("%d/%m/%Y")
    
    if quote_exists(quotes, quote, author_name):
        await interaction.response.send_message("Taki cytat juz istnieje.", ephemeral=True)
        return

    new_quote = {
        "id": get_next_id(quotes),
        "text": quote.strip(),
        "author": author_name,
        "date": date_str
    }
    
    quotes.append(new_quote)
    save_quotes(quotes)
    
    await interaction.response.send_message(f'Quote #{new_quote["id"]} added: "{quote}" - {author_name} ({date_str})')

@bot.tree.command(name="edit", description="Edit one of your quotes")
async def edit_slash(interaction: discord.Interaction, quote_id: int, new_text: str):
    if not new_text.strip():
        await interaction.response.send_message("New text cannot be empty.", ephemeral=True)
        return
    
    if len(new_text) > 500:
        await interaction.response.send_message("New text too long (max 500 characters).", ephemeral=True)
        return
    
    quotes = load_quotes()
    quote = find_quote_by_id(quotes, quote_id)
    
    if not quote:
        await interaction.response.send_message(f"Quote #{quote_id} not found.", ephemeral=True)
        return
    
    if not can_modify_quote(interaction, quote, OWNER_ID):
        await interaction.response.send_message("You can only edit your own quotes.", ephemeral=True)
        return
    
    old_text = quote["text"]
    quote["text"] = new_text.strip()
    save_quotes(quotes)
    
    await interaction.response.send_message(
        f'Quote #{quote_id} updated!\n'
        f'Old: "{old_text}"\n'
        f'New: "{new_text}" - {quote["author"]} ({quote["date"]})'
    )

@bot.tree.command(name="delete", description="Delete one of your quotes")
async def delete_slash(interaction: discord.Interaction, quote_id: int):
    quotes = load_quotes()
    quote = find_quote_by_id(quotes, quote_id)
    
    if not quote:
        await interaction.response.send_message(f"Quote #{quote_id} not found.", ephemeral=True)
        return
    
    if not can_modify_quote(interaction, quote, OWNER_ID):
        await interaction.response.send_message("You can only delete your own quotes.", ephemeral=True)
        return
    
    quotes.remove(quote)
    save_quotes(quotes)
    
    await interaction.response.send_message(
        f'Quote #{quote_id} deleted: "{quote["text"]}" - {quote["author"]} ({quote["date"]})'
    )

@bot.tree.command(name="cycle", description="Cycle to next status quote (owner only)")
async def cycle_slash(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Owner-only command.", ephemeral=True)
        return
    
    quotes = load_quotes()
    
    if not quotes:
        await interaction.response.send_message("No quotes to cycle through.", ephemeral=True)
        return
    
    valid_quotes = get_valid_status_quotes(quotes)
    
    if not valid_quotes:
        await interaction.response.send_message("No quotes fit in status (max 128 chars).", ephemeral=True)
        return
    
    # Get current status to find next quote
    current_activity = bot.activity
    current_index = 0
    
    if current_activity:
        current_status = current_activity.name
        # Try to find current quote in valid quotes
        for i, q in enumerate(valid_quotes):
            cleaned_text = clean_quote_text(q["text"])
            status_text = f'"{cleaned_text}" - {q["author"]}'
            if status_text == current_status:
                current_index = i
                break
    
    # Get next quote (wrap around)
    next_index = (current_index + 1) % len(valid_quotes)
    next_quote = valid_quotes[next_index]
    
    await set_status_to_quote(next_quote)
    
    cleaned_text = clean_quote_text(next_quote["text"])
    await interaction.response.send_message(
        f'Status cycled to quote #{next_quote["id"]}:\n"{cleaned_text}" - {next_quote["author"]}'
    )

@bot.tree.command(name="rave", description="🎉 Toggle RAVE MODE - quotes cycle every 5 seconds!")
async def rave_slash(interaction: discord.Interaction, annoy: str = None):
    """
    Toggle rave mode - cycles quotes every 5 seconds!
    
    Parameters:
    - annoy: Optional - user ID (1234567890) or "everyone" to ping @everyone
    """
    global rave_mode_active, rave_task, annoy_user_id
    
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Owner-only command.", ephemeral=True)
        return
    
    quotes = load_quotes()
    if not quotes:
        await interaction.response.send_message("No quotes available for rave mode!", ephemeral=True)
        return
    
    if rave_mode_active:
        # Stop rave mode
        rave_mode_active = False
        annoy_user_id = None
        
        if rave_task:
            rave_task.cancel()
            rave_task = None
        
        # Set back to daily quote
        valid_quotes = get_valid_status_quotes(quotes)
        if valid_quotes:
            index = get_daily_quote_index(valid_quotes)
            await set_status_to_quote(valid_quotes[index])
        
        await interaction.response.send_message("🛑 Rave mode DISABLED. Back to chill vibes.")
    
    else:
        # Start rave mode
        rave_mode_active = True
        
        # Parse annoy parameter
        if annoy:
            annoy_lower = annoy.strip().lower()
            if annoy_lower == "everyone":
                annoy_user_id = "everyone"
            else:
                try:
                    annoy_user_id = int(annoy.strip())
                except ValueError:
                    await interaction.response.send_message("Invalid format. Use user ID (1234567890) or 'everyone'", ephemeral=True)
                    rave_mode_active = False
                    return
        else:
            annoy_user_id = None
        
        # Determine channel to spam
        # Use current channel if in guild, None if in DM (status only)
        spam_channel = interaction.channel if interaction.guild else None
        
        # Start the rave loop
        rave_task = asyncio.create_task(rave_mode_loop(spam_channel))
        
        if spam_channel:
            annoy_msg = ""
            if annoy_user_id == "everyone":
                annoy_msg = " | Pinging @everyone"
            elif annoy_user_id:
                annoy_msg = f" | Pinging <@{annoy_user_id}>"
            await interaction.response.send_message(f"🎉 RAVE MODE ACTIVATED! 🎉\nQuotes cycling every 5 seconds in this channel!{annoy_msg}")
        else:
            await interaction.response.send_message("🎉 RAVE MODE ACTIVATED! 🎉\nStatus cycling every 5 seconds (DM mode - no messages)")


@bot.tree.command(name="all", description="Show all quotes (owner only)")
async def all_slash(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Owner-only command.", ephemeral=True)
        return
    
    quotes = load_quotes()
    
    if not quotes:
        await interaction.response.send_message("No quotes to display.")
        return
    
    embeds = []
    current_embed = discord.Embed(title="All Quotes", color=0x1E3A8A)
    field_count = 0
    
    for q in quotes:
        if field_count >= 25:
            embeds.append(current_embed)
            current_embed = discord.Embed(title="All Quotes (continued)", color=0x1E3A8A)
            field_count = 0
        
        current_embed.add_field(
            name=f"#{q['id']} - {q['author']}",
            value=f'"{q["text"]}" ({q["date"]})',
            inline=False
        )
        field_count += 1
    
    embeds.append(current_embed)
    
    await interaction.response.send_message(embed=embeds[0])
    for embed in embeds[1:]:
        await interaction.followup.send(embed=embed)

@bot.tree.command(name="mine", description="Show all your quotes")
async def mine_slash(interaction: discord.Interaction):
    quotes = load_quotes()
    
    if not quotes:
        await interaction.response.send_message("No quotes yet.")
        return
    
    user_name = interaction.user.name
    
    filtered = []
    for q in quotes:
        author_names = [a.strip().lower() for a in q["author"].split(",")]
        if user_name.lower() in author_names:
            filtered.append(q)
    
    if not filtered:
        await interaction.response.send_message(f"You don't have any quotes yet, {user_name}!")
        return
    
    category = categorize_author(len(filtered))
    
    embed = discord.Embed(
        title=f"Quotes by {user_name}",
        description=f"Total: {len(filtered)} quote{'s' if len(filtered) != 1 else ''} - {category}",
        color=0x1E3A8A
    )
    
    for q in filtered:
        embed.add_field(
            name=f"#{q['id']} - {q['date']}",
            value=f'"{q["text"]}"',
            inline=False
        )
    
    await interaction.response.send_message(embed=embed)

@bot.tree.command(name="random", description="Display a random quote")
async def random_slash(interaction: discord.Interaction):
    quotes = load_quotes()
    
    if not quotes:
        await interaction.response.send_message("No quotes to display")
        return
    
    seed = f"{datetime.now().timestamp()}{interaction.user.id}"
    hash_obj = hashlib.md5(seed.encode())
    hash_int = int(hash_obj.hexdigest(), 16)
    index = hash_int % len(quotes)
    
    q = quotes[index]
    
    await interaction.response.send_message(f'#{q["id"]}: "{q["text"]}" - {q["author"]} ({q["date"]})')

@bot.tree.command(name="daily", description="Show today's quote")
async def daily_slash(interaction: discord.Interaction):
    quotes = load_quotes()
    
    if not quotes:
        await interaction.response.send_message("No quotes to display")
        return
    
    index = get_daily_quote_index(quotes)
    q = quotes[index]
    
    await interaction.response.send_message(f'Daily Quote\n#{q["id"]}: "{q["text"]}" - {q["author"]} ({q["date"]})')

@bot.tree.command(name="shutdown", description="Shutdown the bot (owner only)")
async def shutdown_slash(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("You don't have permission.", ephemeral=True)
        return
    
    await interaction.response.send_message("Shutting down...")
    await bot.close()

@bot.tree.command(name="sync", description="Force sync slash commands (owner only)")
async def sync_slash(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("You don't have permission.", ephemeral=True)
        return
    
    await interaction.response.defer(ephemeral=True)
    
    try:
        # Sync globally
        synced = await bot.tree.sync()
        
        # Also sync to current guild for immediate effect
        if interaction.guild:
            guild_synced = await bot.tree.sync(guild=interaction.guild)
            await interaction.followup.send(
                f"✅ Synced {len(synced)} global commands\n"
                f"✅ Synced {len(guild_synced)} commands to this server\n"
                f"Commands should appear immediately!",
                ephemeral=True
            )
        else:
            await interaction.followup.send(
                f"✅ Synced {len(synced)} global commands",
                ephemeral=True
            )
    except Exception as e:
        await interaction.followup.send(f"❌ Sync failed: {e}", ephemeral=True)

# -------------------------------
# Run the bot
# -------------------------------
if __name__ == "__main__":
    bot.run(TOKEN)