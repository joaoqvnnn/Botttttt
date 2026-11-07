import logging
import time
from datetime import datetime
from zoneinfo import ZoneInfo

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
from app.db.orders import (
    InsufficientBalance,
    NoCredentials,
    OutOfStock,
    execute_purchase,
)
from app.db.products import get_product
from app.db.users import get_or_create_user


logger = logging.getLogger(__name__)
TZ = ZoneInfo("America/Sao_Paulo")

SUGGESTIONS = [1, 2, 3, 5, 10]
AWAITING_TTL = 300  # 5 minutos


# ─────────────────────────────────────────────────────────
# TELA DE OPÇÕES DE QUANTIDADE
# ─────────────────────────────────────────────────────────


async def _render_qty_options(query, product_id: int) -> None:
    user = query.from_user
    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        product = await get_product(session, product_id)
        if product is None or not product.is_active:
            await query.answer("❌ Produto indisponível.", show_alert=True)
            return
        if product.stock < 1:
            await query.answer("⚠️ Produto esgotado.", show_alert=True)
            return
        balance = float(db_user.balance)
        stock = product.stock
        name = product.name
        price = float(product.price)

    text = (
        "🔢 *COMPRA POR QUANTIDADE*\n\n"
        f"📦 Produto: *{name}*\n"
        f"💰 Valor unitário: R$ {price:.2f}\n"
        f"💎 Seu saldo: R$ {balance:.2f}\n"
        f"📦 Disponível: {stock}\n\n"
        "Quantas unidades deseja comprar?"
    )

    sugg = [s for s in SUGGESTIONS if s <= stock]
    rows: list[list[InlineKeyboardButton]] = []
    if sugg:
        rows.append(
            [
                InlineKeyboardButton(
                    str(s), callback_data=f"qty_select:{product_id}:{s}"
                )
                for s in sugg
            ]
        )
    rows.append(
        [
            InlineKeyboardButton(
                "✏️ Digitar quantidade",
                callback_data=f"qty_custom:{product_id}",
            )
        ]
    )
    rows.append(
        [
            InlineKeyboardButton(
                "↩️ Voltar", callback_data=f"product:{product_id}"
            )
        ]
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.MARKDOWN,
    )


async def buy_qty_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Callback `buy_qty:{id}` — abre as opções de quantidade."""
    query = update.callback_query
    context.user_data.pop("awaiting_qty", None)
    context.user_data.pop("pending_qty", None)

    data = query.data or ""
    try:
        product_id = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        await query.answer("❌ Produto inválido.")
        return

    await _render_qty_options(query, product_id)


async def qty_change_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Callback `qty_change:{id}` — volta às opções de quantidade."""
    query = update.callback_query
    context.user_data.pop("pending_qty", None)
    context.user_data.pop("awaiting_qty", None)

    data = query.data or ""
    try:
        product_id = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        await query.answer("❌ Produto inválido.")
        return

    await _render_qty_options(query, product_id)


# ─────────────────────────────────────────────────────────
# SELEÇÃO DIRETA (1/2/3/5/10)
# ─────────────────────────────────────────────────────────


async def _show_summary(
    query, context, product_id: int, quantity: int
) -> None:
    user = query.from_user
    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        product = await get_product(session, product_id)
        if product is None or not product.is_active:
            await query.answer("❌ Produto indisponível.", show_alert=True)
            return
        if quantity > product.stock:
            await query.answer(
                f"⚠️ Apenas {product.stock} disponível(is).",
                show_alert=True,
            )
            return
        balance = float(db_user.balance)
        price = float(product.price)
        product_name = product.name

    total = price * quantity
    context.user_data["pending_qty"] = {
        "product_id": product_id,
        "product_name": product_name,
        "quantity": quantity,
        "unit_price": price,
        "total": total,
    }

    text = (
        "◈ *RESUMO DO PEDIDO*\n\n"
        f"📦 Produto: *{product_name}*\n"
        f"🔢 Quantidade: {quantity}\n"
        f"💰 Valor unitário: R$ {price:.2f}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        f"💳 Total: R$ {total:.2f}\n"
        f"💎 Seu saldo: R$ {balance:.2f}"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Continuar", callback_data="qty_continue"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔢 Alterar quantidade",
                    callback_data=f"qty_change:{product_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ Cancelar", callback_data="qty_cancel"
                )
            ],
        ]
    )
    await query.edit_message_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )


async def qty_select_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    data = query.data or ""
    parts = data.split(":")
    if len(parts) != 3:
        await query.answer("❌ Inválido.")
        return
    try:
        product_id = int(parts[1])
        quantity = int(parts[2])
    except ValueError:
        await query.answer("❌ Inválido.")
        return
    await _show_summary(query, context, product_id, quantity)


# ─────────────────────────────────────────────────────────
# QUANTIDADE DIGITADA (ForceReply)
# ─────────────────────────────────────────────────────────


async def qty_custom_prompt(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    data = query.data or ""
    try:
        product_id = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        await query.answer("❌ Produto inválido.")
        return

    user = query.from_user
    async with SessionLocal() as session:
        product = await get_product(session, product_id)
        if product is None or not product.is_active:
            await query.answer("❌ Produto indisponível.", show_alert=True)
            return
        stock = product.stock

    prompt_msg = await query.message.reply_text(
        f"✏️ *INFORME A QUANTIDADE*\n\n"
        f"Digite quantas unidades deseja adquirir.\n\n"
        f"📦 Disponível: {stock}",
        reply_markup=ForceReply(selective=True),
        parse_mode=ParseMode.MARKDOWN,
    )

    context.user_data["awaiting_qty"] = {
        "product_id": product_id,
        "prompt_message_id": prompt_msg.message_id,
        "origin_message_id": query.message.message_id,
        "origin_chat_id": query.message.chat_id,
        "set_at": time.time(),
    }
    await query.answer()


async def qty_text_input(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Recebe o valor digitado (MessageHandler)."""
    pending = context.user_data.get("awaiting_qty")
    if not pending:
        return
    if time.time() - pending.get("set_at", 0) > AWAITING_TTL:
        context.user_data.pop("awaiting_qty", None)
        return

    context.user_data.pop("awaiting_qty", None)

    # Limpa mensagens do fluxo ForceReply (best-effort)
    try:
        await update.message.delete()
    except Exception:
        pass
    try:
        await context.bot.delete_message(
            chat_id=pending["origin_chat_id"],
            message_id=pending["prompt_message_id"],
        )
    except Exception:
        pass

    product_id = pending["product_id"]
    origin_chat = pending["origin_chat_id"]
    origin_msg = pending["origin_message_id"]

    text = (update.message.text or "").strip()
    try:
        quantity = int(text)
        if quantity <= 0:
            raise ValueError
    except ValueError:
        await context.bot.edit_message_text(
            "❌ *Quantidade inválida.*\n\nDigite um número inteiro positivo.",
            chat_id=origin_chat,
            message_id=origin_msg,
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "↩️ Voltar",
                            callback_data=f"buy_qty:{product_id}",
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
        product = await get_product(session, product_id)
        if product is None or not product.is_active:
            await context.bot.edit_message_text(
                "❌ *Produto indisponível.*",
                chat_id=origin_chat,
                message_id=origin_msg,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "↩️ Voltar",
                                callback_data="back_to_catalog",
                            )
                        ]
                    ]
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        if quantity > product.stock:
            await context.bot.edit_message_text(
                f"❌ *Quantidade indisponível.*\n\n"
                f"Disponível: {product.stock}",
                chat_id=origin_chat,
                message_id=origin_msg,
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton(
                                "↩️ Voltar",
                                callback_data=f"buy_qty:{product_id}",
                            )
                        ]
                    ]
                ),
                parse_mode=ParseMode.MARKDOWN,
            )
            return

        balance = float(db_user.balance)
        price = float(product.price)
        product_name = product.name

    total = price * quantity
    context.user_data["pending_qty"] = {
        "product_id": product_id,
        "product_name": product_name,
        "quantity": quantity,
        "unit_price": price,
        "total": total,
    }

    text = (
        "◈ *RESUMO DO PEDIDO*\n\n"
        f"📦 Produto: *{product_name}*\n"
        f"🔢 Quantidade: {quantity}\n"
        f"💰 Valor unitário: R$ {price:.2f}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        f"💳 Total: R$ {total:.2f}\n"
        f"💎 Seu saldo: R$ {balance:.2f}"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Continuar", callback_data="qty_continue"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔢 Alterar quantidade",
                    callback_data=f"qty_change:{product_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    "↩️ Cancelar", callback_data="qty_cancel"
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


# ─────────────────────────────────────────────────────────
# CONTINUAR → CONFIRMAÇÃO
# ─────────────────────────────────────────────────────────


async def qty_continue_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    pending = context.user_data.get("pending_qty")
    if not pending:
        await query.answer(
            "⚠️ Sessão expirada. Abra o produto novamente.", show_alert=True
        )
        return

    user = query.from_user
    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        balance = float(db_user.balance)

    total = pending["total"]
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
                        "↩️ Voltar",
                        callback_data=f"qty_change:{pending['product_id']}",
                    )
                ],
            ]
        )
        await query.edit_message_text(
            text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )
        return

    text = (
        "🛍️ *CONFIRMAR PEDIDO*\n\n"
        f"📦 Produto: *{pending['product_name']}*\n"
        f"🔢 Quantidade: {pending['quantity']}\n"
        f"💰 Total: R$ {total:.2f}\n\n"
        f"💎 Saldo atual: R$ {balance:.2f}\n"
        f"💳 Saldo após compra: R$ {balance - total:.2f}\n\n"
        "Deseja confirmar?"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Confirmar compra", callback_data="qty_confirm"
                )
            ],
            [
                InlineKeyboardButton(
                    "✏️ Alterar quantidade",
                    callback_data=f"qty_change:{pending['product_id']}",
                )
            ],
            [
                InlineKeyboardButton(
                    "❌ Cancelar pedido", callback_data="qty_cancel"
                )
            ],
        ]
    )
    await query.edit_message_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────────────────────────────────────────────
# CONFIRMAR → PROCESSA → ENTREGA
# ─────────────────────────────────────────────────────────


async def qty_confirm_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    query = update.callback_query
    pending = context.user_data.get("pending_qty")
    if not pending:
        await query.answer("⚠️ Sessão expirada.", show_alert=True)
        return

    await query.edit_message_text(
        "⏳ *PROCESSANDO SEU PEDIDO*\n\n"
        "Estamos preparando seus produtos.\n\n"
        "Aguarde enquanto o sistema confirma a operação.",
        parse_mode=ParseMode.MARKDOWN,
    )

    user = query.from_user
    error = None
    needed_missing = 0.0
    result = None

    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        try:
            result = await execute_purchase(
                session,
                db_user.id,
                pending["product_id"],
                quantity=pending["quantity"],
            )
        except InsufficientBalance as e:
            await session.rollback()
            error = "insufficient"
            needed_missing = float(e.needed)
        except (OutOfStock, NoCredentials):
            await session.rollback()
            error = "out_of_stock"
        except Exception:
            await session.rollback()
            logger.exception("Falha ao processar compra por quantidade")
            error = "unknown"

    if error:
        if error == "insufficient":
            text = (
                "⚠️ *SALDO INSUFICIENTE*\n\n"
                f"💰 Valor que falta: R$ {needed_missing:.2f}"
            )
        elif error == "out_of_stock":
            text = "⚠️ *Produto esgotado no momento.*"
        else:
            text = "❌ *Erro ao processar.* Tente novamente."
        keyboard = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "↩️ Voltar", callback_data="qty_cancel"
                    )
                ]
            ]
        )
        await query.edit_message_text(
            text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
        )
        return

    context.user_data["last_qty_purchase"] = {
        "order_id": result["order_id"],
        "product_name": result["product_name"],
        "quantity": result["quantity"],
        "total": result["total"],
        "balance_after": result["balance_after"],
        "deliveries": result["deliveries"],
        "purchased_at": result["purchased_at"].isoformat(),
        "revealed": False,
    }
    context.user_data.pop("pending_qty", None)

    await _render_qty_delivery(query, context, revealed=False)


async def _render_qty_delivery(query, context, revealed: bool) -> None:
    last = context.user_data.get("last_qty_purchase")
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

    if revealed:
        sections = []
        for i, d in enumerate(last["deliveries"], start=1):
            sections.append(
                f"#{i}\n📧 E-mail: `{d['email']}`\n🔑 Senha: `{d['password']}`"
            )
        creds_block = "\n\n".join(sections)
        reveal_text = "🔒 Desativar visualização"
        reveal_cb = "qty_hide_creds"
    else:
        sections = [
            f"#{i}\n📧 E-mail: ••••••••••••\n🔑 Senha: ••••••••••••"
            for i in range(1, len(last["deliveries"]) + 1)
        ]
        creds_block = "\n\n".join(sections)
        reveal_text = "🔐 Visualizar acessos"
        reveal_cb = "qty_reveal_creds"

    text = (
        "✅ *COMPRA CONCLUÍDA!*\n\n"
        f"📦 Produto: *{last['product_name']}*\n"
        f"🔢 Quantidade: {last['quantity']}\n"
        f"💰 Total pago: R$ {last['total']:.2f}\n"
        f"💎 Saldo restante: R$ {last['balance_after']:.2f}\n\n"
        f"🆔 Pedido: #{last['order_id']}\n"
        f"📅 Data: {date_str}\n\n"
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


async def qty_reveal_creds(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await _render_qty_delivery(update.callback_query, context, revealed=True)


async def qty_hide_creds(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    await _render_qty_delivery(update.callback_query, context, revealed=False)


# ─────────────────────────────────────────────────────────
# CANCELAR
# ─────────────────────────────────────────────────────────


async def qty_cancel_handler(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    context.user_data.pop("pending_qty", None)
    context.user_data.pop("awaiting_qty", None)

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
    await update.callback_query.edit_message_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )
