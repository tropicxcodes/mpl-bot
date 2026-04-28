"""
booker.py — Playwright automation for Milton Public Library LibCal bookings.

HOW LIBCAL WORKS:
  1. You land on the "Search Spaces" page and pick a date.
  2. Available time slots appear as buttons/links.
  3. Clicking a slot opens the booking form.
  4. You fill in name, email, library card, then submit.

Because LibCal is fully JavaScript-rendered, we use Playwright (async).
"""

import os
import asyncio
from datetime import datetime
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
from dotenv import load_dotenv

load_dotenv()

# ── Credentials (set these in your .env file) ────────────────────────────────
LIBRARY_CARD  = os.getenv("LIBRARY_CARD", "")
PATRON_NAME   = os.getenv("PATRON_NAME", "")
PATRON_EMAIL  = os.getenv("PATRON_EMAIL", "")

BRANCH_URLS = {
    "mainlibrary":    "https://beinspired.libcal.com/reserve/spaces/mainlibrary",
    "sherwoodbranch": "https://beinspired.libcal.com/reserve/spaces/sherwoodbranch",
    "beatybranch":    "https://beinspired.libcal.com/reserve/spaces/beatybranch",
}

TIMEOUT = 15_000   # ms — how long to wait for elements before giving up


# ─────────────────────────────────────────────────────────────────────────────
# check_availability
# ─────────────────────────────────────────────────────────────────────────────

async def check_availability(date: str, branch: str = "mainlibrary") -> list[str]:
    """
    Returns a list of available time-slot strings for the given date/branch.
    e.g. ["9:00am", "9:30am", "2:00pm"]
    """
    url = BRANCH_URLS.get(branch, BRANCH_URLS["mainlibrary"])

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page    = await browser.new_page()

        try:
            await page.goto(url, wait_until="networkidle", timeout=30_000)

            # Fill in the date field and trigger a search
            # LibCal uses an input with id="start_date" or similar
            await _set_date(page, date)

            # Wait for slots to render
            await page.wait_for_timeout(2000)

            # Collect visible available time slots
            slots = await _scrape_slots(page)

        except PlaywrightTimeout:
            slots = []
        finally:
            await browser.close()

    return slots


# ─────────────────────────────────────────────────────────────────────────────
# book_room
# ─────────────────────────────────────────────────────────────────────────────

async def book_room(
    date: str,
    start_time: str,
    duration_minutes: int = 60,
    branch: str = "mainlibrary"
) -> tuple[bool, str]:
    """
    Attempts to book a study room.
    Returns (success: bool, message: str).
    """
    if not LIBRARY_CARD or not PATRON_NAME or not PATRON_EMAIL:
        return False, "Missing credentials. Check your .env file (LIBRARY_CARD, PATRON_NAME, PATRON_EMAIL)."

    url = BRANCH_URLS.get(branch, BRANCH_URLS["mainlibrary"])

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page    = await browser.new_page()

        try:
            # ── Step 1: Load the search page ──────────────────────────────
            await page.goto(url, wait_until="networkidle", timeout=30_000)

            # ── Step 2: Set the date ──────────────────────────────────────
            await _set_date(page, date)
            await page.wait_for_timeout(2000)

            # ── Step 3: Click the desired time slot ───────────────────────
            clicked = await _click_time_slot(page, start_time)
            if not clicked:
                return False, f"Time slot '{start_time}' not found or already taken."

            await page.wait_for_load_state("networkidle", timeout=TIMEOUT)

            # ── Step 4: Set duration (if the form has a duration dropdown) ─
            await _set_duration(page, duration_minutes)

            # ── Step 5: Proceed / confirm the slot if there's a next step ─
            # LibCal sometimes shows a "Continue booking" button first
            continue_btn = page.locator("button:has-text('Continue'), input[value='Continue']")
            if await continue_btn.count() > 0:
                await continue_btn.first.click()
                await page.wait_for_load_state("networkidle", timeout=TIMEOUT)

            # ── Step 6: Fill in the booking form ──────────────────────────
            await _fill_booking_form(page)

            # ── Step 7: Submit ────────────────────────────────────────────
            submit = page.locator("button[type='submit'], input[type='submit']").last
            await submit.click()
            await page.wait_for_load_state("networkidle", timeout=TIMEOUT)

            # ── Step 8: Check for success ─────────────────────────────────
            body_text = await page.inner_text("body")
            if any(phrase in body_text.lower() for phrase in [
                "booking confirmed", "your booking", "reservation confirmed",
                "successfully booked", "thank you"
            ]):
                return True, "Booking confirmed by the library system."
            else:
                # Take a screenshot for debugging if it fails
                await page.screenshot(path="/tmp/mpl_booking_fail.png")
                return False, (
                    "Form submitted but couldn't confirm success. "
                    "The slot may be taken or the form changed. "
                    "Screenshot saved to /tmp/mpl_booking_fail.png"
                )

        except PlaywrightTimeout as e:
            return False, f"Timed out waiting for a page element: {e}"
        except Exception as e:
            return False, f"Unexpected error: {e}"
        finally:
            await browser.close()


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _set_date(page, date: str):
    """
    Sets the date in LibCal's search form.
    LibCal uses input#start_date (text input in MM/DD/YYYY format).
    """
    # Convert YYYY-MM-DD → MM/DD/YYYY for LibCal
    try:
        dt = datetime.strptime(date, "%Y-%m-%d")
        libcal_date = dt.strftime("%m/%d/%Y")
    except ValueError:
        libcal_date = date

    # Try the standard LibCal date input
    date_input = page.locator("input#start_date, input[name='start_date'], input[placeholder*='date' i]").first
    if await date_input.count() > 0:
        await date_input.triple_click()
        await date_input.fill(libcal_date)
        await date_input.press("Enter")
    else:
        # Fallback: look for a calendar day cell with data-date attribute
        cell = page.locator(f"[data-date='{date}']")
        if await cell.count() > 0:
            await cell.click()

    # Click "Search" button if present
    search_btn = page.locator("button:has-text('Search'), input[value='Search']")
    if await search_btn.count() > 0:
        await search_btn.first.click()
        await page.wait_for_load_state("networkidle", timeout=TIMEOUT)


