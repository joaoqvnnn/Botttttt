import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.config import settings
from app.database import SessionLocal
from app.db.orders import (
    InsufficientBalance,
    NoCredentials,
    OutOfStock,
    count_available_credentials,
    execute_purchase,
)
from app.db.products import get_product
from app.db.users import get_or_create_user


logger = logging.getLogger(__name__)
TZ = ZoneInfo("America/Sao_Paulo")


# ─────────────────────────────────────────────────────────
# KEYBOARDS
# ─────────────────────────────────────────────────────────


def _confirmation_keyboard(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Confirmar compra",
                    callback_data=f"confirm_buy:{product_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ Cancelar",
                    callback_data=f"cancel_buy:{product_id}",
                )
            ],
        ]
    )


def _insufficient_keyboard(product_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "💎 Adicionar saldo", callback_data="add_balance"
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ Voltar", callback_data=f"product:{product_id}"
                )
            ],
        ]
    )


# ─────────────────────────────────────────────────────────
# BUY NOW — do detalhe do produto
# ─────────────────────────────────────────────────────────


async def buy_now(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback `buy_now:{id}` — inicia compra normal (1 unidade)."""
    query = update.callback_query
    user = update.effective_user

    data = query.data or ""
    try:
        product_id = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        await query.answer("❌ Produto inválido.")
        return

    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        product = await get_product(session, product_id)
        if product is None or not product.is_active:
            await query.answer("❌ Produto indisponível.", show_alert=True)
            return

        available = await count_available_credentials(session, product_id)
        if available < 1 or product.stock < 1:
            if product.stock > 0 and available < 1:
                product.stock = 0
                await session.commit()
            await query.answer(
                "⚠️ Produto esgotado no momento.", show_alert=True
            )
            return

        balance = float(db_user.balance)
        price = float(product.price)
        product_name = product.name

    # Saldo insuficiente → tela própria
    if balance < price:
        needed = price - balance
        text = (
            "⚠️ *SALDO INSUFICIENTE*\n\n"
            "Não foi possível continuar com sua compra.\n\n"
            f"💰 Valor que falta: R$ {needed:.2f}\n\n"
            "Adicione saldo à sua carteira e tente novamente."
        )
        await query.edit_message_text(
            text,
            reply_markup=_insufficient_keyboard(product_id),
            parse_mode=ParseMode.MARKDOWN,
        )
        return

    # Guarda intenção para a confirmação
    context.user_data["pending_purchase"] = {
        "product_id": product_id,
        "product_name": product_name,
        "quantity": 1,
        "unit_price": price,
        "total": price,
    }

    text = (
        "🛍️ *CONFIRMAÇÃO DA COMPRA*\n\n"
        "Seu pedido está pronto para confirmação!\n\n"
        f"◈ Produto: *{product_name}*\n"
        "◈ Quantidade: 1\n"
        f"◈ Valor unitário: R$ {price:.2f}\n"
        f"◈ Total: R$ {price:.2f}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        f"💎 Saldo atual: R$ {balance:.2f}\n"
        f"💰 Saldo após a compra: R$ {balance - price:.2f}\n\n"
        "Deseja confirmar seu pedido?"
    )
    await query.edit_message_text(
        text,
        reply_markup=_confirmation_keyboard(product_id),
        parse_mode=ParseMode.MARKDOWN,
    )


# ─────────────────────────────────────────────────────────
# CONFIRMAR — executa transação atômica
# ─────────────────────────────────────────────────────────


async def confirm_buy(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Callback `confirm_buy:{id}` — executa a compra."""
    query = update.callback_query
    user = update.effective_user

    pending = context.user_data.get("pending_purchase")
    if not pending:
        await query.answer(
            "⚠️ Sessão expirada. Abra o produto novamente.", show_alert=True
        )
        return

    product_id = pending["product_id"]
    error = None
    result = None
    needed_missing = 0.0

    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        try:
            result = await execute_purchase(
                session, db_user.id, product_id, quantity=1
            )
        except InsufficientBalance as e:
            error = "insufficient"
            needed_missing = float(e.needed)
        except (OutOfStock, NoCredentials):
            error = "out_of_stock"
        except Exception:
            logger.exception("Falha ao processar compra")
            error = "unknown"

    if error == "insufficient":
        text = (
            "⚠️ *SALDO INSUFICIENTE*\n\n"
            "Não foi possível concluir a compra.\n\n"
            f"💰 Valor que falta: R$ {needed_missing:.2f}\n\n"
            "Adicione saldo à sua carteira e tente novamente."
        )
        await query.edit_message_text(
            text,
            reply_markup=_insufficient_keyboard(product_id),
            parse_mode=ParseMode.MARKDOWN,
        )
        return
    if error == "out_of_stock":
        await query.answer(
            "⚠️ Produto esgotado no momento.", show_alert=True
        )
        return
    if error == "unknown":
        await query.answer(
            "❌ Erro ao processar. Tente novamente.", show_alert=True
        )
        return

    # Sucesso
    context.user_data["last_purchase"] = {
        "order_id": result["order_id"],
        "product_name": result["product_name"],
        "quantity": result["quantity"],
        "total": result["total"],
        "balance_after": result["balance_after"],
        "deliveries": result["deliveries"],
        "purchased_at": result["purchased_at"].isoformat(),
        "revealed": False,
    }
    context.user_data.pop("pending_purchase", None)

    await _render_success(query, context, revealed=False)


# ─────────────────────────────────────────────────────────
# TELA DE SUCESSO + TOGGLE DE CREDENCIAIS
# ─────────────────────────────────────────────────────────


async def _render_success(query, context, revealed: bool) -> None:
    last = context.user_data.get("last_purchase")
    if not last:
        await query.answer("⚠️ Sessão expirada.", show_alert=True)
        return

    last["revealed"] = revealed

    # Data localizada
    try:
        purchased_at = datetime.fromisoformat(last["purchased_at"])
        if purchased_at.tzinfo is None:
            purchased_at = purchased_at.replace(tzinfo=ZoneInfo("UTC"))
        date_str = purchased_at.astimezone(TZ).strftime("%d/%m/%Y às %H:%M")
    except Exception:
        date_str = "—"

    # Bloco de credenciais
    if revealed:
        lines = []
        for i, d in enumerate(last["deliveries"], start=1):
            prefix = f"#{i}\n" if len(last["deliveries"]) > 1 else ""
            lines.append(
                f"{prefix}📧 E-mail: `{d['email']}`\n"
                f"🔑 Senha: `{d['password']}`"
            )
        creds_block = "\n\n".join(lines)
        reveal_text = "🔒 Desativar visualização"
        reveal_cb = "hide_creds"
    else:
        creds_block = "📧 E-mail: ••••••••••••\n🔑 Senha: ••••••••••••"
        reveal_text = "🔓 Ativar visualização"
        reveal_cb = "reveal_creds"

    text = (
        "✅ *COMPRA CONCLUÍDA!*\n\n"
        "Seu pedido foi confirmado e seus dados de acesso estão disponíveis.\n\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📦 Produto: *{last['product_name']}*\n"
        f"🆔 Pedido: #{last['order_id']}\n"
        f"📅 Data: {date_str}\n\n"
        "🔐 *DADOS DE ACESSO*\n\n"
        f"{creds_block}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "💡 Seus dados estão protegidos. Utilize o botão abaixo para visualizar."
    )

    buttons = [
        [InlineKeyboardButton(reveal_text, callback_data=reveal_cb)],
    ]

    # Botão "Ativar diretamente" — URL configurável, com suporte a {order_id}
    activation_url = (settings.ACTIVATION_URL or "").strip()
    if activation_url:
        url = activation_url.replace("{order_id}", str(last["order_id"]))
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
        [InlineKeyboardButton("🏠 Menu principal", callback_data="back_to_menu")]
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(buttons),
        parse_mode=ParseMode.MARKDOWN,
    )


async def reveal_creds(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await _render_success(update.callback_query, context, revealed=True)


async def hide_creds(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await _render_success(update.callback_query, context, revealed=False)


async def activation_missing(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await update.callback_query.answer(
        "⚠️ Link de ativação não configurado pelo administrador.",
        show_alert=True,
    )


# ─────────────────────────────────────────────────────────
# CANCELAR
# ─────────────────────────────────────────────────────────


async def cancel_buy(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    context.user_data.pop("pending_purchase", None)

    text = (
        "❌ *COMPRA CANCELADA*\n\n"
        "Seu pedido foi cancelado e nenhuma cobrança foi realizada."
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
    await query.edit_message_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )
