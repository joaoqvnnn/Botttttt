import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.config import settings
from app.database import SessionLocal
from app.db.cart import clear_cart, get_cart_with_products
from app.db.orders import (
    InsufficientBalance,
    NoCredentials,
    OutOfStock,
    execute_cart_purchase,
)
from app.db.users import get_or_create_user


logger = logging.getLogger(__name__)
TZ = ZoneInfo("America/Sao_Paulo")


# ─────────────────────────────────────────────────────────
# VISUALIZAR CARRINHO
# ─────────────────────────────────────────────────────────


async def cart_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    user = query.from_user

    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        items = await get_cart_with_products(session, db_user.id)
        balance = float(db_user.balance)

    if not items:
        text = (
            "🧺 *CARRINHO VAZIO*\n\n"
            "Seu carrinho está vazio.\n\n"
            "Adicione produtos para começar."
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
                        "↩️ Voltar", callback_data="back_to_menu"
                    )
                ],
            ]
        )
        await query.edit_message_text(
            text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )
        return

    lines = []
    total = 0.0
    total_items = 0
    for cart_item, product in items:
        subtotal = float(product.price) * cart_item.quantity
        total += subtotal
        total_items += cart_item.quantity
        lines.append(
            f"• *{product.name}*\n"
            f"  {cart_item.quantity} × R$ {float(product.price):.2f} = R$ {subtotal:.2f}"
        )
    products_block = "\n\n".join(lines)

    text = (
        "◈ *BELLAMY | MEU CARRINHO*\n\n"
        f"👤 {user.first_name} (`{user.id}`)\n\n"
        f"{products_block}\n\n"
        f"📦 Quantidade de itens: {total_items}\n"
        f"💰 Total: R$ {total:.2f}\n"
        f"💎 Saldo: R$ {balance:.2f}"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🛒 Comprar", callback_data="cart_buy")
            ],
            [
                InlineKeyboardButton(
                    "🗑️ Limpar carrinho", callback_data="cart_clear"
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ Cancelar e voltar", callback_data="back_to_menu"
                )
            ],
        ]
    )
    await query.edit_message_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────────────────────────────────────────────
# COMPRAR → CONFIRMAÇÃO
# ─────────────────────────────────────────────────────────


async def cart_buy_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = query.from_user

    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        items = await get_cart_with_products(session, db_user.id)
        balance = float(db_user.balance)

    if not items:
        await query.answer("⚠️ Carrinho vazio.", show_alert=True)
        return

    total = sum(float(p.price) * c.quantity for c, p in items)
    total_items = sum(c.quantity for c, p in items)

    if balance < total:
        needed = total - balance
        text = (
            "⚠️ *SALDO INSUFICIENTE*\n\n"
            "Não foi possível continuar com sua compra.\n\n"
            f"💰 Valor que falta: R$ {needed:.2f}\n\n"
            "Adicione saldo à sua carteira e tente novamente."
        )
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "💎 Adicionar saldo",
                        callback_data="add_balance",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "↩️ Voltar", callback_data="cart"
                    )
                ],
            ]
        )
        await query.edit_message_text(
            text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )
        return

    lines = []
    for cart_item, product in items:
        subtotal = float(product.price) * cart_item.quantity
        lines.append(
            f"• {product.name} x{cart_item.quantity} = R$ {subtotal:.2f}"
        )

    text = (
        "🛍️ *CONFIRMAÇÃO DO CARRINHO*\n\n"
        "Confira seu pedido:\n\n"
        f"{chr(10).join(lines)}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        f"📦 Total de itens: {total_items}\n"
        f"💰 Valor total: R$ {total:.2f}\n"
        f"💎 Saldo atual: R$ {balance:.2f}\n"
        f"💳 Saldo após compra: R$ {balance - total:.2f}"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Confirmar compra", callback_data="cart_confirm"
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ Cancelar", callback_data="cart"
                )
            ],
        ]
    )
    await query.edit_message_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────────────────────────────────────────────
# CONFIRMAR → EXECUTA → ENTREGA
# ─────────────────────────────────────────────────────────


