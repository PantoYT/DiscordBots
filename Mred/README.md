# Mred – Music Recurrent Editor & Dump

Mred is a Discord bot for exploring music through the Spotify API — search tracks, browse artists, get recommendations, and discover new releases.

> **Note:** Mred does not play audio. It uses the Spotify Web API to display music information and recommendations.

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
| `/artist <name>` | Artist info + top 5 tracks |
| `/album <name> [artist]` | Album info + tracklist |
| `/recommend <genre>` | Recommended tracks by genre |
| `/genres` | List all available genre seeds |
| `/new` | New album releases in Poland |

## Running your own instance
1. Create a Spotify app at [developer.spotify.com](https://developer.spotify.com) → Create App
2. Copy your **Client ID** and **Client Secret**
3. Create a `.env` file:
   ```
   DISCORD_TOKEN=your_bot_token
   OWNER_ID=your_discord_id
   SPOTIFY_CLIENT_ID=your_spotify_client_id
   SPOTIFY_CLIENT_SECRET=your_spotify_client_secret
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