async def _scrape_slots(page) -> list[str]:
    """Collect available time slot labels from the results."""
    # LibCal renders slots as links or buttons with time text
    slot_locator = page.locator(
        "a.fc-time-grid-event, "          # FullCalendar events
        ".s-lc-eq-avail, "                 # LibCal available class
        "td.fc-available a, "
        "button.s-lc-slot-available, "
        "[class*='available'] .fc-title"
    )
    slots = []
    count = await slot_locator.count()
    for i in range(count):
        text = (await slot_locator.nth(i).inner_text()).strip()
        if text:
            slots.append(text)
    return slots


async def _click_time_slot(page, start_time: str) -> bool:
    """
    Tries to click a time slot matching start_time (e.g. "10:00am").
    Returns True if clicked, False if not found.
    """
    # Normalise: "10:00am" → try a few formats
    time_variants = [
        start_time,
        start_time.upper(),
        start_time.replace("am", " am").replace("pm", " pm"),
        start_time.replace(":00", "").replace(":30", ":30"),
    ]

    for variant in time_variants:
        locator = page.locator(f"text=/{variant}/i").first
        if await locator.count() > 0:
            await locator.click()
            return True

    # Also try clicking a FullCalendar time slot by aria-label or title
    fc_slot = page.locator(f"[title*='{start_time}'], [aria-label*='{start_time}']").first
    if await fc_slot.count() > 0:
        await fc_slot.click()
        return True

    return False


async def _set_duration(page, duration_minutes: int):
    """If there's a duration dropdown, set it."""
    duration_select = page.locator("select#duration, select[name='duration']")
    if await duration_select.count() > 0:
        await duration_select.select_option(value=str(duration_minutes))


async def _fill_booking_form(page):
    """
    Fills in the standard LibCal booking form fields.

    ⚠️  Field IDs may differ — if booking fails, run the bot with
        headless=False and inspect the form at beinspired.libcal.com
        to find the correct IDs, then update below.
    """
    field_map = {
        # Common LibCal field IDs → your values
        "fname":         PATRON_NAME,
        "email":         PATRON_EMAIL,
        "email2":        PATRON_EMAIL,   # confirmation field
        "nick":          PATRON_NAME,    # sometimes used instead of fname
        # Library card field — LibCal uses a "question" ID like q1234
        # YOU MAY NEED TO UPDATE THIS after inspecting the real form:
        "q_id":          LIBRARY_CARD,   # placeholder — see README
    }

    for field_id, value in field_map.items():
        locator = page.locator(f"input#{field_id}, input[name='{field_id}']")
        if await locator.count() > 0 and value:
            await locator.first.fill(value)

    # Also try any input whose placeholder mentions "library card"
    card_input = page.locator("input[placeholder*='library card' i], input[placeholder*='card number' i]")
    if await card_input.count() > 0:
        await card_input.first.fill(LIBRARY_CARD)

    # Accept terms checkbox if present
    terms = page.locator("input[type='checkbox'][name*='terms'], input[type='checkbox'][id*='terms']")
    if await terms.count() > 0:
        await terms.first.check()
