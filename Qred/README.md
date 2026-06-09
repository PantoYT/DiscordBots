# Qred – Quote Recurrent Editor & Dump

Qred is a Discord bot that allows you to collect, display, and manage quotes on your server. You can add your own quotes, view random quotes, browse by author, and receive a daily quote.

## How to use
- Add the bot to your server using this link: [Discord Invite](https://discord.com/oauth2/authorize?client_id=1464359456660914403)
- Use slash commands to add quotes, browse by author, view random quotes, or get a daily quote.
- To see all available commands, type `/commands`.

## Running your own instance
1. Create a `.env` file containing:
   - Your Discord ID
   - Your Discord bot token
2. Install all required Python packages from `requirements.txt`.
3. Run the bot using a `.vbs` file or directly in Python to keep it running in the background.
4. To shut down the bot, use the `/shutdown` command.

## Notes
- Quotes are automatically saved with the author and date in the format `DD/MM/YYYY`.
- Author names are case-insensitive.
- Authors added via `/createquote` are automatically stored.
- The daily quote (`/dailyquote`) is selected based on a date-looping system.
