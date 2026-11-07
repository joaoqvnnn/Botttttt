import logging
import time

from telegram import (
    ForceReply,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Update,
)
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.config import settings
from app.database import SessionLocal
from app.db.affiliates import (
    RedemptionError,
    get_user_affiliate_stats,
    get_user_referrals_paginated,
    redeem_points,
)
from app.db.users import get_or_create_user


logger = logging.getLogger(__name__)

AWAITING_TTL = 300


# ─────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────


def _main_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💎 Trocar pontos por saldo",
                    callback_data="aff_redeem",
                )
            ],
            [
                InlineKeyboardButton(
                    "👥 Meus indicados", callback_data="aff_referrals"
                )
            ],
            [
                InlineKeyboardButton(
                    "📊 Meu desempenho", callback_data="aff_performance"
                )
            ],
            [
                InlineKeyboardButton(
                    "📜 Histórico de recompensas",
                    callback_data="aff_history",
                )
            ],
            [
                InlineKeyboardButton(
                    "📖 Como funciona", callback_data="aff_how"
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ Voltar", callback_data="back_to_menu"
                )
            ],
        ]
    )


def _user_display(first_name: str | None, username: str | None) -> str:
    if first_name:
        return first_name[:24]
    if username:
        return f"@{username}"
    return "Usuário"


# ─────────────────────────────────────────────────────────
# TELA PRINCIPAL
# ─────────────────────────────────────────────────────────


async def affiliates_view(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = query.from_user

    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        stats = await get_user_affiliate_stats(session, db_user.id)

    bot_username = context.bot.username or "bellamy_bot"
    ref_link = f"https://t.me/{bot_username}?start={user.id}"

    text = (
        "◈ *BELLAMY | AFILIADOS*\n\n"
        "Convide pessoas e acumule recompensas através das suas indicações.\n\n"
        f"🏆 Pontos acumulados: {stats['pontos']}\n"
        f"💎 Saldo disponível para resgate: R$ {stats['valor_resgate']:.2f}\n"
        f"👥 Pessoas indicadas: {stats['total_indicados']}\n"
        f"✅ Indicações confirmadas: {stats['confirmados']}\n\n"
        "🔗 *Seu link exclusivo:*\n"
        f"`{ref_link}`"
    )

    await query.edit_message_text(
        text,
        reply_markup=_main_keyboard(),
        parse_mode=ParseMode.MARKDOWN,
    )


# ─────────────────────────────────────────────────────────
# TROCA DE PONTOS
# ─────────────────────────────────────────────────────────


async def affiliates_redeem(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = query.from_user

    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        stats = await get_user_affiliate_stats(session, db_user.id)

    if stats["pontos"] < settings.AFFILIATE_MIN_REDEEM:
        text = (
            "💎 *TROCA DE PONTOS*\n\n"
            f"Você possui *{stats['pontos']} pontos*.\n\n"
            f"O mínimo para resgate é *{settings.AFFILIATE_MIN_REDEEM} pontos*.\n"
            "Continue indicando para acumular mais!"
        )
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "↩️ Voltar", callback_data="affiliates"
                    )
                ]
            ]
        )
        await query.edit_message_text(
            text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )
        return

    text = (
        "💎 *TROCA DE PONTOS*\n\n"
        "Transforme seus pontos acumulados em saldo na carteira Bellamy.\n\n"
        f"🏆 Seus pontos: {stats['pontos']}\n"
        f"💰 Valor disponível: R$ {stats['valor_resgate']:.2f}\n\n"
        f"📊 Conversão: 1 ponto = R$ {settings.AFFILIATE_CONVERSION_RATE:.2f}\n"
        f"🔻 Mínimo: {settings.AFFILIATE_MIN_REDEEM} pontos"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Converter todos os pontos",
                    callback_data="aff_redeem_all",
                )
            ],
            [
                InlineKeyboardButton(
                    "Escolher quantidade", callback_data="aff_redeem_custom"
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ Voltar", callback_data="affiliates"
                )
            ],
        ]
    )
    await query.edit_message_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )


async def affiliates_redeem_all(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = query.from_user

    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        stats = await get_user_affiliate_stats(session, db_user.id)

    points_to_use = stats["pontos"]
    context.user_data["aff_pending_redeem"] = points_to_use

    conversion = settings.AFFILIATE_CONVERSION_RATE
    amount = round(points_to_use * conversion, 2)

    text = (
        "◈ *CONFIRMAR CONVERSÃO*\n\n"
        f"🏆 Pontos utilizados: {points_to_use}\n"
        f"💰 Saldo que receberá: R$ {amount:.2f}\n\n"
        "Deseja confirmar a troca?"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Confirmar troca",
                    callback_data="aff_redeem_confirm",
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ Cancelar", callback_data="aff_redeem_cancel"
                )
            ],
        ]
    )
    await query.edit_message_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )


