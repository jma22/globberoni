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

from datetime import datetime, time
import os
from unittest import case
import discord
from discord.ext import commands, tasks
from discord import app_commands
import asyncio
import enum
from typing import Literal
import pydantic
from tinydb import TinyDB, Query
from tinydb.storages import JSONStorage

import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger(__name__)


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



class GlobberoniBot(commands.Bot):
    async def setup_hook(self) -> None:
        if GUILD_ID:
            guild = discord.Object(id=GUILD_ID)
            # Copy globally-defined commands to the guild and sync — instant.
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()
        logger.info(f"Logged in as {self.user} — list ready.")



class Archive(commands.Cog):
    CHANNEL_ID = int(os.environ["ARCHIVE_CHANNEL_ID"])
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # self.table = db.table("archive")
        self.channel = None
    
    @commands.Cog.listener()
    async def on_ready(self):
        self.channel = self.bot.get_channel(Archive.CHANNEL_ID)
    
    @commands.Cog.listener()
    async def on_archive(self, message : str):
        msg = await self.channel.send(f"{message}")


    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.channel.id != Archive.CHANNEL_ID:
            return
        try:
            await message.delete()
        except discord.NotFound:
            pass


class Notes(commands.Cog):
    CHANNEL_ID = int(os.environ["TODO_CHANNEL_ID"])
    DONE_EMOJI = "✅"
    def __init__(self, bot: commands.Bot, db: TinyDB):
        self.bot = bot
        self.table = db.table("notes")
        # self.todo_list: dict[int, str] = {}
        self.channel = None

    @commands.Cog.listener()
    async def on_ready(self):
        self.channel = self.bot.get_channel(Notes.CHANNEL_ID)
        # await self.channel.purge()
    
    @commands.hybrid_command(name="note", description="Add item to the note list")
    @app_commands.describe(reminder="book appointment, call mom, a code, an address etc.")
    async def note(self,ctx: commands.Context, reminder: str):
        sender = MEMBER_IDS.get(ctx.author.id).value
        msg = await self.channel.send(f"\U0001f4dd **{reminder}**")
        await msg.add_reaction(Notes.DONE_EMOJI)
        payload = {"msg_id": msg.id, "content": reminder, "added_by": sender}
        add_to_table(self.table, payload)
        await ctx.send(f"{sender} added to note list: {reminder}", ephemeral=True)


    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id:
            return
        reacted_message_id = payload.message_id
        if str(payload.emoji) == Notes.DONE_EMOJI:
            result = find_msg_if_exist(self.table, reacted_message_id)
            if result:
                await self.channel.get_partial_message(reacted_message_id).delete()
                item = result["content"]
                self.bot.dispatch("archive", self.archive_note(payload.user_id, item))
                set_archived_to_table(self.table, reacted_message_id)

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.channel.id != Notes.CHANNEL_ID:
            return
        try:
            await message.delete()
        except discord.NotFound:
            pass

    def archive_note(self, user_id, item):
        return f"**Note:** {item} (removed by {MEMBER_IDS.get(user_id)})"


class ExpenseObject(pydantic.BaseModel):
    expense: str
    amount: float
    fronter: Names

    def to_dict(self):
        return {
            "expense": self.expense,
            "amount": self.amount,
            "fronter": self.fronter.value
        }
    

class Target(enum.Enum):
    BOTH = "both"
    THEM = "them"
    ME = "me"



class Expenses(commands.Cog):
    CHANNEL_ID = int(os.environ["EXPENSES_CHANNEL_ID"])

    def __init__(self, bot: commands.Bot, db: TinyDB):
        self.bot = bot
        self.channel = None
        self.expenses: dict[int, ExpenseObject] = {}
        self.pinned_message = None
        self.table = db.table("expenses")
        self.ledger = {Names.MANDY: 0, Names.JEMMY: 0}

    @commands.Cog.listener()
    async def on_ready(self):
        self.channel = self.bot.get_channel(Expenses.CHANNEL_ID)
        await self.channel.purge()
        ## create pinned message with total expenses
        self.pinned_message = None
        await self.init_ledger()

    async def init_ledger(self):
        expenses = self.table.all()
        for expense in expenses:
            self.ledger[Names(expense["fronter"])] += expense["amount"]
        self.pinned_message = await self.channel.send(self.info_msg())
        await self.pinned_message.pin()
    
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
        # self.expenses[msg.id] = expense_obj
        payload = {"msg_id": msg.id, **expense_obj.to_dict(), "for_who": for_who_name}
        add_to_table(self.table, payload)
        self.update_ledger(expense_obj, for_who)
        await self.pinned_message.edit(content=self.info_msg())
        
    def update_ledger(self, expense_obj: ExpenseObject, for_who: Target):
        self.ledger[expense_obj.fronter] += expense_obj.amount

    def info_msg(self):
        spending = self.ledger
        return f"Mandy: ${spending[Names.MANDY]:.2f}, Jemmy: ${spending[Names.JEMMY]:.2f})"
        
    

class Reminders(commands.Cog):
    pass


class DayOfWeek(enum.Enum):
    MONDAY = "Monday"
    TUESDAY = "Tuesday"
    WEDNESDAY = "Wednesday"
    THURSDAY = "Thursday"
    FRIDAY = "Friday"
    SATURDAY = "Saturday"
    SUNDAY = "Sunday"

    @classmethod
    def today(cls):
        # datetime.weekday(): Monday == 0 ... Sunday == 6, matching enum order.
        return list(cls)[datetime.now().weekday()]

    @classmethod
    def parse(cls, value):
        # Accepts any case + prefix, e.g. "Monday", "monday", "mon".
        v = value.strip().lower()
        return next((d for d in cls if d.value.lower().startswith(v)), cls.MONDAY)


