"""
Forza la sincronizzazione dei comandi slash con Discord.
Usalo solo se i comandi non appaiono dopo il riavvio normale.

    python scripts/deploy_commands.py
"""
import asyncio
import os
from pathlib import Path

import discord
from discord.ext import commands
from dotenv import load_dotenv
from config import Config

load_dotenv()


async def main():
    bot = commands.Bot(command_prefix="!", intents=discord.Intents.default())

    @bot.event
    async def on_ready():
        print(f"Loggato come {bot.user}")
        for f in Path("cogs").glob("*.py"):
            if f.stem != "__init__":
                await bot.load_extension(f"cogs.{f.stem}")
        if Config.GUILD_IDS:
            total = 0
            for gid in Config.GUILD_IDS:
                g = discord.Object(id=gid)
                bot.tree.clear_commands(guild=g)
                bot.tree.copy_global_to(guild=g)
                synced = await bot.tree.sync(guild=g)
                total += len(synced)
                print(f"Guild {gid}: sincronizzati {len(synced)} comandi.")
            print(f"Sincronizzazione completata: {total} comandi totali su {len(Config.GUILD_IDS)} guild.")
        else:
            synced = await bot.tree.sync()
            print(f"Sincronizzati {len(synced)} comandi globali.")
        await bot.close()

    async with bot:
        await bot.start(os.getenv("DISCORD_TOKEN"))


asyncio.run(main())
