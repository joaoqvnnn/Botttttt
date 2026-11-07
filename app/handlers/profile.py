import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.database import SessionLocal
from app.db.profile import get_profile_stats, get_user_transactions
from app.db.users import get_or_create_user
from app.utils.pdf import generate_history_pdf


logger = logging.getLogger(__name__)


def _profile_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📄 Histórico de movimentações",
                    callback_data="profile_history",
                )
            ],
            [
                InlineKeyboardButton(
                    "💎 Adicionar saldo", callback_data="add_balance"
                )
            ],
            [
                InlineKeyboardButton(
                    "📺 Minhas assinaturas", callback_data="profile_subs"
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ Voltar", callback_data="back_to_menu"
                )
            ],
        ]
    )


async def _render_profile(query, user, bot) -> None:
    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        stats = await get_profile_stats(session, db_user.id)

    bot_username = bot.username or "bellamy_bot"
    ref_link = f"https://t.me/{bot_username}?start={user.id}"
    username_str = f"@{user.username}" if user.username else "—"

    text = (
        "◈ *BELLAMY | MEU PERFIL*\n\n"
        f"👤 {user.first_name}\n"
        f"💠 {username_str}\n"
        f"🆔 `{user.id}`\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "💎 *CARTEIRA*\n\n"
        f"Saldo disponível: R$ {stats['saldo']:.2f}\n\n"
        "🛒 *ATIVIDADES*\n\n"
        f"Compras realizadas: {stats['total_compras']}\n"
        f"Total em recargas: R$ {stats['total_recargas']:.2f}\n"
        f"Gift Cards resgatados: R$ {stats['total_gifts']:.2f}\n\n"
        "⌁ *INDICAÇÕES*\n\n"
        f"Pontos: {stats['pontos_indicacao']}\n"
        f"Indicados: {stats['total_indicados']}\n\n"
        "🔗 *Seu link:*\n"
        f"`{ref_link}`"
    )

    await query.edit_message_text(
        text,
        reply_markup=_profile_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )


async def profile_view(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await _render_profile(query, query.from_user, context.bot)


async def back_to_profile(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await _render_profile(query, query.from_user, context.bot)


# ─────────────────────────────────────────────────────────
# HISTÓRICO
# ─────────────────────────────────────────────────────────


async def profile_history(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = query.from_user

    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        stats = await get_profile_stats(session, db_user.id)

    text = (
        "◈ *BELLAMY | HISTÓRICO*\n\n"
        "Confira suas movimentações.\n\n"
        f"💰 Compras: {stats['total_compras']}\n"
        f"💎 Recargas: R$ {stats['total_recargas']:.2f}\n"
        f"🎁 Gift Cards: R$ {stats['total_gifts']:.2f}\n"
        f"💸 Saques: R$ {stats['total_saques']:.2f}"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "📄 Gerar histórico em PDF",
                    callback_data="history_pdf",
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ Voltar ao perfil",
                    callback_data="back_to_profile",
                )
            ],
        ]
    )
    await query.edit_message_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )


async def generate_pdf_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = query.from_user

    await query.answer("⏳ Gerando PDF...", show_alert=False)

    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        transactions = await get_user_transactions(session, db_user.id)
        stats = await get_profile_stats(session, db_user.id)
        balance = float(db_user.balance)
        user_id = db_user.id
        username = db_user.username
        first_name = db_user.first_name or "Usuário"

    pdf_buffer = generate_history_pdf(
        user_id=user_id,
        telegram_id=user.id,
        username=username,
        first_name=first_name,
        balance=balance,
        transactions=transactions,
    )

    filename = f"bellamy_historico_{user.id}.pdf"
    await query.message.reply_document(
        document=pdf_buffer,
        filename=filename,
        caption=(
            "📄 *Seu histórico de movimentações*\n\n"
            f"💎 Saldo atual: R$ {balance:.2f}"
        ),
        parse_mode=ParseMode.MARKDOWN,
    )
