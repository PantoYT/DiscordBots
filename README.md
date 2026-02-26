# Discord Bots

A collection of Discord bots built with Python and discord.py — each focused on a different use case for community servers.

## Bots

### [Fred](https://github.com/PantoYT/Fred) — Free Recurrent Epicgames Dump
Automatically fetches and posts Epic Games free game offers to a designated channel.
- Slash commands, auto-posting, RapidAPI integration
- `/confirmchannel`, `/commands`, `/shutdown`

### [Qred](https://github.com/PantoYT/Qred) — Quote Recurrent Editor & Dump
Collect, display, and manage quotes on your server. Supports browsing by author and a daily quote system.
- Date-looping daily quote, case-insensitive author search
- `/createquote`, `/randomquote`, `/dailyquote`, `/commands`

### [Tred](https://github.com/PantoYT/Tred) — Trivia Recurrent Editor & Dump
Manage and browse trivia and fun facts. Features categories, search, statistics, and contributor rankings.
- 7 contributor ranks (Trivia Novice → Omniscient)
- Rave Mode, daily trivia, keyword search
- `/random`, `/daily`, `/category`, `/search`, `/stats`, `/create`, `/edit`, `/delete`

## Tech Stack

- **Python 3.x**
- **discord.py** — slash commands, bot lifecycle
- **SQLite / JSON** — local data storage
- **RapidAPI** — Epic Games API (Fred only)

## Running Any Bot

1. Clone the specific bot's repo
2. Create `.env` with your `DISCORD_TOKEN` and `OWNER_ID`
3. Install dependencies:
```bash
pip install -r requirements.txt
```
4. Run:
```bash
python main.py
```
5. Shut down with `/shutdown`

## Structure

```
DiscordBots/
├── Fred/     ← submodule
├── Qred/     ← submodule
└── Tred/     ← submodule
```

Each bot is an independent repository and can be used standalone.

## License

MIT — see individual bot repositories for details.