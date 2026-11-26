"""Help command handler: /help."""

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

router = Router(name="help_router")


@router.message(Command("help"))
async def handle_help_command(message: Message):
    help_text = (
        "📖 *TicketNotify Bot - Complete Guide*\n\n"
        "TicketNotify monitors cinema booking platforms in real time and alerts you the instant "
        "tickets open or new seats become available.\n\n"
        "📌 *Commands:*\n"
        "• /track - Guided wizard: movie -> location -> platforms -> theatres -> filters -> seats -> urgency\n"
        "• /list - View active alerts with inline controls\n"
        "• /theatres - Customize cinema selections for an active alert\n"
        "• /seats - Configure group size, zones, and categories\n"
        "• /test - Preview live sample alerts across all 4 platforms\n"
        "• /remove - Delete an alert\n"
        "• /location - Change your default location\n"
        "• /settings - Quiet hours, languages, preferences\n"
        "• /deleteme - GDPR wipe: permanently deletes your data\n\n"
        "🏷 *Supported Platforms:*\n"
        "• *BookMyShow (BMS)* - India, UAE, Indonesia, Sri Lanka\n"
        "• *Ticketnew* - India\n"
        "• *District (by Zomato)* - India, UAE\n"
        "• *PVR INOX* - India, Sri Lanka\n\n"
        "⚡ *Alert Types:*\n"
        "• `Bookings Opened` - First shows announced\n"
        "• `New Show Added` - Additional showtimes or cinemas added\n"
        "• `Seats Filling Fast` - Tickets running low\n"
        "• `Price Drop` - Tickets discounted\n"
        "• `Cinema Opened` - Your specific favorite cinema opened\n\n"
        "🎯 *Filter Options per Alert:*\n"
        "• Formats: `IMAX`, `3D`, `4DX`, `Dolby Atmos`, `2D`\n"
        "• Chains: `PVR`, `INOX`, `Cinepolis`, `SPI`, `Miraj`\n"
        "• Maximum Ticket Price\n"
        "• Minimum Seats Needed\n\n"
        "To get started right now, tap /track!"
    )
    await message.answer(help_text, parse_mode="Markdown")
