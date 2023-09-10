import discord
from discord.ext import tasks
import os
from dotenv import load_dotenv
import requests
import aiosqlite
from dataclasses import dataclass
import difflib

load_dotenv()  # load all the variables from the env file
bot = discord.Bot()

@dataclass
class Pad:
    gid: int
    cid: int
    url: str
    content: str

async def createTable(connection : aiosqlite.Connection):
    await connection.execute("""
        CREATE TABLE IF NOT EXISTS pads (
            gid INTEGER PRIMARY KEY, cid INTEGER, url TEXT, content TEXT
        )""")
    await connection.commit()

db = None

@bot.event
async def on_connect():
    print("Setting up")
    global db
    db = await aiosqlite.connect("db.sqlite")
    await createTable(db)

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
            content = requests.get(resPad.url).content.decode('utf-8')
        except requests.exceptions.RequestException as e:
            await bot.get_channel(resPad.cid).send("The url given is bad, try to redo /bind")
            continue
        if content != resPad.content:
            diff = difflib.ndiff(resPad.content.splitlines(keepends=True), content.splitlines(keepends=True))
            diff = [d for d in diff if d[0] in "-+?"]
            await db.execute("UPDATE pads SET content=? WHERE gid=?", (content, resPad.gid))
            await db.commit()
            await bot.get_channel(resPad.cid).send("The pad has changed! (diff algorithm test, "
                                                   "https://en.wikipedia.org/wiki/Diff)")
            await bot.get_channel(resPad.cid).send('```' + ''.join(diff) + '```')


@bot.event
async def on_ready():
    print(f"{bot.user} is ready and online!")
    sendChanges.start()


@bot.slash_command(name="pad", description="get current pad")
async def pad(ctx):
    cursor = await db.execute("SELECT * FROM pads WHERE gid=?", (ctx.guild.id,))
    result = await cursor.fetchone()
    if result is None:
        await ctx.respond(f"The bot is not bound!")
    else:
        final_res = Pad(*result)
        file = open("message.txt", 'wb')
        file.write(requests.get(final_res.url).content)
        file.close()
        await ctx.respond(file=discord.File("message.txt"))

@bot.slash_command(name="getpad", description="get pad from url")
async def getpad(ctx, url: str):
    if not url.endswith("/export/txt") or not url.endswith("/export/txt/"):
        if url.endswith("/"):
            url = "export/txt"
        else:
            url += "/export/txt"
    file = open("message.txt", 'wb')
    try:
        file.write(requests.get(url).content)
    except requests.exceptions.RequestException as e:
        await ctx.respond("Sent bad url!")
        file.close()
        return
    file.close()
    await ctx.respond(file=discord.File("message.txt"))

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
        content = requests.get(newUrl).content.decode('utf-8')
    except requests.exceptions.RequestException as e:
        await ctx.respond("Sent bad url!")
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
                          f"with url {final_res.url[:-10]}")

@bot.slash_command(name="unbind", description="Unbinds the bot.")
async def unbind(ctx):
    await db.execute("DELETE FROM pads WHERE gid=?", (ctx.guild.id,))
    await db.commit()
    await ctx.respond("Successfully unbound.")

bot.run(os.getenv('TOKEN'))  # run the bot with the token
