# Tred – Trivia Recurrent Editor & Dump

Tred is a Discord bot that allows you to collect, display, and manage trivia and funfacts on your server. You can add your own trivia, view random facts, browse by category, search for specific topics, and receive a daily trivia.

## How to use
- Add the bot to your server using the Discord invite link
- Use slash commands to add trivia, browse by category, view random facts, or get a daily trivia
- To see all available commands, type `/commands`

## Features
- 📚 **Add & Manage Trivia**: Create trivia with categories, edit your own entries
- 🎲 **Random Trivia**: Get a random funfact anytime with `/random`
- 📅 **Daily Trivia**: Receive a unique trivia fact each day with `/daily`
- 🔍 **Search**: Find trivia by keyword or browse by category
- 📊 **Statistics**: Track top contributors and popular categories
- 🎉 **Rave Mode**: Cycle through trivia every 5 seconds (owner only)

## Available Commands
- `/random` - Display a random trivia/funfact
- `/daily` - Show today's trivia/funfact
- `/category <category>` - Show all trivia from a specific category
- `/categories` - List all available categories
- `/mine` - Show all your contributed trivia
- `/create <text> <category>` - Add a new trivia/funfact
- `/edit <id> <new_text>` - Edit your trivia (or owner can edit any)
- `/delete <id>` - Delete your trivia (or owner can delete any)
- `/search <keyword>` - Search for trivia containing a keyword
- `/stats` - Show trivia statistics

### Owner Commands
- `/all` - Show all trivia (owner only)
- `/cycle` - Cycle to next status trivia (owner only)
- `/rave` - Toggle RAVE MODE (owner only)
- `/shutdown` - Shutdown the bot (owner only)
- `/sync` - Force sync slash commands (owner only)

## Running your own instance
1. Create a `.env` file containing:
   - Your Discord ID (`OWNER_ID`)
   - Your Discord bot token (`DISCORD_TOKEN`)
2. Install all required Python packages from `requirements.txt`:
   ```bash
   pip install -r requirements.txt
   ```
3. Run the bot using a `.vbs` file or directly in Python to keep it running in the background:
   ```bash
   python main.py
   ```
4. To shut down the bot, use the `/shutdown` command

## Notes
- Trivia items are automatically saved with the contributor name and date in the format `DD/MM/YYYY`
- Each trivia item is assigned a category for easy organization
- Contributors can edit or delete their own trivia
- The bot owner can manage all trivia items
- The daily trivia (`/daily`) is selected based on a date-looping system
- Categories are case-insensitive for easy searching
- Contributor rankings are based on the number of trivia items contributed

## Contributor Ranks
- **Trivia Novice**: 1-5 trivia items
- **Fact Finder**: 6-15 trivia items
- **Knowledge Seeker**: 16-30 trivia items
- **Trivia Expert**: 31-50 trivia items
- **Fact Master**: 51-75 trivia items
- **Encyclopedia**: 76-100 trivia items
- **Omniscient**: 100+ trivia items
