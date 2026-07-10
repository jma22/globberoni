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
from unittest import case
import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import enum
from typing import Literal
import pydantic

DISCORD_TOKEN = os.environ["DISCORD_TOKEN"]
SHOPPING_CHANNEL_ID = int(os.environ["SHOPPING_CHANNEL_ID"])
# Optional: set GUILD_ID for INSTANT slash-command registration during dev.
# Without it, sync is global and can take up to an hour to appear in Discord.
GUILD_ID = int(os.environ["GUILD_ID"]) if os.environ.get("GUILD_ID") else None

class Names(enum.Enum):
    MANDY = "Mandy"
    JEMMY = "Jemmy"

    def other_person(self):
        if self == Names.MANDY:
            return Names.JEMMY
        else:
            return Names.MANDY

    
MEMBER_IDS = {
    656615789658636320 : Names.MANDY,
    168127023900917760: Names.JEMMY
}



# ------------------------------------------------------------ in-memory state

# message id -> item name. One live message per item, so this IS the list.
# shopping_items: dict[int, str] = {}
# todo_list: dict[int, str] = {}

# def get_todo_list() -> list[str]:
#     """Return the current to-do list as a list of item names."""
#     return list(todo_list.values())

# def has_item(name: str) -> bool:
#     name = name.lower()
#     return any(existing.lower() == name for existing in todo_list.values())


# def parse_names(text: str) -> list[str]:
#     return [p.strip() for p in text.split(",") if p.strip()]


# ------------------------------------------------------------------ discord




# async def add_names(channel, names):
#     """Post one message per new item. Returns (added, dupes, skipped_full)."""
#     added, dupes, skipped = [], [], 0
#     for name in names:
#         if has_item(name):
#             dupes.append(name)
#             continue
#         if len(shopping_items) >= MAX_ITEMS:
#             skipped += 1
#             continue
#         msg = await channel.send(f"\U0001f6d2 **{name}**")
#         shopping_items[msg.id] = name
#         added.append(name)
#         # Pre-seed the check so buying it is always a single tap.
#         try:
#             await msg.add_reaction(BUY_EMOJI)
#         except discord.HTTPException:
#             pass
#     return added, dupes, skipped


class GlobberoniBot(commands.Bot):
    async def setup_hook(self) -> None:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            # Copy globally-defined commands to the guild and sync — instant.
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        print(f"Logged in as {bot.user} — list ready.")

# @bot.event
# async def on_ready():
#     if GUILD_ID:
#         guild = discord.Object(id=GUILD_ID)
#         # Copy globally-defined commands to the guild and sync — instant.
#         bot.tree.copy_global_to(guild=guild)
#         await bot.tree.sync(guild=guild)
#     else:
#         await bot.tree.sync()
#     # State is in memory, so any surviving item messages are orphans.
#     channel = bot.get_channel(SHOPPING_CHANNEL_ID)
#     if channel is not None:
#         await channel.purge(limit=50, check=lambda m: m.author == bot.user)
#     print(f"Logged in as {bot.user} — list ready.")


# @bot.event
# async def on_message(message):
#     """Any human message in #shopping = add items."""
#     if message.author.bot:
#         return
#     if message.channel.id == SHOPPING_CHANNEL_ID:
#         names = parse_names(message.content)
#         try:
#             await message.delete()
#         except discord.HTTPException:
#             pass
#         _, _, skipped = await add_names(message.channel, names)
#         if skipped:
#             warn = await message.channel.send(
#                 f"⚠️ List is full ({MAX_ITEMS} max) — {skipped} item(s) not added. "
#                 f"Check some off with {BUY_EMOJI} first.")
#             await warn.delete(delay=6)
#         return
#     await bot.process_commands(message)


# @bot.event
# async def on_raw_reaction_add(payload):
#     if payload.user_id == bot.user.id or payload.channel_id != TODO_CHANNEL_ID:
#         return
#     if str(payload.emoji) != BUY_EMOJI or payload.message_id not in shopping_items:
#         return

#     del shopping_items[payload.message_id]
#     channel = bot.get_channel(payload.channel_id)
#     try:
#         await channel.get_partial_message(payload.message_id).delete()
#     except discord.HTTPException:
#         pass


# @bot.hybrid_command(name="shop", description="Add item(s) to the shopping list (comma-separated)")
# @app_commands.describe(items="e.g. milk, eggs, hot sauce")
# async def shop(ctx: commands.Context, *, items: str):
#     channel = bot.get_channel(SHOPPING_CHANNEL_ID)
#     if channel is None:
#         await ctx.send("Can't reach the shopping channel.", ephemeral=True)
#         return
#     added, dupes, skipped = await add_names(channel, parse_names(items))
#     if added:
#         note = f"Added: {', '.join(added)}"
#         if skipped:
#             note += f" (list full — {skipped} skipped)"
#     elif skipped:
#         note = f"List is full ({MAX_ITEMS} max) — nothing added."
#     elif dupes:
#         note = "Already on the list."
#     else:
#         note = "Nothing to add."
#     await ctx.send(note, ephemeral=True)


