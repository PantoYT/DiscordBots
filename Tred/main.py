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

# ---------------------------------------------------------------------------
# Single-instance guard: a second copy (e.g. a stray autostart entry) binds the
# same localhost port, fails, and exits instead of double-posting on one token.
# ---------------------------------------------------------------------------
_singleton = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    _singleton.bind(("127.0.0.1", 47923))
except OSError:
    print("[Tred] Druga instancja juz dziala — wychodze.")
    raise SystemExit(0)

load_dotenv()
TOKEN    = os.getenv("DISCORD_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID"))
TRIVIA_FILE = pathlib.Path(__file__).parent / "trivia.json"

TRED_COLOR = 0x10B981

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix=commands.when_mentioned, intents=intents)

rave_mode_active = False
rave_task        = None
annoy_user_id    = None

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_trivia():
    if TRIVIA_FILE.exists():
        try:
            with open(TRIVIA_FILE, "r", encoding="utf-8") as f:
                trivia_list = json.load(f)
                needs_save  = False
                next_id     = max([t.get("id", 0) for t in trivia_list], default=0) + 1
                for t in trivia_list:
                    if "id" not in t:
                        t["id"] = next_id; next_id += 1; needs_save = True
                if needs_save:
                    save_trivia(trivia_list)
                return trivia_list
        except json.JSONDecodeError as e:
            print(f"Błąd ładowania trivia: {e}")
            return []
    return []

def save_trivia(trivia_list):
    try:
        tmp = TRIVIA_FILE.parent / (TRIVIA_FILE.name + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(trivia_list, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, TRIVIA_FILE)
    except Exception as e:
        print(f"Błąd zapisu trivia: {e}")

def get_next_id(trivia_list):
    if not trivia_list: return 1
    return max([t.get("id", 0) for t in trivia_list]) + 1

def find_trivia_by_id(trivia_list, trivia_id):
    for t in trivia_list:
        if t.get("id") == trivia_id: return t
    return None

def categorize_contributor(count):
    if count <= 5:   return "Nowicjusz"
    if count <= 15:  return "Odkrywca Faktów"
    if count <= 30:  return "Poszukiwacz Wiedzy"
    if count <= 50:  return "Ekspert Trivia"
    if count <= 75:  return "Mistrz Faktów"
    if count <= 100: return "Encyklopedia"
    return "Wszechwiedzączy"

def clean_trivia_text(text):
    text = re.sub(r'<@!?\d+>', '', text)
    text = re.sub(r'<@&\d+>', '', text)
    text = re.sub(r'<#\d+>', '', text)
    return ' '.join(text.split()).strip()

def get_daily_trivia_index(trivia_list):
    if not trivia_list: return 0
    today    = datetime.now().strftime("%Y-%m-%d")
    hash_int = int(hashlib.md5(today.encode()).hexdigest(), 16)
    return hash_int % len(trivia_list)

def can_modify_trivia(interaction, trivia, owner_id):
    if interaction.user.id == owner_id: return True
    return interaction.user.name == trivia.get("contributor", "")

def get_valid_status_trivia(trivia_list):
    valid = []
    for t in trivia_list:
        status_text = f'Czy wiesz, że? {clean_trivia_text(t["text"])}'
        if len(status_text) <= 128:
            valid.append(t)
    return valid

async def set_status_to_trivia(trivia):
    status_text = f'Czy wiesz, że? {clean_trivia_text(trivia["text"])}'
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name=status_text
    ))

def format_rave_message(trivia):
    category = trivia.get("category", "Ogólne")
    return f'**RAVE MODE** 🎉\nCzy wiesz, że? {trivia["text"]} (Kategoria: {category}, #{trivia["id"]})'

