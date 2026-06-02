# Mred – Music Recurrent Editor & Dump

Mred is a Discord bot for exploring music through the Spotify API — search tracks, browse artists, get recommendations, and discover new releases.

> **Note:** Mred does not play audio. It uses the Last.fm API to display music information — no Spotify Premium required.

## Features
- 🔍 **Search**: Find tracks on Spotify
- 🎤 **Artist info**: Bio, follower count, genres, top tracks
- 💿 **Album info**: Tracklist, release date, artist
- 🎲 **Recommendations**: Get tracks by genre seed
- 🎵 **Genre list**: Browse all available Spotify genre seeds
- 🆕 **New releases**: Latest albums in Poland

## Available Commands
| Command | Description |
|---------|-------------|
| `/search <query>` | Search for a track |
| `/artist <name>` | Artist info + bio |
| `/toptracks <artist>` | Top tracks by artist |
| `/album <artist> <album>` | Album info + tracklist |
| `/similar <artist>` | Similar artists |
| `/topcharts` | Global top tracks this week |
| `/tag <genre>` | Top tracks by genre/tag |

## Running your own instance
1. Create a free API account at [last.fm/api/account/create](https://www.last.fm/api/account/create)
2. Copy your **API key**
3. Create a `.env` file:
   ```
   DISCORD_TOKEN=your_bot_token
   OWNER_ID=your_discord_id
   LASTFM_API_KEY=your_lastfm_api_key
   ```
4. Install dependencies:
   ```
   pip install -r requirements.txt
   ```
5. Run:
   ```
   python main.py
   ```

## Notes
- Uses Spotify Client Credentials flow — no user login required
- All Spotify links open in the Spotify app or web player
- Genre seeds for `/recommend` can be listed with `/genres`