class Shopping(commands.Cog):
    CHANNEL_ID = int(os.environ["SHOPPING_CHANNEL_ID"])
    DONE_EMOJI = "✅"
    def __init__(self, bot: commands.Bot, db: TinyDB):
        self.bot = bot
        self.table = db.table("shopping")
        self.recurring_table = db.table("shopping_recurring")
        # self.todo_list: dict[int, str] = {}
        self.channel = None

    @commands.Cog.listener()
    async def on_ready(self):
        self.channel = self.bot.get_channel(Shopping.CHANNEL_ID)
        await self.channel.purge()
        if not self.readd_recurring.is_running():
            self.readd_recurring.start()

    async def cog_unload(self):
        self.readd_recurring.cancel()

    @commands.hybrid_command(name="shop", description="Add item to the shopping list")
    @app_commands.describe(
        item="Item to add to the shopping list",
        recurring="Re-add this item automatically every week",
        day="Day of week to re-add a recurring item (default Monday)",
    )
    async def shop(self, ctx: commands.Context, item: str, recurring: bool = False, day: str = "Monday"):
        day = DayOfWeek.parse(day)
        logger.info(f"Adding item to shopping list: {item} (recurring={recurring}, day={day.value})")
        sender = MEMBER_IDS.get(ctx.author.id).value
        msg = await self.channel.send(f"\U0001f4dd **{item}**")
        await msg.add_reaction(Shopping.DONE_EMOJI)
        payload = {"msg_id": msg.id, "content": item, "added_by": sender,
                   "recurring": recurring, "recur_day": day.value if recurring else None}
        add_to_table(self.table, payload)
        if recurring:
            if not self.recurring_table.contains((Query().content == item) & (Query().recur_day == day.value)):
                self.recurring_table.insert({
                    "content": item,
                    "recur_day": day.value,
                    "added_by": sender,
                    "last_added": str(datetime.now().date()) if day == DayOfWeek.today() else None,
                })
            await ctx.send(f"{sender} added to SHOPPING list: {item}, recurring every {day.value}", ephemeral=True)
        else:
            await ctx.send(f"{sender} added to SHOPPING list: {item}", ephemeral=True)

    @tasks.loop(time=time(hour=9))
    async def readd_recurring(self):
        today = DayOfWeek.today()
        today_str = str(datetime.now().date())
        logger.info(f"Checking recurring shopping items for {today.value}")
        for template in self.recurring_table.search(Query().recur_day == today.value):
            if template.get("last_added") == today_str:
                continue
            msg = await self.channel.send(f"\U0001f4dd **{template['content']}**")
            await msg.add_reaction(Shopping.DONE_EMOJI)
            add_to_table(self.table, {
                "msg_id": msg.id,
                "content": template["content"],
                "added_by": template["added_by"],
                "recurring": True,
                "recur_day": template["recur_day"],
            })
            self.recurring_table.update({"last_added": today_str}, doc_ids=[template.doc_id])

    @readd_recurring.before_loop
    async def before_readd_recurring(self):
        await self.bot.wait_until_ready()


    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload):
        if payload.user_id == self.bot.user.id:
            return
        reacted_message_id = payload.message_id
        if str(payload.emoji) == Shopping.DONE_EMOJI:
            logger.info("Reaction added to shopping item, removing it from the list.")
            result = find_msg_if_exist(self.table, reacted_message_id)
            if result:
                await self.channel.get_partial_message(reacted_message_id).delete()
                item = result["content"]
                self.bot.dispatch("archive", self.archive_note(payload.user_id, item))
                set_archived_to_table(self.table, reacted_message_id)   

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or message.channel.id != Shopping.CHANNEL_ID:
            return
        await message.delete()

    def archive_note(self, user_id, item):
        return f"**Note:** {item} (removed by {MEMBER_IDS.get(user_id)})"

    # def sync(self):



def find_msg_if_exist(table, msg_id):
    ## check if not archived
    result = table.get(Query().msg_id == msg_id)
    if result and not result.get("archived", False):
        return result
    return None



def add_to_table(table, payload):
    logger.info(f"Adding to table {table.name}: {payload}")
    table.insert({**payload, "added_time": str(datetime.now())})
    logger.info(f"Table now has {len(table)} items.")

def set_archived_to_table(table, msg_id):
    logger.info(f"Setting archived for message ID {msg_id} in table {table.name}")
    table.update({"archived": True}, Query().msg_id == msg_id)

import asyncio

if __name__ == "__main__":

    db = TinyDB('db/db.json', storage=JSONStorage, indent=2)

    intents = discord.Intents.default()
    intents.message_content = True

    bot = GlobberoniBot(command_prefix="!",intents=intents)

    @bot.hybrid_command(name="test", description="Test command to verify the bot is working")
    async def test(ctx: commands.Context):
        await ctx.send("The bot is working!", ephemeral=True)
    
    async def main():
        await bot.add_cog(Archive(bot))
        await bot.add_cog(Notes(bot, db))
        await bot.add_cog(Expenses(bot, db))
        await bot.add_cog(Shopping(bot, db))
        await bot.start(DISCORD_TOKEN)

    asyncio.run(main())