async def rave_mode_loop(channel_to_spam=None):
    global rave_mode_active, annoy_user_id
    trivia_list  = load_trivia()
    valid_trivia = get_valid_status_trivia(trivia_list) or trivia_list
    index = 0
    while rave_mode_active:
        try:
            trivia = valid_trivia[index % len(valid_trivia)]
            await set_status_to_trivia(trivia)
            if channel_to_spam:
                msg = format_rave_message(trivia)
                if annoy_user_id == "everyone":   msg = f"@everyone\n{msg}"
                elif annoy_user_id:               msg = f"<@{annoy_user_id}>\n{msg}"
                await channel_to_spam.send(msg)
            index += 1
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Rave mode błąd: {e}")
            await asyncio.sleep(5)

# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

@bot.event
async def on_ready():
    print(f"[Tred] Zalogowano jako {bot.user}")
    try:
        synced = await bot.tree.sync()
        print(f"[Tred] Zsynchronizowano {len(synced)} komend")
        for guild in bot.guilds:
            await bot.tree.sync(guild=guild)
    except Exception as e:
        print(f"[Tred] Błąd sync: {e}")
    trivia_list = load_trivia()
    if trivia_list:
        valid = get_valid_status_trivia(trivia_list)
        if valid:
            await set_status_to_trivia(valid[get_daily_trivia_index(valid)])
            return
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="Trivia i ciekawostki | /commands"
    ))

# ---------------------------------------------------------------------------
# Slash commands
# ---------------------------------------------------------------------------

@bot.tree.command(name="commands", description="Lista komend Tred")
async def commands_slash(interaction: discord.Interaction):
    embed = discord.Embed(title="Tred — Trivia & Ciekawostki", description="Zbieraj i dziel się ciekawostkami!", color=TRED_COLOR)
    embed.add_field(name="/random",              value="Losowa ciekawostka",                        inline=False)
    embed.add_field(name="/daily",               value="Dzisiejsza ciekawostka",                    inline=False)
    embed.add_field(name="/category <kategoria>",value="Ciekawostki z wybranej kategorii",          inline=False)
    embed.add_field(name="/categories",          value="Lista wszystkich kategorii",                inline=False)
    embed.add_field(name="/mine",                value="Twoje ciekawostki",                         inline=False)
    embed.add_field(name="/create <tekst> <kat>",value="Dodaj nową ciekawostkę",                   inline=False)
    embed.add_field(name="/edit <id> <tekst>",   value="Edytuj swoją ciekawostkę",                 inline=False)
    embed.add_field(name="/delete <id>",         value="Usuń swoją ciekawostkę",                   inline=False)
    embed.add_field(name="/search <słowo>",      value="Szukaj ciekawostek po słowie kluczowym",   inline=False)
    embed.add_field(name="/stats",               value="Statystyki trivia",                         inline=False)
    embed.add_field(name="Owner only",           value="`/all` `/cycle` `/rave` `/sync` `/shutdown`", inline=False)
    embed.set_footer(text="Tred • Trivia Recurrent Editor & Dump")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="create", description="Dodaj nową ciekawostkę")
async def create_slash(interaction: discord.Interaction, tekst: str, kategoria: str):
    trivia_list = load_trivia()
    new_trivia  = {
        "id":          get_next_id(trivia_list),
        "text":        tekst,
        "category":    kategoria.strip(),
        "contributor": interaction.user.name,
        "date":        datetime.now().strftime("%d/%m/%Y"),
    }
    trivia_list.append(new_trivia)
    save_trivia(trivia_list)
    await interaction.response.send_message(
        f'✅ Ciekawostka #{new_trivia["id"]} dodana!\n"{tekst}"\nKategoria: {kategoria} · Autor: {interaction.user.name}'
    )