async def affiliates_redeem_custom_prompt(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query

    prompt_msg = await query.message.reply_text(
        "✏️ *QUANTIDADE PARA CONVERSÃO*\n\n"
        f"💎 Conversão: 1 ponto = R$ {settings.AFFILIATE_CONVERSION_RATE:.2f}\n"
        f"🔻 Mínimo: {settings.AFFILIATE_MIN_REDEEM} pontos\n\n"
        "Digite quantos pontos deseja converter:",
        reply_markup=ForceReply(selective=True),
        parse_mode=ParseMode.MARKDOWN,
    )

    context.user_data["aff_awaiting_points"] = {
        "prompt_message_id": prompt_msg.message_id,
        "origin_message_id": query.message.message_id,
        "origin_chat_id": query.message.chat_id,
        "set_at": time.time(),
    }
    await query.answer()


async def affiliates_redeem_custom_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Handler de texto — recebe quantidade de pontos digitada."""
    awaiting = context.user_data.get("aff_awaiting_points")
    if not awaiting:
        return
    if time.time() - awaiting.get("set_at", 0) > AWAITING_TTL:
        context.user_data.pop("aff_awaiting_points", None)
        return

    context.user_data.pop("aff_awaiting_points", None)

    try:
        await update.message.delete()
    except Exception:
        pass
    try:
        await context.bot.delete_message(
            chat_id=awaiting["origin_chat_id"],
            message_id=awaiting["prompt_message_id"],
        )
    except Exception:
        pass

    origin_chat = awaiting["origin_chat_id"]
    origin_msg = awaiting["origin_message_id"]
    user = update.effective_user

    raw = (update.message.text or "").strip()
    try:
        points_to_use = int(raw)
        if points_to_use <= 0:
            raise ValueError
    except ValueError:
        await context.bot.edit_message_text(
            "❌ *Valor inválido.*\n\nDigite um número inteiro positivo.",
            chat_id=origin_chat,
            message_id=origin_msg,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "↩️ Voltar", callback_data="aff_redeem"
                        )
                    ]
                ]
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        stats = await get_user_affiliate_stats(session, db_user.id)

    if points_to_use > stats["pontos"]:
        await context.bot.edit_message_text(
            f"❌ *Pontos insuficientes.*\n\nVocê tem {stats['pontos']} pontos.",
            chat_id=origin_chat,
            message_id=origin_msg,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "↩️ Voltar", callback_data="aff_redeem"
                        )
                    ]
                ]
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    if points_to_use < settings.AFFILIATE_MIN_REDEEM:
        await context.bot.edit_message_text(
            f"❌ *Mínimo de {settings.AFFILIATE_MIN_REDEEM} pontos.*",
            chat_id=origin_chat,
            message_id=origin_msg,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "↩️ Voltar", callback_data="aff_redeem"
                        )
                    ]
                ]
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    context.user_data["aff_pending_redeem"] = points_to_use
    amount = round(
        points_to_use * settings.AFFILIATE_CONVERSION_RATE, 2
    )

    text = (
        "◈ *CONFIRMAR CONVERSÃO*\n\n"
        f"🏆 Pontos utilizados: {points_to_use}\n"
        f"💰 Saldo que receberá: R$ {amount:.2f}\n\n"
        "Deseja confirmar a troca?"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Confirmar troca",
                    callback_data="aff_redeem_confirm",
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ Cancelar", callback_data="aff_redeem_cancel"
                )
            ],
        ]
    )
    await context.bot.edit_message_text(
        text,
        chat_id=origin_chat,
        message_id=origin_msg,
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )


async def affiliates_redeem_confirm(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = query.from_user

    points_to_use = context.user_data.get("aff_pending_redeem")
    if not points_to_use:
        await query.answer("⚠️ Sessão expirada.", show_alert=True)
        return

    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        try:
            result = await redeem_points(session, db_user.id, points_to_use)
        except RedemptionError as e:
            await query.answer(e.message, show_alert=True)
            return
        except Exception:
            logger.exception("Falha ao trocar pontos")
            await query.answer("❌ Erro ao processar.", show_alert=True)
            return

    context.user_data.pop("aff_pending_redeem", None)

    text = (
        "✅ *CONVERSÃO REALIZADA!*\n\n"
        "Seus pontos foram convertidos com sucesso.\n\n"
        f"💎 Saldo adicionado: R$ {result['amount_credited']:.2f}\n"
        f"🏆 Pontos utilizados: {result['points_used']}\n"
        f"💰 Novo saldo: R$ {result['new_balance']:.2f}\n\n"
        f"🆔 Operação: #{result['redemption_id']}"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💎 Minha carteira", callback_data="profile"
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ Voltar aos afiliados", callback_data="affiliates"
                )
            ],
        ]
    )
    await query.edit_message_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )


async def affiliates_redeem_cancel(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    context.user_data.pop("aff_pending_redeem", None)
    context.user_data.pop("aff_awaiting_points", None)
    # Reaproveita o handler principal
    await affiliates_view(update, context)


# ─────────────────────────────────────────────────────────
# MEUS INDICADOS
# ─────────────────────────────────────────────────────────


async def _render_referrals_list(query, user, page: int) -> None:
    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        items, total, total_pages, current_page = (
            await get_user_referrals_paginated(
                session, db_user.id, page, settings.AFFILIATE_PER_PAGE
            )
        )
        stats = await get_user_affiliate_stats(session, db_user.id)

    if total == 0:
        text = (
            "👥 *MEUS INDICADOS*\n\n"
            "Você ainda não possui indicados.\n\n"
            "Compartilhe seu link exclusivo para começar a indicar!"
        )
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "↩️ Voltar", callback_data="affiliates"
                    )
                ]
            ]
        )
        await query.edit_message_text(
            text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )
        return

    lines = [
        "👥 *MEUS INDICADOS*\n",
        f"👥 Total de indicados: {stats['total_indicados']}",
        f"✅ Confirmados: {stats['confirmados']}",
        f"⏳ Pendentes: {stats['pendentes']}\n",
        f"📄 Página {current_page}/{total_pages}:\n",
    ]
    for ref, referred in items:
        icon = "✅" if ref.status == "confirmed" else "⏳"
        name = _user_display(referred.first_name, referred.username)
        date_str = ref.created_at.strftime("%d/%m/%Y") if ref.created_at else "—"
        lines.append(f"{icon} {name} — {date_str}")

    text = "\n".join(lines)

    nav: list[InlineKeyboardButton] = []
    if current_page > 1:
        nav.append(
            InlineKeyboardButton(
                "⬅️ Anterior",
                callback_data=f"aff_refs_page:{current_page - 1}",
            )
        )
    if current_page < total_pages:
        nav.append(
            InlineKeyboardButton(
                "Próxima ➡️",
                callback_data=f"aff_refs_page:{current_page + 1}",
            )
        )

    rows: list[list[InlineKeyboardButton]] = []
    if nav:
        rows.append(nav)
    rows.append(
        [InlineKeyboardButton("↩️ Voltar", callback_data="affiliates")]
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN,
    )


async def affiliates_referrals(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    await _render_referrals_list(query, query.from_user, page=1)


async def affiliates_referrals_page(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    data = query.data or ""
    try:
        page = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        page = 1
    await _render_referrals_list(query, query.from_user, page=page)


# ─────────────────────────────────────────────────────────
# MEU DESEMPENHO
# ─────────────────────────────────────────────────────────


async def affiliates_performance(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = query.from_user

    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        stats = await get_user_affiliate_stats(session, db_user.id)

    text = (
        "📊 *MEU DESEMPENHO*\n\n"
        f"🏆 Pontuação acumulada: {stats['pontos']}\n"
        f"👥 Total de indicações: {stats['total_indicados']}\n"
        f"🛒 Compras originadas: {stats['confirmados']}\n"
        f"💎 Recompensas recebidas: R$ {stats['saldo_recebido']:.2f}\n"
        f"📈 Taxa de conversão: {stats['taxa_conversao']:.1f}%"
    )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("↩️ Voltar", callback_data="affiliates")]]
    )
    await query.edit_message_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────────────────────────────────────────────
# HISTÓRICO DE RECOMPENSAS
# ─────────────────────────────────────────────────────────


async def affiliates_history(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = query.from_user

    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        stats = await get_user_affiliate_stats(session, db_user.id)

    text = (
        "📜 *HISTÓRICO DE RECOMPENSAS*\n\n"
        f"🏆 Pontos recebidos: {stats['pontos_recebidos']}\n"
        f"💎 Pontos convertidos: {stats['pontos_convertidos']}\n"
        f"💰 Saldo recebido: R$ {stats['saldo_recebido']:.2f}"
    )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("↩️ Voltar", callback_data="affiliates")]]
    )
    await query.edit_message_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────────────────────────────────────────────
# COMO FUNCIONA
# ─────────────────────────────────────────────────────────


async def affiliates_how_it_works(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query

    text = (
        "📖 *COMO FUNCIONA O PROGRAMA?*\n\n"
        "1. Compartilhe seu link exclusivo.\n"
        "2. Novos usuários entram através dele.\n"
        "3. O sistema identifica as indicações.\n"
        "4. Quando as condições forem cumpridas, você recebe pontos.\n"
        "5. Troque seus pontos por saldo na carteira.\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "📋 *Regras atuais*\n\n"
        f"🏆 Pontos por indicação confirmada: {settings.AFFILIATE_POINTS_PER_REFERRAL}\n"
        f"💎 Conversão: 1 ponto = R$ {settings.AFFILIATE_CONVERSION_RATE:.2f}\n"
        f"🔻 Mínimo para resgate: {settings.AFFILIATE_MIN_REDEEM} pontos\n\n"
        "✅ A indicação é confirmada quando o indicado realiza a primeira compra."
    )
    keyboard = InlineKeyboardMarkup(
        [[InlineKeyboardButton("↩️ Voltar", callback_data="affiliates")]]
    )
    await query.edit_message_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )
