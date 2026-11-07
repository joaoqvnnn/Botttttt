import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.config import settings
from app.database import SessionLocal
from app.db.subscriptions import (
    compute_status,
    get_subscription_details,
    get_user_subscriptions_paginated,
)
from app.db.users import get_or_create_user


logger = logging.getLogger(__name__)
TZ = ZoneInfo("America/Sao_Paulo")

STATUS_LABEL = {
    "ativa": "🟢 Ativa",
    "expirada": "⚪ Expirada",
    "finalizada": "⚪ Finalizada",
}


def _fmt_date(dt: datetime | None) -> str:
    if dt is None:
        return "Sem expiração"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(TZ).strftime("%d/%m/%Y")


# ─────────────────────────────────────────────────────────
# LISTAGEM
# ─────────────────────────────────────────────────────────


async def _render_subscriptions_list(query, user, page: int) -> None:
    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        items, stats, total_pages, current_page = (
            await get_user_subscriptions_paginated(
                session, db_user.id, page, settings.SUBSCRIPTIONS_PER_PAGE
            )
        )

    if stats["total"] == 0:
        text = (
            "📦 *Você ainda não possui nenhuma assinatura.*\n\n"
            "Adquira um produto para começar!"
        )
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "🛍️ Ver produtos", callback_data="catalog"
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
        return

    text = (
        "◈ *BELLAMY | MINHAS ASSINATURAS*\n\n"
        f"📦 Assinaturas cadastradas: {stats['total']}\n"
        f"🟢 Ativas: {stats['ativas']}\n"
        f"⚪ Finalizadas: {stats['finalizadas']}\n\n"
        "Selecione uma assinatura abaixo:"
    )

    buttons: list[list[InlineKeyboardButton]] = []
    for delivery, product, _order in items:
        status = compute_status(delivery)
        label = f"{STATUS_LABEL[status]} · {product.name}"
        buttons.append(
            [
                InlineKeyboardButton(
                    label, callback_data=f"sub_detail:{delivery.id}"
                )
            ]
        )

    nav: list[InlineKeyboardButton] = []
    if current_page > 1:
        nav.append(
            InlineKeyboardButton(
                "⬅️ Anterior",
                callback_data=f"sub_page:{current_page - 1}",
            )
        )
    if current_page < total_pages:
        nav.append(
            InlineKeyboardButton(
                "Próxima ➡️",
                callback_data=f"sub_page:{current_page + 1}",
            )
        )
    if nav:
        buttons.append(nav)

    buttons.append(
        [
            InlineKeyboardButton(
                "↩️ Voltar ao perfil", callback_data="back_to_profile"
            )
        ]
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN,
    )


async def subscriptions_view(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    context.user_data["subs_page"] = 1
    await _render_subscriptions_list(query, query.from_user, page=1)


async def subscriptions_page(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    data = query.data or ""
    try:
        page = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        page = 1
    context.user_data["subs_page"] = page
    await _render_subscriptions_list(query, query.from_user, page=page)


# ─────────────────────────────────────────────────────────
# DETALHE
# ─────────────────────────────────────────────────────────


async def _render_subscription_detail(
    query, user, delivery_id: int, revealed: bool
) -> None:
    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        row = await get_subscription_details(session, db_user.id, delivery_id)

    if row is None:
        await query.answer("❌ Assinatura não encontrada.", show_alert=True)
        return

    delivery, product, order = row
    status = compute_status(delivery)

    acquired = delivery.created_at
    if acquired.tzinfo is None:
        acquired = acquired.replace(tzinfo=ZoneInfo("UTC"))
    acquired_str = acquired.astimezone(TZ).strftime("%d/%m/%Y às %H:%M")
    validade_str = _fmt_date(delivery.expires_at)

    if revealed:
        creds_block = (
            f"📧 E-mail: `{delivery.email}`\n"
            f"🔑 Senha: `{delivery.password}`"
        )
        reveal_text = "🔒 Desativar visualização"
        reveal_cb = f"sub_hide:{delivery.id}"
    else:
        creds_block = "📧 E-mail: ••••••••••••\n🔑 Senha: ••••••••••••"
        reveal_text = "🔓 Visualizar acesso"
        reveal_cb = f"sub_reveal:{delivery.id}"

    text = (
        "◈ *DETALHES DA ASSINATURA*\n\n"
        f"📦 Produto: *{product.name}*\n"
        f"🆔 Pedido: #{order.id}\n"
        f"📅 Aquisição: {acquired_str}\n"
        f"⏳ Validade: {validade_str}\n"
        f"📌 Status: {STATUS_LABEL[status]}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🔐 *DADOS DE ACESSO*\n\n"
        f"{creds_block}"
    )

    buttons = [[InlineKeyboardButton(reveal_text, callback_data=reveal_cb)]]

    activation_url = (settings.ACTIVATION_URL or "").strip()
    if activation_url:
        url = activation_url.replace("{order_id}", str(order.id))
        buttons.append(
            [InlineKeyboardButton("🌐 Ativar diretamente", url=url)]
        )
    else:
        buttons.append(
            [
                InlineKeyboardButton(
                    "🌐 Ativar diretamente",
                    callback_data="activation_missing",
                )
            ]
        )

    buttons.append(
        [
            InlineKeyboardButton(
                "↩️ Voltar às assinaturas", callback_data="profile_subs"
            )
        ]
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN,
    )


async def subscription_detail(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    data = query.data or ""
    try:
        delivery_id = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        await query.answer("❌ Assinatura inválida.")
        return
    await _render_subscription_detail(
        query, query.from_user, delivery_id, revealed=False
    )


async def subscription_reveal(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    data = query.data or ""
    try:
        delivery_id = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        return
    await _render_subscription_detail(
        query, query.from_user, delivery_id, revealed=True
    )


async def subscription_hide(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    data = query.data or ""
    try:
        delivery_id = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        return
    await _render_subscription_detail(
        query, query.from_user, delivery_id, revealed=False
    )
