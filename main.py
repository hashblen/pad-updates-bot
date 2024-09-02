import discord
from discord.ext import tasks
import os
from dotenv import load_dotenv
import requests
import aiosqlite
from dataclasses import dataclass
import difflib
from io import BytesIO

load_dotenv()  # load all the variables from the env file
bot = discord.Bot()


@dataclass
class Pad:
    gid: int
    cid: int
    url: str
    content: str
    error_count: int
    verbosity: int


async def createTable(connection: aiosqlite.Connection):
    await connection.execute("""
        CREATE TABLE IF NOT EXISTS pads (
            gid INTEGER PRIMARY KEY, cid INTEGER, url TEXT, content TEXT, error_count INTEGER DEFAULT 0, verbosity INTEGER DEFAULT 0
        )""")
    await connection.commit()


db = None


@tasks.loop(seconds=300)
async def sendChanges():
    cursor = await db.execute("SELECT * FROM pads")
    results = await cursor.fetchall()
    for res in results:
        resPad = Pad(*res)
        if bot.get_channel(resPad.cid) is None:
            await db.execute("DELETE FROM pads WHERE gid=?", (resPad.gid,))
            await db.commit()
            continue
        try:
            r = requests.get(resPad.url)
            content = r.content.decode('utf-8')
            r.raise_for_status()
        except requests.exceptions.RequestException as e:
            if resPad.error_count == 0 and resPad.verbosity:
                await bot.get_channel(resPad.cid).send(f"The url given has errored, ignoring next errors.\n-# {str(e)}")
            await db.execute("UPDATE pads SET error_count=error_count+1 WHERE gid=?", (resPad.gid,))
            await db.commit()
            continue
        if content.startswith("<html>"):
            continue
        if resPad.error_count != 0:
            if resPad.verbosity:
                await bot.get_channel(resPad.cid).send(f"-# Errors stopped.")
            await db.execute("UPDATE pads SET error_count=0 WHERE gid=?", (resPad.gid,))
            await db.commit()
        if content != resPad.content:
            diff = difflib.ndiff(resPad.content.splitlines(keepends=True), content.splitlines(keepends=True))
            diff = [d for d in diff if d[0] in "-+?"]
            await db.execute("UPDATE pads SET content=? WHERE gid=?", (content, resPad.gid))
            await db.commit()
            await bot.get_channel(resPad.cid).send("The pad has changed! url: " + resPad.url[:-11])
            if len(''.join(diff)) < 1950:
                await bot.get_channel(resPad.cid).send('```' + ''.join(diff) + '```')
            else:
                await bot.get_channel(resPad.cid).send(
                    file=discord.File(BytesIO(str.encode(''.join(diff))), "message.txt"))


@bot.event
async def on_ready():
    print("Setting up")
    global db
    db = await aiosqlite.connect("db.sqlite")
    await createTable(db)
    print(f"{bot.user} is ready and online!")
    sendChanges.start()


@bot.slash_command(name="verbosity", description="set verbosity")
async def verbosity(ctx, verbose: bool):
    cursor = await db.execute("SELECT * FROM pads WHERE gid=?", (ctx.guild.id,))
    result = await cursor.fetchone()
    if result is None:
        await ctx.respond(f"The bot is not bound!")
    else:
        verbosity = 1 if verbose else 0
        await db.execute("UPDATE pads SET verbosity=? WHERE gid=?", (verbosity, ctx.guild.id))
        await db.commit()
        await ctx.respond(f"Set verbosity to {verbosity}")


@bot.slash_command(name="pad", description="get current pad")
async def pad(ctx):
    cursor = await db.execute("SELECT * FROM pads WHERE gid=?", (ctx.guild.id,))
    result = await cursor.fetchone()
    if result is None:
        await ctx.respond(f"The bot is not bound!")
    else:
        final_res = Pad(*result)
        await ctx.respond(file=discord.File(BytesIO(requests.get(final_res.url).content), "message.txt"))


@bot.slash_command(name="getpad", description="get pad from url")
async def getpad(ctx, url: str):
    if not url.endswith("/export/txt") or not url.endswith("/export/txt/"):
        if url.endswith("/"):
            url = "export/txt"
        else:
            url += "/export/txt"
    content = b''
    try:
        r = requests.get(url)
        content = r.content.decode('utf-8')
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        await ctx.respond("Sent bad url!\n```" + str(e) + "```")
        return
    await ctx.respond(file=discord.File(BytesIO(content), "message.txt"))


@bot.slash_command(name="bind", description="Bind to a channel")
async def bind(ctx, url: str):
    gid = ctx.guild.id
    cid = ctx.channel.id
    newUrl = url
    if not url.endswith("/export/txt") or not url.endswith("/export/txt/"):
        if url.endswith("/"):
            newUrl = "export/txt"
        else:
            newUrl += "/export/txt"
    content = None
    try:
        r = requests.get(newUrl)
        content = r.content.decode('utf-8')
        r.raise_for_status()
    except requests.exceptions.RequestException as e:
        await ctx.respond("Sent bad url!\n```" + str(e) + "```")
        return
    await db.execute('''INSERT INTO pads (gid, cid, url, content) VALUES (?, ?, ?, ?) 
                        ON CONFLICT(gid) DO UPDATE SET cid=?, url=?, content=?''',
                     (gid, cid, newUrl, content, cid, newUrl, content))
    await db.commit()
    await ctx.respond(f"Bound to <#{str(ctx.channel.id)}> on guild **{str(ctx.guild.name)}** to url {url}")


@bot.slash_command(name="isbound", description="Prints the channel where is the bot bound if exists")
async def isbound(ctx):
    cursor = await db.execute("SELECT * FROM pads WHERE gid=?", (ctx.guild.id,))
    result = await cursor.fetchone()
    if result is None:
        await ctx.respond(f"The bot is not bound!")
    else:
        final_res = Pad(*result)
        await ctx.respond(f"The bot is bound to <#{final_res.cid}> on guild **{str(ctx.guild.name)}** "
                          f"with url {final_res.url[:-11]}")


@bot.slash_command(name="unbind", description="Unbinds the bot.")
async def unbind(ctx):
    await db.execute("DELETE FROM pads WHERE gid=?", (ctx.guild.id,))
    await db.commit()
    await ctx.respond("Successfully unbound.")


bot.run(os.getenv('TOKEN'))  # run the bot with the token
