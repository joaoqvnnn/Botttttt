import logging

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.config import settings
from app.database import SessionLocal
from app.db.cart import add_to_cart
from app.db.products import (
    get_active_products_paginated,
    get_product,
    register_view_and_get_counters,
)
from app.db.users import get_or_create_user
from app.keyboards.catalog import catalog_keyboard, product_keyboard


logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────
# TEXTO / RENDER DO CATÁLOGO
# ─────────────────────────────────────────────────────────


def _catalog_text(first_name: str, balance: float) -> str:
    return (
        "◈ *BELLAMY | CONTAS*\n\n"
        f"Olá, {first_name}!\n\n"
        f"💎 Saldo: R$ {balance:.2f}\n\n"
        "⌘ Selecione um produto disponível abaixo."
    )


async def _render_catalog(
    update: Update, context: ContextTypes.DEFAULT_TYPE, page: int = 1
) -> None:
    query = update.callback_query
    user = update.effective_user

    async with SessionLocal() as session:
        db_user = await get_or_create_user(
            session, user.id, user.username, user.first_name
        )
        products, total_pages, current_page = await get_active_products_paginated(
            session, page, settings.PRODUCTS_PER_PAGE
        )
        balance = float(db_user.balance)

    # Guarda a página atual para o botão "Voltar" do detalhe saber retornar
    context.user_data["catalog_page"] = current_page

    text = _catalog_text(user.first_name, balance)
    keyboard = catalog_keyboard(products, current_page, total_pages)

    await query.edit_message_text(
        text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN
    )


async def catalog_open(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Abre o catálogo na página 1 (chamado a partir do menu principal)."""
    await _render_catalog(update, context, page=1)


async def catalog_page(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Paginação — callback `cat_page:N`."""
    data = update.callback_query.data or ""
    try:
        page = int(data.split(":", 1)[1])
    except (IndexError, ValueError):
        page = 1
    await _render_catalog(update, context, page=page)


async def back_to_catalog(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Retorna ao catálogo na última página visitada pelo usuário."""
    page = context.user_data.get("catalog_page", 1)
    await _render_catalog(update, context, page=page)


# ─────────────────────────────────────────────────────────
# DETALHE DO PRODUTO
# ─────────────────────────────────────────────────────────


def _product_text(product, balance: float, viewers: int) -> str:
    stock_line = str(product.stock) if product.stock > 0 else "Esgotado"
    desc = product.description or "Sem descrição."

    text = (
        "◈ *BELLAMY | PRODUTO*\n\n"
        f"▸ Produto: *{product.name}*\n"
        f"▸ Preço: R$ {float(product.price):.2f}\n"
        f"▸ Seu saldo: R$ {balance:.2f}\n"
        f"▸ Disponibilidade: {stock_line}\n\n"
        f"⌁ {desc}\n\n"
        f"◈ {viewers} pessoas visualizando este produto."
    )
    if product.stock <= 0:
        text += "\n\n⚠️ _Produto temporariamente esgotado._"
    return text


async def product_view(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Abre a tela de detalhes do produto — callback `product:{id}`."""
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

        viewers = await register_view_and_get_counters(
            session, product_id, db_user.id
        )
        balance = float(db_user.balance)

    text = _product_text(product, balance, viewers)
    await query.edit_message_text(
        text, reply_markup=product_keyboard(product), parse_mode=ParseMode.MARKDOWN
    )


# ─────────────────────────────────────────────────────────
# ADICIONAR AO CARRINHO (silencioso)
# ─────────────────────────────────────────────────────────


async def cart_add(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Adiciona ao carrinho — callback `cart_add:{id}`. Não edita a mensagem."""
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
        count = await add_to_cart(session, db_user.id, product_id, 1)

    await query.answer(f"✅ Adicionado! ({count} no carrinho)")
