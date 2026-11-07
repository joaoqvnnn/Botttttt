import logging

from sqlalchemy import select
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.config import settings
from app.database import SessionLocal
from app.db.affiliates import register_referral
from app.db.cart import get_cart_count
from app.db.users import get_or_create_user
from app.keyboards.main_menu import lock_screen_keyboard, main_menu_keyboard
from app.utils.texts import get_greeting


logger = logging.getLogger(__name__)

VALID_STATUSES = {"member", "administrator", "creator"}


def _clear_pending_states(context: ContextTypes.DEFAULT_TYPE) -> None:
    for key in (
        "pending_qty",
        "awaiting_qty",
        "pending_purchase",
        "pix_current",
        "pix_awaiting_value",
        "aff_pending_redeem",
        "aff_awaiting_points",
    ):
        context.user_data.pop(key, None)


async def _check_membership(bot, user_id: int) -> bool:
    try:
        channel = await bot.get_chat_member(settings.CHANNEL_ID, user_id)
        group = await bot.get_chat_member(settings.GROUP_ID, user_id)
        return (
            channel.status in VALID_STATUSES
            and group.status in VALID_STATUSES
        )
    except Exception as e:
        logger.warning(f"Falha ao verificar membros: {e}")
        return False


def _lock_screen_text(first_name: str) -> str:
    return (
        "🔒 *ACESSO RESTRITO*\n\n"
        f"Olá, {first_name}!\n\n"
        "Para utilizar nossos serviços, é necessário participar do nosso "
        "grupo e canal oficial.\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "📢 Entre no canal oficial\n"
        "👥 Entre no grupo oficial\n\n"
        "Após entrar nos dois, clique em *Já entrei — Verificar*."
    )


def _welcome_text(
    first_name: str, username: str | None, telegram_id: int, balance: float
) -> str:
    greeting = get_greeting()
    user_display = f"@{username}" if username else first_name
    return (
        f"☀️ *{greeting}, {first_name}!*\n\n"
        "💠 *BELLAMY | DIGITAL STORE*\n\n"
        "Tecnologia, praticidade e agilidade em uma única plataforma.\n\n"
        "⚡ Sistema automatizado\n"
        "💎 Saldo atualizado em tempo real\n"
        "🛒 Catálogo inteligente\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "👤 *SEU PERFIL*\n\n"
        f"➤ Usuário: {user_display}\n"
        f"➤ ID: `{telegram_id}`\n"
        f"➤ Saldo: R$ {balance:.2f}\n\n"
        "👇 Selecione uma opção no menu."
    )


async def _try_register_referral(user, referrer_telegram_id: int) -> None:
    """Registra indicação via /start REFERRER_ID (se válida)."""
    if not settings.AFFILIATE_ENABLED:
        return

    async with SessionLocal() as session:
        new_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        try:
            registered = await register_referral(
                session, referrer_telegram_id, new_user
            )
            if registered:
                logger.info(
                    f"Indicação registrada: user {user.id} via {referrer_telegram_id}"
                )
        except Exception:
            logger.exception("Falha ao registrar indicação")


async def _render_entry(update: Update, bot) -> None:
    user = update.effective_user

    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        balance = float(db_user.balance)
        cart_count = await get_cart_count(session, db_user.id)

    # ⚠️ VERIFICAÇÃO DE CANAL/GRUPO DESATIVADA TEMPORARIAMENTE PARA TESTES
    # Quando criar o canal e o grupo, troque a linha abaixo por:
    # is_member = await _check_membership(bot, user.id)
    is_member = True

    if is_member:
        text = _welcome_text(
            user.first_name, user.username, user.id, balance
        )
        keyboard = main_menu_keyboard(cart_count)
    else:
        text = _lock_screen_text(user.first_name)
        keyboard = lock_screen_keyboard(
            settings.CHANNEL_LINK, settings.GROUP_LINK
        )

    if update.callback_query:
        await update.callback_query.edit_message_text(
            text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )
    else:
        await update.message.reply_text(
            text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )


async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user

    # Processa o parâmetro de indicação (?start=REFERRER_TELEGRAM_ID)
    args = context.args
    if args:
        try:
            referrer_telegram_id = int(args[0])
            if referrer_telegram_id != user.id:
                await _try_register_referral(user, referrer_telegram_id)
        except (ValueError, TypeError):
            pass

    _clear_pending_states(context)
    await _render_entry(update, context.bot)


async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    _clear_pending_states(context)
    await _render_entry(update, context.bot)


async def verify_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = update.effective_user

    is_member = await _check_membership(context.bot, user.id)
    if not is_member:
        await query.answer(
            "❌ Você ainda não entrou no canal e no grupo!", show_alert=True
        )
        return

    await query.answer("✅ Verificado!")
    _clear_pending_states(context)
    await _render_entry(update, context.bot)


async def placeholder_callback(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await update.callback_query.answer("🔄 Em breve")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error("Erro no handler:", exc_info=context.error)