@bot.tree.command(name="edit", description="Edytuj ciekawostkę po ID")
async def edit_slash(interaction: discord.Interaction, id: int, nowy_tekst: str):
    trivia_list = load_trivia()
    trivia      = find_trivia_by_id(trivia_list, id)
    if not trivia:
        await interaction.response.send_message(f"❌ Nie znaleziono ciekawostki #{id}.", ephemeral=True); return
    if not can_modify_trivia(interaction, trivia, OWNER_ID):
        await interaction.response.send_message(f"❌ Możesz edytować tylko swoje ciekawostki.", ephemeral=True); return
    old = trivia["text"]
    trivia["text"] = nowy_tekst
    save_trivia(trivia_list)
    await interaction.response.send_message(f'✅ Ciekawostka #{id} zaktualizowana!\nStara: "{old}"\nNowa: "{nowy_tekst}"')


@bot.tree.command(name="delete", description="Usuń ciekawostkę po ID")
async def delete_slash(interaction: discord.Interaction, id: int):
    trivia_list = load_trivia()
    trivia      = find_trivia_by_id(trivia_list, id)
    if not trivia:
        await interaction.response.send_message(f"❌ Nie znaleziono ciekawostki #{id}.", ephemeral=True); return
    if not can_modify_trivia(interaction, trivia, OWNER_ID):
        await interaction.response.send_message("❌ Możesz usuwać tylko swoje ciekawostki.", ephemeral=True); return
    trivia_list.remove(trivia)
    save_trivia(trivia_list)
    await interaction.response.send_message(f'🗑️ Ciekawostka #{id} usunięta: "{trivia["text"]}"')


@bot.tree.command(name="category", description="Ciekawostki z wybranej kategorii")
async def category_slash(interaction: discord.Interaction, kategoria: str):
    trivia_list = load_trivia()
    if not trivia_list:
        await interaction.response.send_message("Brak ciekawostek."); return
    filtered = [t for t in trivia_list if t.get("category", "").lower() == kategoria.strip().lower()]
    if not filtered:
        await interaction.response.send_message(f"❌ Brak ciekawostek w kategorii '{kategoria}'."); return
    embed = discord.Embed(title=f"📂 {kategoria}", description=f"Łącznie: {len(filtered)}", color=TRED_COLOR)
    for t in filtered[:25]:
        embed.add_field(name=f"#{t['id']} — {t.get('contributor','?')}", value=f'{t["text"]} ({t["date"]})', inline=False)
    if len(filtered) > 25:
        embed.set_footer(text=f"Pokazuję pierwsze 25 z {len(filtered)}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="categories", description="Lista wszystkich kategorii")
async def categories_slash(interaction: discord.Interaction):
    trivia_list = load_trivia()
    if not trivia_list:
        await interaction.response.send_message("Brak ciekawostek."); return
    categories = {}
    for t in trivia_list:
        cat = t.get("category", "Bez kategorii")
        categories[cat] = categories.get(cat, 0) + 1
    sorted_cats = sorted(categories.items(), key=lambda x: x[1], reverse=True)
    embed = discord.Embed(title="📋 Kategorie", description=f"Łącznie kategorii: {len(sorted_cats)}", color=TRED_COLOR)
    cat_list = "\n".join(f"**{cat}**: {count}" for cat, count in sorted_cats)
    embed.add_field(name="Dostępne kategorie", value=cat_list or "—", inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="search", description="Szukaj ciekawostki po słowie kluczowym")
async def search_slash(interaction: discord.Interaction, slowo: str):
    trivia_list = load_trivia()
    if not trivia_list:
        await interaction.response.send_message("Brak ciekawostek."); return
    filtered = [t for t in trivia_list if slowo.lower() in t["text"].lower()]
    if not filtered:
        await interaction.response.send_message(f"❌ Brak ciekawostek zawierających '{slowo}'."); return
    embed = discord.Embed(title=f"🔍 Wyniki dla '{slowo}'", description=f"Znaleziono: {len(filtered)}", color=TRED_COLOR)
    for t in filtered[:25]:
        embed.add_field(
            name=f"#{t['id']} — {t.get('category','Ogólne')}",
            value=f'{t["text"]}\nAutor: {t.get("contributor","?")} ({t["date"]})',
            inline=False,
        )
    if len(filtered) > 25:
        embed.set_footer(text=f"Pokazuję pierwsze 25 z {len(filtered)}")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="stats", description="Statystyki trivia na serwerze")
async def stats_slash(interaction: discord.Interaction):
    trivia_list = load_trivia()
    if not trivia_list:
        await interaction.response.send_message("Brak ciekawostek."); return
    contributors = {}
    categories   = {}
    for t in trivia_list:
        c = t.get("contributor", "?"); contributors[c] = contributors.get(c, 0) + 1
        k = t.get("category", "Bez kategorii"); categories[k] = categories.get(k, 0) + 1
    top_c = sorted(contributors.items(), key=lambda x: x[1], reverse=True)[:5]
    top_k = sorted(categories.items(),   key=lambda x: x[1], reverse=True)[:5]
    embed = discord.Embed(title="📊 Statystyki Trivia", description=f"Łącznie ciekawostek: {len(trivia_list)}", color=TRED_COLOR)
    embed.add_field(name="Top autorzy", value="\n".join(f"**{n}**: {c} ({categorize_contributor(c)})" for n, c in top_c), inline=False)
    embed.add_field(name="Top kategorie", value="\n".join(f"**{k}**: {c}" for k, c in top_k), inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="random", description="Losowa ciekawostka")
async def random_slash(interaction: discord.Interaction):
    trivia_list = load_trivia()
    if not trivia_list:
        await interaction.response.send_message("Brak ciekawostek."); return
    seed     = f"{datetime.now().timestamp()}{interaction.user.id}"
    hash_int = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    t        = trivia_list[hash_int % len(trivia_list)]
    embed    = discord.Embed(title="🎲 Losowa ciekawostka", description=t["text"], color=TRED_COLOR)
    embed.add_field(name="Kategoria", value=t.get("category","Ogólne"), inline=True)
    embed.add_field(name="Autor",     value=t.get("contributor","?"),   inline=True)
    embed.set_footer(text=f"#{t['id']} · {t['date']} · Tred")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="daily", description="Dzisiejsza ciekawostka")
