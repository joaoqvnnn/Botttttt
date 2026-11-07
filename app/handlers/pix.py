import logging
from datetime import datetime
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import httpx
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
from app.db.payments import (
    attach_mp_data,
    calculate_bonus,
    confirm_payment,
    create_payment_record,
    get_payment_by_id,
    payment_expiration,
)
from app.db.products import get_product
from app.db.users import get_or_create_user


logger = logging.getLogger(__name__)
TZ = ZoneInfo("America/Sao_Paulo")

MP_API = "https://api.mercadopago.com"


# ─────────────────────────────────────────────────────────
# CHAMADAS À API DO MERCADO PAGO
# ─────────────────────────────────────────────────────────


async def _create_mp_pix(
    amount: float, description: str, payer_email: str, external_ref: str
) -> dict:
    headers = {
        "Authorization": f"Bearer {settings.MP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
        "X-Idempotency-Key": external_ref,
    }
    payload = {
        "transaction_amount": float(amount),
        "description": description,
        "payment_method_id": "pix",
        "external_reference": external_ref,
        "payer": {"email": payer_email},
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{MP_API}/v1/payments", json=payload, headers=headers
        )
        resp.raise_for_status()
        return resp.json()


async def _get_mp_payment(mp_payment_id: int) -> dict:
    headers = {"Authorization": f"Bearer {settings.MP_ACCESS_TOKEN}"}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(
            f"{MP_API}/v1/payments/{mp_payment_id}", headers=headers
        )
        resp.raise_for_status()
        return resp.json()


# ─────────────────────────────────────────────────────────
# ESTADO DE ORIGEM (retornar ao contexto correto)
# ─────────────────────────────────────────────────────────


def _set_origin(context, origin: str) -> None:
    context.user_data["pix_origin"] = origin


def _get_origin(context) -> str:
    return context.user_data.get("pix_origin", "menu")


# ─────────────────────────────────────────────────────────
# TELA 1 — ESCOLHA DA FORMA DE RECARGA
# ─────────────────────────────────────────────────────────


async def pix_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback `add_balance` — abre o fluxo único de recarga."""
    query = update.callback_query

    # Detecta origem para retornar depois da recarga
    data = query.data or ""
    if data.startswith("add_balance:"):
        origin = data.split(":", 1)[1]
    else:
        origin = "menu"
    _set_origin(context, origin)

    text = (
        "💳 Selecione a opção desejada para adicionar saldo via PIX!\n\n"
        "🔹 Adicione crédito de forma rápida e segura com PIX.\n"
        "💸 Escolha o valor e faça o pagamento."
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💠 PIX automático", callback_data="pix_start"
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ Voltar", callback_data=f"pix_back:{origin}"
                )
            ],
        ]
    )
    await query.edit_message_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────────────────────────────────────────────
# TELA 2 — PEDIR VALOR (ForceReply)
# ─────────────────────────────────────────────────────────


async def pix_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query

    prompt_msg = await query.message.reply_text(
        "🏦 *RECARGA DE SALDO*\n\n"
        f"🔻 Depósito mínimo: R$ {settings.PIX_MIN_DEPOSIT:.2f}\n"
        f"🎁 Bônus de depósito: {settings.PIX_BONUS_PERCENT:.0f}%\n\n"
        "➡️ Envie o valor que deseja recarregar. Digite apenas números.",
        reply_markup=ForceReply(selective=True),
        parse_mode=ParseMode.MARKDOWN,
    )

    context.user_data["pix_awaiting_value"] = {
        "prompt_message_id": prompt_msg.message_id,
        "origin_message_id": query.message.message_id,
        "origin_chat_id": query.message.chat_id,
    }
    await query.answer()


async def pix_value_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Recebe o valor digitado (MessageHandler)."""
    awaiting = context.user_data.get("pix_awaiting_value")
    if not awaiting:
        return

    context.user_data.pop("pix_awaiting_value", None)

    # Limpa mensagens do fluxo
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

    raw = (update.message.text or "").strip().replace(",", ".")
    try:
        amount = Decimal(raw)
        if amount < Decimal(str(settings.PIX_MIN_DEPOSIT)):
            raise ValueError("below_min")
    except (InvalidOperation, ValueError):
        await context.bot.edit_message_text(
            f"❌ *Valor inválido.*\n\n"
            f"O depósito mínimo é R$ {settings.PIX_MIN_DEPOSIT:.2f}.\n"
            "Digite apenas números (ex: 20 ou 20.50).",
            chat_id=origin_chat,
            message_id=origin_msg,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "↩️ Tentar novamente",
                            callback_data="pix_start",
                        )
                    ]
                ]
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    user = update.effective_user

    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        user_id = db_user.id
        db_email = db_user.username or f"user{user.id}@bellamy.bot"

    bonus = calculate_bonus(amount)
    expires_at = payment_expiration()

    async with SessionLocal() as session:
        payment = await create_payment_record(
            session, user_id, amount, bonus, expires_at
        )
        local_id = payment.id

    external_ref = f"bellamy_pix_{local_id}"

    try:
        mp_resp = await _create_mp_pix(
            amount=float(amount),
            description=f"Recarga Bellamy - Pedido #{local_id}",
            payer_email=db_email,
            external_ref=external_ref,
        )
    except Exception:
        logger.exception("Falha ao criar cobrança PIX no Mercado Pago")
        await context.bot.edit_message_text(
            "❌ *Erro ao gerar o PIX.*\n\n"
            "Tente novamente em instantes ou contate o suporte.",
            chat_id=origin_chat,
            message_id=origin_msg,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "↩️ Voltar", callback_data="pix_start"
                        )
                    ]
                ]
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    mp_id = mp_resp.get("id")
    tdata = (
        mp_resp.get("point_of_interaction", {})
        .get("transaction_data", {})
    )
    qr_code = tdata.get("qr_code")
    qr_base64 = tdata.get("qr_code_base64")
    ticket_url = tdata.get("ticket_url")

    async with SessionLocal() as session:
        await attach_mp_data(
            session, local_id, mp_id, qr_code, qr_base64, ticket_url
        )

    context.user_data["pix_current"] = {
        "local_id": local_id,
        "mp_id": mp_id,
        "amount": float(amount),
        "bonus": float(bonus),
        "qr_code": qr_code,
        "expires_at": expires_at.isoformat(),
    }

    await _render_pix_charge(
        context.bot,
        origin_chat,
        origin_msg,
        amount=float(amount),
        bonus=float(bonus),
        qr_code=qr_code,
        local_id=local_id,
        expires_at=expires_at,
        ticket_url=ticket_url,
    )


# ─────────────────────────────────────────────────────────
# TELA 3 — COBRANÇA PIX (QR + Copia e Cola)
# ─────────────────────────────────────────────────────────


def _fmt_expires(expires_at: datetime) -> str:
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=ZoneInfo("UTC"))
    return expires_at.astimezone(TZ).strftime("%H:%M")


async def _render_pix_charge(
    bot,
    chat_id: int,
    message_id: int,
    amount: float,
    bonus: float,
    qr_code: str | None,
    local_id: int,
    expires_at: datetime,
    ticket_url: str | None = None,
) -> None:
    total = amount + bonus
    text = (
        "💰 *COMPRAR SALDO COM PIX AUTOMÁTICO*\n\n"
        f"⏱ Expira em: {_fmt_expires(expires_at)}\n"
        f"💰 Valor: R$ {amount:.2f}\n"
        f"🎁 Bônus: R$ {bonus:.2f}\n"
        f"💎 Total a receber: R$ {total:.2f}\n"
        f"✨ ID da compra: #{local_id}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "💎 *PIX COPIA E COLA*\n\n"
        f"`{qr_code or '—'}`\n\n"
        "🇧🇷 Após a confirmação do pagamento, seu saldo será atualizado "
        "automaticamente."
    )

    buttons = [
        [
            InlineKeyboardButton(
                "⏳ Aguardando pagamento", callback_data="pix_check"
            )
        ]
    ]
    if ticket_url:
        buttons.append(
            [InlineKeyboardButton("🔗 Abrir QR Code", url=ticket_url)]
        )
    buttons.append(
        [
            InlineKeyboardButton(
                "↩️ Cancelar recarga", callback_data="pix_cancel"
            )
        ]
    )

    await bot.edit_message_text(
        text,
        chat_id=chat_id,
        message_id=message_id,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN,
    )


# ─────────────────────────────────────────────────────────
# AGUARDANDO PAGAMENTO (consulta manual)
# ─────────────────────────────────────────────────────────


async def pix_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    current = context.user_data.get("pix_current")
    if not current:
        await query.answer("⚠️ Cobrança expirada.", show_alert=True)
        return

    await query.answer("🔄 Consultando...")

    try:
        mp_data = await _get_mp_payment(current["mp_id"])
    except Exception:
        logger.exception("Falha ao consultar status do PIX")
        await query.answer("❌ Erro ao consultar. Tente novamente.", show_alert=True)
        return

    status = mp_data.get("status")

    if status != "approved":
        await query.edit_message_text(
            "⏳ *PAGAMENTO NÃO IDENTIFICADO*\n\n"
            "Consultamos nossos sistemas e ainda não identificamos a "
            "confirmação do pagamento.\n\n"
            "Se você já realizou o pagamento, aguarde a atualização bancária "
            "e consulte novamente.",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "🔄 Consultar novamente",
                            callback_data="pix_check",
                        )
                    ],
                    [
                        InlineKeyboardButton(
                            "↩️ Cancelar recarga",
                            callback_data="pix_cancel",
                        )
                    ],
                ]
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Aprovado → credita (idempotente)
    async with SessionLocal() as session:
        payment = await get_payment_by_id(session, current["local_id"])
        if payment is None:
            await query.answer("❌ Cobrança não encontrada.", show_alert=True)
            return
        user, credited = await confirm_payment(session, payment)

    if user is None:
        # Já havia sido creditado (webhook chegou antes)
        async with SessionLocal() as session:
            payment = await get_payment_by_id(session, current["local_id"])
            total = float(payment.total_credited) if payment else 0.0

        await query.edit_message_text(
            "✅ *RECARGA JÁ CONFIRMADA*\n\n"
            f"💎 Valor creditado anteriormente: R$ {total:.2f}",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("↩️ Voltar", callback_data="pix_back:menu")]]
            ),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    await _render_recharge_success(
        query, context, user, current, credited
    )


async def _render_recharge_success(
    query, context, user, current, credited
) -> None:
    origin = _get_origin(context)
    balance = float(user.balance)

    text = (
        "✅ *RECARGA CONFIRMADA!*\n\n"
        "Seu pagamento foi identificado.\n\n"
        f"💎 Valor recebido: R$ {current['amount']:.2f}\n"
        f"🎁 Bônus: R$ {current['bonus']:.2f}\n"
        f"💰 Novo saldo: R$ {balance:.2f}"
    )

    context.user_data.pop("pix_current", None)

    buttons = []
    if origin.startswith("product:"):
        pid = origin.split(":", 1)[1]
        buttons.append(
            [InlineKeyboardButton("🛍️ Voltar ao produto", callback_data=f"product:{pid}")]
        )
    elif origin == "cart":
        buttons.append(
            [InlineKeyboardButton("🧺 Voltar ao carrinho", callback_data="cart")]
        )
    buttons.append(
        [InlineKeyboardButton("🏠 Menu principal", callback_data="back_to_menu")]
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN,
    )


# ─────────────────────────────────────────────────────────
# CANCELAR / VOLTAR
# ─────────────────────────────────────────────────────────


async def pix_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("pix_current", None)
    context.user_data.pop("pix_awaiting_value", None)

    text = (
        "❌ *RECARGA CANCELADA*\n\n"
        "Sua cobrança foi cancelada. Nenhum valor foi debitado."
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🏠 Menu principal", callback_data="back_to_menu"
                )
            ]
        ]
    )
    await update.callback_query.edit_message_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )


async def pix_back(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    data = query.data or ""
    origin = data.split(":", 1)[1] if ":" in data else "menu"
    context.user_data.pop("pix_awaiting_value", None)

    if origin.startswith("product:"):
        pid = origin.split(":", 1)[1]
        from app.handlers.catalog import _render_product_detail_by_id
        # fallback simples: reabre o catálogo
        await query.edit_message_text(
            "↩️ Retornando...",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🛍️ Ver produto", callback_data=f"product:{pid}")]]
            ),
        )
        return
    if origin == "cart":
        await query.edit_message_text(
            "↩️ Retornando ao carrinho...",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("🧺 Carrinho", callback_data="cart")]]
            ),
        )
        return

    await query.edit_message_text(
        "↩️ Voltando ao menu...",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🏠 Menu principal", callback_data="back_to_menu")]]
        ),
    )