async def cart_confirm_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = query.from_user

    await query.edit_message_text(
        "⏳ *PROCESSANDO SEU PEDIDO*\n\n"
        "Aguarde enquanto o sistema confirma a operação.",
        parse_mode=ParseMode.MARKDOWN,
    )

    error = None
    needed = 0.0
    result = None

    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        try:
            result = await execute_cart_purchase(session, db_user.id)
        except InsufficientBalance as e:
            await session.rollback()
            error = "insufficient"
            needed = float(e.needed)
        except (OutOfStock, NoCredentials):
            await session.rollback()
            error = "out_of_stock"
        except Exception:
            await session.rollback()
            logger.exception("Falha ao processar compra em carrinho")
            error = "unknown"

    if error:
        if error == "insufficient":
            text = (
                "⚠️ *SALDO INSUFICIENTE*\n\n"
                f"💰 Valor que falta: R$ {needed:.2f}"
            )
        elif error == "out_of_stock":
            text = "⚠️ *Um ou mais produtos estão esgotados.*"
        else:
            text = "❌ *Erro ao processar.* Tente novamente."
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "↩️ Voltar ao carrinho", callback_data="cart"
                    )
                ]
            ]
        )
        await query.edit_message_text(
            text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )
        return

    context.user_data["last_cart_purchase"] = {
        "order_id": result["order_id"],
        "total": result["total"],
        "balance_after": result["balance_after"],
        "items": result["items"],
        "purchased_at": result["purchased_at"].isoformat(),
        "revealed": False,
    }

    await _render_cart_delivery(query, context, revealed=False)


async def _render_cart_delivery(query, context, revealed: bool) -> None:
    last = context.user_data.get("last_cart_purchase")
    if not last:
        await query.answer("⚠️ Sessão expirada.", show_alert=True)
        return

    last["revealed"] = revealed

    try:
        purchased_at = datetime.fromisoformat(last["purchased_at"])
        if purchased_at.tzinfo is None:
            purchased_at = purchased_at.replace(tzinfo=ZoneInfo("UTC"))
        date_str = purchased_at.astimezone(TZ).strftime("%d/%m/%Y às %H:%M")
    except Exception:
        date_str = "—"

    total_items = sum(item["quantity"] for item in last["items"])

    sections = []
    for item in last["items"]:
        if revealed:
            inner = [
                f"#{i}\n📧 E-mail: `{d['email']}`\n🔑 Senha: `{d['password']}`"
                for i, d in enumerate(item["deliveries"], start=1)
            ]
        else:
            inner = [
                f"#{i}\n📧 E-mail: ••••••••••••\n🔑 Senha: ••••••••••••"
                for i in range(1, len(item["deliveries"]) + 1)
            ]
        sections.append(
            f"*{item['product_name']}* (x{item['quantity']})\n\n"
            + "\n\n".join(inner)
        )
    creds_block = "\n\n━━━\n\n".join(sections)

    if revealed:
        reveal_text = "🔒 Desativar visualização"
        reveal_cb = "cart_hide_creds"
    else:
        reveal_text = "🔐 Visualizar acessos"
        reveal_cb = "cart_reveal_creds"

    text = (
        "✅ *COMPRA CONCLUÍDA!*\n\n"
        f"📦 Total de itens: {total_items}\n"
        f"💰 Total pago: R$ {last['total']:.2f}\n"
        f"💎 Saldo restante: R$ {last['balance_after']:.2f}\n"
        f"🆔 Pedido: #{last['order_id']}\n"
        f"📅 Data: {date_str}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🔐 *SEUS DADOS DE ACESSO*\n\n"
        f"{creds_block}"
    )

    buttons = [[InlineKeyboardButton(reveal_text, callback_data=reveal_cb)]]

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


async def cart_reveal_creds(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await _render_cart_delivery(update.callback_query, context, revealed=True)


async def cart_hide_creds(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await _render_cart_delivery(update.callback_query, context, revealed=False)


# ─────────────────────────────────────────────────────────
# LIMPAR CARRINHO
# ─────────────────────────────────────────────────────────


async def cart_clear_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    user = query.from_user

    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        await clear_cart(session, db_user.id)

    text = (
        "🗑️ *CARRINHO LIMPO*\n\n"
        "Seu carrinho foi esvaziado com sucesso."
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
