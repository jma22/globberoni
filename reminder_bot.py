"""
Shopping list bot for a locked #shopping channel — in-memory edition.

How it works:
  - The bot keeps ONE dashboard message in #shopping (the current list).
  - Type item names (comma-separated) in #shopping to add them; your
    message is deleted right away so the channel stays clean.
  - Type an item's name AGAIN to toggle it checked/unchecked.
    ("milk" -> added, "milk" -> ~~milk~~ ✅, "milk" -> back on the list)
  - React 🧹 on the dashboard to sweep checked items away.
  - /to-buy <items> works from ANY channel for quick adds.

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
SWEEP_EMOJI = "\U0001f9f9"  # 🧹

# ------------------------------------------------------------ in-memory state

# Each item: {"name": str, "checked": bool}
shopping_list: list[dict] = []
dashboard_message_id: int | None = None


def find_item(name: str):
    name = name.lower()
    for item in shopping_list:
        if item["name"].lower() == name:
            return item
    return None


def apply_names(names, allow_toggle=True):
    """Add new items; if a name already exists (and toggling is allowed),
    flip its checked state instead. Returns (added, toggled, skipped_full)."""
    added, toggled, skipped = [], [], 0
    for raw in names:
        name = raw.strip()
        if not name:
            continue
        existing = find_item(name)
        if existing:
            if allow_toggle:
                existing["checked"] = not existing["checked"]
                toggled.append(existing["name"])
            continue
        if len(shopping_list) >= MAX_ITEMS:
            skipped += 1
            continue
        shopping_list.append({"name": name, "checked": False})
        added.append(name)
    return added, toggled, skipped


def sweep_checked() -> int:
    global shopping_list
    before = len(shopping_list)
    shopping_list = [i for i in shopping_list if not i["checked"]]
    return before - len(shopping_list)


# ---------------------------------------------------------------- rendering

def render_dashboard() -> str:
    if not shopping_list:
        body = "*Nothing on the list — type here to add items.*"
    else:
        lines = []
        for item in shopping_list:
            if item["checked"]:
                lines.append(f"\u2022 ~~{item['name']}~~ \u2705")
            else:
                lines.append(f"\u2022 **{item['name']}**")
        body = "\n".join(lines)

    footer = (f"\n\ntype to add \u00b7 type again to check off \u00b7 "
              f"{SWEEP_EMOJI} clears checked \u00b7 {len(shopping_list)}/{MAX_ITEMS}")
    return f"\U0001f6d2 **Shopping List**\n\n{body}{footer}"


# ------------------------------------------------------------------ discord

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!",intents=intents)
tree = bot.tree


async def get_dashboard(channel):
    """Return the dashboard message, creating it if needed."""
    global dashboard_message_id
    if dashboard_message_id:
        try:
            return await channel.fetch_message(dashboard_message_id)
        except discord.NotFound:
            pass
    msg = await channel.send(render_dashboard())
    dashboard_message_id = msg.id
    try:
        await msg.pin()
    except discord.HTTPException:
        pass
    return msg


async def refresh_dashboard():
    channel = bot.get_channel(SHOPPING_CHANNEL_ID)
    if channel is None:
        return
    msg = await get_dashboard(channel)
    await msg.edit(content=render_dashboard())

    # Pre-seed the broom so sweeping is always a single tap.
    if not any(str(r.emoji) == SWEEP_EMOJI for r in msg.reactions):
        await msg.add_reaction(SWEEP_EMOJI)


@bot.event
async def on_ready():
    if GUILD_ID:
        guild = discord.Object(id=GUILD_ID)
        # Copy globally-defined commands to the guild and sync — instant.
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    else:
        await bot.tree.sync()
    # Fresh start: clean up any old bot messages so the channel shows one list.
    channel = bot.get_channel(SHOPPING_CHANNEL_ID)
    if channel is not None:
        async for old in channel.history(limit=50):
            if old.author == bot.user:
                try:
                    await old.delete()
                except discord.HTTPException:
                    pass
        await refresh_dashboard()
    print(f"Logged in as {bot.user} — dashboard ready.")


@bot.event
async def on_message(message):
    """Any human message in #shopping = add items / toggle existing ones."""
    if message.author.bot:
        return
    if message.channel.id == SHOPPING_CHANNEL_ID:
        names = [p.strip() for p in message.content.split(",") if p.strip()]
        added, toggled, skipped = apply_names(names)
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        if skipped:
            warn = await message.channel.send(
                f"\u26a0\ufe0f List is full ({MAX_ITEMS} max) — {skipped} item(s) not added. "
                f"Sweep with {SWEEP_EMOJI} first.")
            await warn.delete(delay=6)
        if added or toggled or skipped:
            await refresh_dashboard()
        return
    await bot.process_commands(message)


@bot.event
async def on_raw_reaction_add(payload):
    if payload.user_id == bot.user.id or payload.channel_id != SHOPPING_CHANNEL_ID:
        return
    if dashboard_message_id is None or payload.message_id != dashboard_message_id:
        return

    changed = str(payload.emoji) == SWEEP_EMOJI and sweep_checked() > 0

    # Remove the user's reaction so the broom stays reusable.
    channel = bot.get_channel(payload.channel_id)
    try:
        msg = await channel.fetch_message(payload.message_id)
        member = payload.member or await channel.guild.fetch_member(payload.user_id)
        await msg.remove_reaction(payload.emoji, member)
    except discord.HTTPException:
        pass

    if changed:
        await refresh_dashboard()


@bot.hybrid_command(name="shop", description="Add item(s) to the shopping list (comma-separated)")
@app_commands.describe(items="e.g. milk, eggs, hot sauce")
async def shop(ctx: commands.Context, *, items: str):
    names = [p.strip() for p in items.split(",") if p.strip()]
    # From other channels, don't toggle — only add. (Typing "milk" twice in
    # conversation shouldn't check it off; toggling stays a #shopping gesture.)
    added, _, skipped = apply_names(names, allow_toggle=False)
    await refresh_dashboard()
    if added:
        note = f"Added: {', '.join(added)}"
        if skipped:
            note += f" (list full — {skipped} skipped)"
    elif skipped:
        note = f"List is full ({MAX_ITEMS} max) — nothing added."
    else:
        note = "Already on the list."
    await ctx.send(note, ephemeral=True)


@bot.hybrid_command(name="test", description="Test command to verify the bot is working")
async def test(ctx: commands.Context):
    await ctx.send("The bot is working!", ephemeral=True)
bot.run(DISCORD_TOKEN)