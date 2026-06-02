# Pred – Poll Recurrent Editor & Dump

Pred is a Discord bot for creating polls and quick votes on your server.

## Features
- 📊 **Multi-option polls**: Create polls with 2–4 options using letter reactions
- 🗳️ **Quick polls**: Instant yes/no votes
- 📋 **Poll management**: List active polls, end them and view results
- 📈 **Results with bar chart**: Visual percentage breakdown per option

## Available Commands
- `/poll <question> <A> <B> [C] [D]` — Create a poll with 2–4 options
- `/quickpoll <question>` — Create a quick yes/no poll
- `/endpoll <message_id>` — End a poll and display results
- `/polls` — List active polls on this server

## Running your own instance
1. Create a `.env` file:
   ```
   DISCORD_TOKEN=your_bot_token
   OWNER_ID=your_discord_id
   ```
2. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
3. Run:
   ```
   python main.py
   ```

## Notes
- Poll results are counted from reactions — bot's own reaction is excluded from the count
- Only the poll author or the owner can end a poll
- Active polls are stored in `polls.json`
