import discord
from discord.ext import commands
from discord import app_commands
import asyncio
import os

# Force install Chromium on startup
from booker import book_room, check_availability
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN")

intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)


@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user} — slash commands synced.")


# ─── /bookroom ────────────────────────────────────────────────────────────────

@bot.tree.command(
    name="bookroom",
    description="Book a study room at Milton Public Library"
)
@app_commands.describe(
    date='Date to book (YYYY-MM-DD, e.g. 2026-05-05)',
    start_time='Start time, e.g. 10:00am',
    duration='Duration in minutes: 30, 60, 90, or 120',
    branch='Branch: main, sherwood, or beaty'
)
@app_commands.choices(duration=[
    app_commands.Choice(name="30 minutes", value=30),
    app_commands.Choice(name="1 hour",     value=60),
    app_commands.Choice(name="1.5 hours",  value=90),
    app_commands.Choice(name="2 hours",    value=120),
])
@app_commands.choices(branch=[
    app_commands.Choice(name="Main Library",     value="mainlibrary"),
    app_commands.Choice(name="Sherwood Branch",  value="sherwoodbranch"),
    app_commands.Choice(name="Beaty Branch",     value="beatybranch"),
])
async def bookroom(
    interaction: discord.Interaction,
    date: str,
    start_time: str,
    duration: int = 60,
    branch: str = "mainlibrary"
):
    await interaction.response.defer(thinking=True)

    await interaction.followup.send(
        f"⏳ Attempting to book **{branch.replace('library','').replace('branch',''). strip().title()}** "
        f"on **{date}** at **{start_time}** for **{duration} min**..."
    )

    success, message = await book_room(
        date=date,
        start_time=start_time,
        duration_minutes=duration,
        branch=branch
    )

    if success:
        await interaction.followup.send(
            f"✅ **Booking confirmed!**\n"
            f"📅 Date: **{date}**\n"
            f"🕐 Time: **{start_time}** ({duration} min)\n"
            f"📍 Branch: **{branch}**\n\n"
            f"{message}"
        )
    else:
        await interaction.followup.send(
            f"❌ **Booking failed.**\n```{message}```\n"
            f"Try `/checkavailability {date} {branch}` to see what slots are open."
        )


# ─── /checkavailability ───────────────────────────────────────────────────────

@bot.tree.command(
    name="checkavailability",
    description="Check available study room slots at Milton Public Library"
)
@app_commands.describe(
    date='Date to check (YYYY-MM-DD)',
    branch='Branch: main, sherwood, or beaty'
)
@app_commands.choices(branch=[
    app_commands.Choice(name="Main Library",     value="mainlibrary"),
    app_commands.Choice(name="Sherwood Branch",  value="sherwoodbranch"),
    app_commands.Choice(name="Beaty Branch",     value="beatybranch"),
])
async def checkavailability(
    interaction: discord.Interaction,
    date: str,
    branch: str = "mainlibrary"
):
    await interaction.response.defer(thinking=True)

    try:
        slots = await check_availability(date=date, branch=branch)

        if not slots:
            await interaction.followup.send(
                f"😔 No available slots found for **{date}** at **{branch}**."
            )
            return

        lines = [f"📅 **Available slots on {date}** ({branch}):\n"]
        for slot in slots:
            lines.append(f"• {slot}")

        lines.append(f"\nUse `/bookroom {date} <time>` to book one!")

        # prevent long messages (just in case)
        message = "\n".join(lines)
        if len(message) > 1900:
            message = message[:1900] + "\n... (truncated)"

        await interaction.followup.send(message)

    except Exception as e:
        error_msg = str(e)[:1900]  # 👈 prevents Discord 2000 char crash

        await interaction.followup.send(
            f"❌ Error checking availability:\n```{error_msg}```"
        )


# ─── /help ────────────────────────────────────────────────────────────────────

@bot.tree.command(name="mplhelp", description="How to use the MPL room booker bot")
async def mplhelp(interaction: discord.Interaction):
    embed = discord.Embed(
        title="📚 MPL Room Booker — Help",
        color=discord.Color.blue()
    )
    embed.add_field(
        name="/bookroom",
        value=(
            "Book a study room.\n"
            "`date` — YYYY-MM-DD (up to 7 days ahead)\n"
            "`start_time` — e.g. `10:00am`\n"
            "`duration` — 30 / 60 / 90 / 120 min\n"
            "`branch` — Main / Sherwood / Beaty"
        ),
        inline=False
    )
    embed.add_field(
        name="/checkavailability",
        value="See open slots for a given date and branch.",
        inline=False
    )
    embed.add_field(
        name="⚙️ Setup",
        value="Your library card and name are set in the `.env` file on the server.",
        inline=False
    )
    embed.set_footer(text="Milton Public Library · beinspired.ca")
    await interaction.response.send_message(embed=embed)


bot.run(TOKEN)
