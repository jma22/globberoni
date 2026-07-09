"""
Shopping list bot for a locked #shopping channel — in-memory edition.

How it works:
  - Every item on the list is its own message in #shopping.
  - Type item names (comma-separated) in #shopping to add them; your
    message is deleted right away so the channel stays clean.
  - React ✅ on an item to buy it — the message disappears.
  - /shop <items> works from ANY channel for quick adds.

NOTE: state lives in memory — restarting the bot clears the list.

Setup:
  1. pip install -U discord.py
  2. Create a bot at https://discord.com/developers/applications
     - Enable the MESSAGE CONTENT intent (Bot tab -> Privileged Gateway Intents)
     - Invite with permissions: View Channel, Send Messages, Manage Messages,
       Add Reactions, Read Message History, Use Application Commands
  3. Lock #shopping: only you two + the bot can send messages there.
  4. Run:
     export BOT_TOKEN="..."
     export SHOPPING_CHANNEL_ID="123456789"   # right-click channel -> Copy ID
     python reminder_bot.py
"""

import os
import discord
from discord.ext import commands
from discord import app_commands

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
SHOPPING_CHANNEL_ID = int(os.environ["SHOPPING_CHANNEL_ID"])
# Optional: set GUILD_ID for INSTANT slash-command registration during dev.
# Without it, sync is global and can take up to an hour to appear in Discord.
GUILD_ID = int(os.environ["GUILD_ID"]) if os.environ.get("GUILD_ID") else None

MAX_ITEMS = 25
BUY_EMOJI = "✅"

# ------------------------------------------------------------ in-memory state

# message id -> item name. One live message per item, so this IS the list.
shopping_items: dict[int, str] = {}


def has_item(name: str) -> bool:
    name = name.lower()
    return any(existing.lower() == name for existing in shopping_items.values())


def parse_names(text: str) -> list[str]:
    return [p.strip() for p in text.split(",") if p.strip()]


# ------------------------------------------------------------------ discord

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!",intents=intents)


async def add_names(channel, names):
    """Post one message per new item. Returns (added, dupes, skipped_full)."""
    added, dupes, skipped = [], [], 0
    for name in names:
        if has_item(name):
            dupes.append(name)
            continue
        if len(shopping_items) >= MAX_ITEMS:
            skipped += 1
            continue
        msg = await channel.send(f"\U0001f6d2 **{name}**")
        shopping_items[msg.id] = name
        added.append(name)
        # Pre-seed the check so buying it is always a single tap.
        try:
            await msg.add_reaction(BUY_EMOJI)
        except discord.HTTPException:
            pass
    return added, dupes, skipped


@bot.event
async def on_ready():
    if GUILD_ID:
        guild = discord.Object(id=GUILD_ID)
        # Copy globally-defined commands to the guild and sync — instant.
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    else:
        await bot.tree.sync()
    # State is in memory, so any surviving item messages are orphans.
    channel = bot.get_channel(SHOPPING_CHANNEL_ID)
    if channel is not None:
        await channel.purge(limit=50, check=lambda m: m.author == bot.user)
    print(f"Logged in as {bot.user} — list ready.")


@bot.event
async def on_message(message):
    """Any human message in #shopping = add items."""
    if message.author.bot:
        return
    if message.channel.id == SHOPPING_CHANNEL_ID:
        names = parse_names(message.content)
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        _, _, skipped = await add_names(message.channel, names)
        if skipped:
            warn = await message.channel.send(
                f"⚠️ List is full ({MAX_ITEMS} max) — {skipped} item(s) not added. "
                f"Check some off with {BUY_EMOJI} first.")
            await warn.delete(delay=6)
        return
    await bot.process_commands(message)


@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id or payload.channel_id != SHOPPING_CHANNEL_ID:
        return
    if str(payload.emoji) != BUY_EMOJI or payload.message_id not in shopping_items:
        return

    del shopping_items[payload.message_id]
    channel = bot.get_channel(payload.channel_id)
    try:
        await channel.get_partial_message(payload.message_id).delete()
    except discord.HTTPException:
        pass


@bot.hybrid_command(name="shop", description="Add item(s) to the shopping list (comma-separated)")
@app_commands.describe(items="e.g. milk, eggs, hot sauce")
async def shop(ctx: commands.Context, *, items: str):
    channel = bot.get_channel(SHOPPING_CHANNEL_ID)
    if channel is None:
        await ctx.send("Can't reach the shopping channel.", ephemeral=True)
        return
    added, dupes, skipped = await add_names(channel, parse_names(items))
    if added:
        note = f"Added: {', '.join(added)}"
        if skipped:
            note += f" (list full — {skipped} skipped)"
    elif skipped:
        note = f"List is full ({MAX_ITEMS} max) — nothing added."
    elif dupes:
        note = "Already on the list."
    else:
        note = "Nothing to add."
    await ctx.send(note, ephemeral=True)


@bot.hybrid_command(name="test", description="Test command to verify the bot is working")
async def test(ctx: commands.Context):
    await ctx.send("The bot is working!", ephemeral=True)
bot.run(DISCORD_TOKEN)
