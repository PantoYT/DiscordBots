# Rred – Reminder Recurrent Editor & Dump

Rred is a Discord bot for setting personal reminders and timers.

## Features
- ⏰ **Flexible time formats**: Relative (`30m`, `2h`, `1d`, `1h30m`) or absolute (`DD/MM/YYYY HH:MM`)
- 📬 **Dual delivery**: Reminders sent as DM + message on the original channel
- 📋 **Reminder management**: List and cancel your active reminders
- 🔄 **Persistent**: Reminders survive bot restarts (stored in `reminders.json`)

## Available Commands
- `/remind <time> <message>` — Set a reminder
- `/reminders` — List your active reminders
- `/cancel <id>` — Cancel a reminder by ID

## Time format examples
| Input | Meaning |
|-------|---------|
| `30m` | 30 minutes from now |
| `2h` | 2 hours from now |
| `1d` | 1 day from now |
| `1h30m` | 1 hour and 30 minutes |
| `01/06/2026 15:30` | Specific date and time (UTC) |

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
- All times are stored and interpreted in UTC
- The bot checks for due reminders every 30 seconds
- Reminders are delivered via DM; if DMs are closed, only the channel message is sent