async def daily_slash(interaction: discord.Interaction):
    trivia_list = load_trivia()
    if not trivia_list:
        await interaction.response.send_message("Brak ciekawostek."); return
    t     = trivia_list[get_daily_trivia_index(trivia_list)]
    embed = discord.Embed(title="📅 Ciekawostka dnia", description=t["text"], color=TRED_COLOR)
    embed.add_field(name="Kategoria", value=t.get("category","Ogólne"), inline=True)
    embed.add_field(name="Autor",     value=t.get("contributor","?"),   inline=True)
    embed.set_footer(text=f"#{t['id']} · {t['date']} · Tred")
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="mine", description="Twoje ciekawostki")
async def mine_slash(interaction: discord.Interaction):
    trivia_list = load_trivia()
    filtered    = [t for t in trivia_list if t.get("contributor","").lower() == interaction.user.name.lower()]
    if not filtered:
        await interaction.response.send_message(f"Nie masz jeszcze żadnych ciekawostek, {interaction.user.name}!"); return
    rank  = categorize_contributor(len(filtered))
    embed = discord.Embed(title=f"Ciekawostki — {interaction.user.name}", description=f"Łącznie: {len(filtered)} · {rank}", color=TRED_COLOR)
    for t in filtered:
        embed.add_field(name=f"#{t['id']} — {t.get('category','Ogólne')} ({t['date']})", value=t["text"], inline=False)
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="all", description="Wszystkie ciekawostki (owner only)")
async def all_slash(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Tylko właściciel.", ephemeral=True); return
    trivia_list = load_trivia()
    if not trivia_list:
        await interaction.response.send_message("Brak ciekawostek."); return
    embeds, current_embed, count = [], discord.Embed(title="Wszystkie ciekawostki", color=TRED_COLOR), 0
    for t in trivia_list:
        if count >= 25:
            embeds.append(current_embed)
            current_embed = discord.Embed(title="Wszystkie ciekawostki (cd.)", color=TRED_COLOR)
            count = 0
        current_embed.add_field(
            name=f"#{t['id']} — {t.get('category','?')}",
            value=f'{t["text"]}\nAutor: {t.get("contributor","?")} ({t["date"]})',
            inline=False,
        )
        count += 1
    embeds.append(current_embed)
    await interaction.response.send_message(embed=embeds[0])
    for e in embeds[1:]: await interaction.followup.send(embed=e)


@bot.tree.command(name="cycle", description="Następny status trivia (owner only)")
async def cycle_slash(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Tylko właściciel.", ephemeral=True); return
    trivia_list  = load_trivia()
    valid_trivia = get_valid_status_trivia(trivia_list)
    if not valid_trivia:
        await interaction.response.send_message("Brak ciekawostek.", ephemeral=True); return
    current_index = 0
    if bot.activity:
        for i, t in enumerate(valid_trivia):
            if f'Czy wiesz, że? {clean_trivia_text(t["text"])}' == bot.activity.name:
                current_index = i; break
    next_t = valid_trivia[(current_index + 1) % len(valid_trivia)]
    await set_status_to_trivia(next_t)
    await interaction.response.send_message(f'✅ Status → ciekawostka #{next_t["id"]}: {clean_trivia_text(next_t["text"])[:80]}')


@bot.tree.command(name="rave", description="🎉 Rave mode — ciekawostki co 5 sekund (owner only)")
async def rave_slash(interaction: discord.Interaction, annoy: str = None):
    global rave_mode_active, rave_task, annoy_user_id
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Tylko właściciel.", ephemeral=True); return
    trivia_list = load_trivia()
    if not trivia_list:
        await interaction.response.send_message("Brak ciekawostek!", ephemeral=True); return
    if rave_mode_active:
        rave_mode_active = False; annoy_user_id = None
        if rave_task: rave_task.cancel(); rave_task = None
        valid = get_valid_status_trivia(trivia_list)
        if valid: await set_status_to_trivia(valid[get_daily_trivia_index(valid)])
        await interaction.response.send_message("🛑 Rave mode wyłączony.")
    else:
        rave_mode_active = True
        if annoy:
            if annoy.strip().lower() == "everyone": annoy_user_id = "everyone"
            else:
                try: annoy_user_id = int(annoy.strip())
                except ValueError:
                    await interaction.response.send_message("❌ Zły format. Podaj ID lub 'everyone'.", ephemeral=True)
                    rave_mode_active = False; return
        spam_channel = interaction.channel if interaction.guild else None
        rave_task    = asyncio.create_task(rave_mode_loop(spam_channel))
        extra = f" | Pinguje <@{annoy_user_id}>" if annoy_user_id and annoy_user_id != "everyone" else (" | Pinguje @everyone" if annoy_user_id else "")
        await interaction.response.send_message(f"🎉 RAVE MODE AKTYWOWANY!{extra}")


@bot.tree.command(name="sync", description="Force sync komend (owner only)")
async def sync_slash(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Tylko właściciel.", ephemeral=True); return
    await interaction.response.defer(ephemeral=True)
    synced = await bot.tree.sync()
    if interaction.guild: await bot.tree.sync(guild=interaction.guild)
    await interaction.followup.send(f"✅ Zsynchronizowano {len(synced)} komend", ephemeral=True)


@bot.tree.command(name="shutdown", description="Wyłącz Tred (owner only)")
async def shutdown_slash(interaction: discord.Interaction):
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message("Nie masz uprawnień.", ephemeral=True); return
    await interaction.response.send_message("Wyłączam Tred...")
    await bot.close()


if __name__ == "__main__":
    bot.run(TOKEN)
