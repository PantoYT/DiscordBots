# Ared – Admin Recurrent Editor & Dump

Ared is a Discord moderation bot for managing users, channels, and server order.

## Features
- 👢 **Kick & Ban**: Remove users from the server
- 🔇 **Mute**: Discord timeout system (`10m`, `1h`, `7d`, up to 28 days)
- 🧹 **Clear**: Bulk delete messages (1–100)
- ⚠️ **Warnings**: Warn users, view history, clear warnings
- 🔒 **Channel control**: Lock/unlock channels, set slowmode
- 📬 **DM notifications**: Warned users receive a DM automatically

## Available Commands
| Command | Description |
|---------|-------------|
| `/kick <user> [reason]` | Kick a user |
| `/ban <user> [reason]` | Ban a user |
| `/unban <user_id>` | Unban by user ID |
| `/mute <user> <time> [reason]` | Timeout a user |
| `/unmute <user>` | Remove timeout |
| `/clear <amount>` | Delete 1–100 messages |
| `/warn <user> <reason>` | Issue a warning |
| `/warnings <user>` | View warning history |
| `/clearwarns <user>` | Clear all warnings |
| `/slowmode <seconds>` | Set slowmode (0 = off) |
| `/lock` | Block @everyone from sending messages |
| `/unlock` | Restore @everyone send permissions |

## Required bot permissions
- Kick Members, Ban Members
- Moderate Members (for timeout)
- Manage Messages (for clear)
- Manage Channels (for lock/unlock/slowmode)

## Running your own instance
1. Create a `.env` file:
   ```
   DISCORD_TOKEN=your_bot_token
   OWNER_ID=your_discord_id
   ```
2. Enable **Server Members Intent** in Discord Developer Portal → Bot → Privileged Gateway Intents
3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
4. Run:
   ```
   python main.py
   ```

## Notes
- Warnings are stored in `warnings.json` per guild
- Moderation commands require Kick Members, Ban Members, or Manage Messages permission
- The bot owner bypasses all permission checks
