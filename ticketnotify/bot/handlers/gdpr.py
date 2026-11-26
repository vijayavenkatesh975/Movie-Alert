"""GDPR Compliance: /deleteme command and account deletion handler."""

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton

from ticketnotify.database.session import get_db_session
from ticketnotify.database.crud import delete_user_data_gdpr

router = Router(name="gdpr_router")


@router.message(Command("deleteme"))
@router.callback_query(F.data == "gdpr_delete")
async def confirm_gdpr_deletion(event: Message | CallbackQuery):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⚠️ Yes, Delete All My Data", callback_data="gdpr_confirm_delete"),
                InlineKeyboardButton(text="Cancel", callback_data="cancel_flow"),
            ]
        ]
    )
    text = (
        "⚠️ *GDPR Data Erasure Request*\n\n"
        "This will permanently delete:\n"
        "• Your user profile and Telegram ID\n"
        "• All saved locations and alert preferences\n"
        "• All active movie monitors and watch state\n"
        "• All notification logs\n\n"
        "Are you sure you want to permanently erase your data?"
    )
    if isinstance(event, CallbackQuery):
        await event.message.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)
        await event.answer()
    else:
        await event.answer(text, parse_mode="Markdown", reply_markup=keyboard)


@router.callback_query(F.data == "gdpr_confirm_delete")
async def execute_gdpr_deletion(query: CallbackQuery):
    telegram_id = query.from_user.id
    async with get_db_session() as session:
        wiped = await delete_user_data_gdpr(session, telegram_id)

    if wiped:
        await query.message.edit_text(
            "✅ *All your personal data and active alerts have been permanently erased from TicketNotify.*\n\n"
            "If you ever wish to use the service again, simply send /start.",
            parse_mode="Markdown",
        )
    else:
        await query.message.edit_text("No active records were found for your account.")
    await query.answer()