class Archive(commands.Cog):
    CHANNEL_ID = int(os.environ["ARCHIVE_CHANNEL_ID"])
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.channel = None
    
    @commands.Cog.listener()
    async def on_ready(self):
        self.channel = self.bot.get_channel(Archive.CHANNEL_ID)
    
    @commands.Cog.listener()
    async def on_archive(self, message : str):
        await self.channel.send(f"{message}")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        await message.delete()

class Notes(commands.Cog):
    CHANNEL_ID = int(os.environ["TODO_CHANNEL_ID"])
    DONE_EMOJI = "✅"
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.todo_list: dict[int, str] = {}
        self.channel = None

    @commands.Cog.listener()
    async def on_ready(self):
        self.channel = self.bot.get_channel(Notes.CHANNEL_ID)
        # await self.channel.purge()
    
    @commands.hybrid_command(name="note", description="Add item to the note list")
    @app_commands.describe(reminder="book appointment, call mom, a code, an address etc.")
    async def note(self,ctx: commands.Context, reminder: str):
        msg = await self.channel.send(f"\U0001f4dd **{reminder}**")
        await msg.add_reaction(Notes.DONE_EMOJI)
        self.todo_list[msg.id] = reminder
        await ctx.send(f"Added to note list: {reminder}", ephemeral=True)


    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id:
            return
        reacted_message_id = payload.message_id
        if str(payload.emoji) == Notes.DONE_EMOJI:
            if reacted_message_id in self.todo_list:
                await self.channel.get_partial_message(reacted_message_id).delete()
                item = self.todo_list.get(reacted_message_id)
                self.bot.dispatch("archive", self.archive_note(payload.user_id, item))
                del self.todo_list[reacted_message_id]

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot:
            return
        await message.delete()

    def archive_note(self, user_id, item):
        return f"**Note:** {item} (removed by {MEMBER_IDS.get(user_id)})"
        

class ExpenseObject(pydantic.BaseModel):
    expense: str
    amount: float
    fronter: Names
    

class Target(enum.Enum):
    BOTH = "both"
    THEM = "them"
    ME = "me"



class Expenses(commands.Cog):
    CHANNEL_ID = int(os.environ["EXPENSES_CHANNEL_ID"])

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.channel = None
        self.expenses: dict[int, ExpenseObject] = {}
        self.pinned_message = None

    @commands.Cog.listener()
    async def on_ready(self):
        self.channel = self.bot.get_channel(Expenses.CHANNEL_ID)
        await self.channel.purge()
        ## create pinned message with total expenses
        self.pinned_message = await self.channel.send("Total Expenses: $0.00")
        await self.pinned_message.pin()
        await self.maintain_pinned_msg()
    
    @commands.hybrid_command(name="spend", description="Add item to the expense list")
    @app_commands.describe(expense="expense description", amount="amount spent", fronted_by = "who paid, default to the command invoker", for_who="For whom the expense is for (both, them, me). Default is me.")
    async def spend(self,ctx: commands.Context, expense: str, amount: float, fronted_by: Names = None, for_who: Target = Target.ME):
        match for_who:
            case Target.BOTH:
                for_who_name = "both"
            case Target.THEM:
                ## other person's name ther would be only 2
                for_who_name = MEMBER_IDS.get(ctx.author.id).other_person().value
            case Target.ME:
                for_who_name = MEMBER_IDS.get(ctx.author.id).value
        if fronted_by is None:
            fronted_by = MEMBER_IDS.get(ctx.author.id)
        expense_obj = ExpenseObject(expense=expense, amount=amount, fronter=fronted_by)
        msg = await self.channel.send(f"\U0001f4b0 **{expense}** - ${amount:.2f} (fronted by {fronted_by.value}) for {for_who_name}")
        await ctx.send(f"Added to expense list: {expense} - ${amount:.2f}", ephemeral=True)
        # msg.add_reaction(Notes.DONE_EMOJI)
        self.expenses[msg.id] = expense_obj
        await self.maintain_pinned_msg()
    

    async def maintain_pinned_msg(self):
        spending = {Names.MANDY: 0, Names.JEMMY: 0}
        for expense in self.expenses.values():
            spending[expense.fronter] += expense.amount
        await self.pinned_message.edit(content=self.info_msg())
    
    def info_msg(self):
        spending = {Names.MANDY: 0, Names.JEMMY: 0}
        for expense in self.expenses.values():
            spending[expense.fronter] += expense.amount
        return f"Mandy: ${spending[Names.MANDY]:.2f}, Jemmy: ${spending[Names.JEMMY]:.2f})"
        
    

class Reminders(commands.Cog):
    pass

class Shopping(commands.Cog):
    pass

## helpers



import asyncio

if __name__ == "__main__":
    intents = discord.Intents.default()
    intents.message_content = True

    bot = GlobberoniBot(command_prefix="!",intents=intents)

    @bot.hybrid_command(name="test", description="Test command to verify the bot is working")
    async def test(ctx: commands.Context):
        await ctx.send("The bot is working!", ephemeral=True)
    
    async def main():
        await bot.add_cog(Archive(bot))
        await bot.add_cog(Notes(bot))
        await bot.add_cog(Expenses(bot))
        await bot.start(DISCORD_TOKEN)

    asyncio.run(main())