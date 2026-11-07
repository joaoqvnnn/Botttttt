import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

from app.database import SessionLocal
from app.db.ranking import (
    top_balance,
    top_depositors,
    top_products_sold,
    top_purchases_count,
    top_recharges_count,
    top_referrers,
)


logger = logging.getLogger(__name__)


CATEGORIES = [
    ("servicos", "Serviços"),
    ("recargas", "Recargas"),
    ("compras", "Compras"),
    ("saldo", "Saldo"),
    ("depositadores", "Depositadores"),
    ("indicacoes", "Indicações"),
]

CATEGORY_TITLES = {
    "servicos": "🛍️ Serviços mais vendidos",
    "recargas": "💎 Maiores recarregadores",
    "compras": "🛒 Maiores compradores",
    "saldo": "💰 Maiores saldos",
    "depositadores": "💳 Maiores depositadores",
    "indicacoes": "🤝 Melhores indicadores",
}


# ─────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────


def _medal(pos: int) -> str:
    return {1: "🥇", 2: "🥈", 3: "🥉"}.get(pos, f"{pos}º")


def _user_display(first_name: str | None, username: str | None) -> str:
    if first_name:
        return first_name[:20]
    if username:
        return f"@{username}"
    return "Usuário"


# ─────────────────────────────────────────────────────────
# KEYBOARD
# ─────────────────────────────────────────────────────────


def _ranking_keyboard(selected: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []

    # Duas colunas
    for i in range(0, len(CATEGORIES), 2):
        row: list[InlineKeyboardButton] = []
        for key, label in CATEGORIES[i : i + 2]:
            mark = "🟢" if key == selected else "⚪"
            row.append(
                InlineKeyboardButton(
                    f"{mark} {label}", callback_data=f"rank:{key}"
                )
            )
        rows.append(row)

    # Voltar sozinho na última linha
    rows.append(
        [
            InlineKeyboardButton(
                "↩️ Voltar", callback_data="back_to_menu"
            )
        ]
    )
    return InlineKeyboardMarkup(rows)


# ─────────────────────────────────────────────────────────
# TEXTO DE CADA CATEGORIA
# ─────────────────────────────────────────────────────────


async def _build_ranking_body(category: str) -> str:
    async with SessionLocal() as session:
        if category == "servicos":
            rows = await top_products_sold(session)
            if not rows:
                return "Nenhuma venda registrada ainda."
            return "\n".join(
                f"{_medal(i + 1)} *{r[0]}* — {int(r[1])} venda(s)"
                for i, r in enumerate(rows)
            )

        if category == "recargas":
            rows = await top_recharges_count(session)
            if not rows:
                return "Nenhuma recarga registrada ainda."
            return "\n".join(
                f"{_medal(i + 1)} *{_user_display(r[0], r[1])}* "
                f"— {int(r[2])} recarga(s)"
                for i, r in enumerate(rows)
            )

        if category == "compras":
            rows = await top_purchases_count(session)
            if not rows:
                return "Nenhuma compra registrada ainda."
            return "\n".join(
                f"{_medal(i + 1)} *{_user_display(r[0], r[1])}* "
                f"— {int(r[2])} compra(s)"
                for i, r in enumerate(rows)
            )

        if category == "saldo":
            rows = await top_balance(session)
            if not rows:
                return "Nenhum usuário cadastrado ainda."
            return "\n".join(
                f"{_medal(i + 1)} *{_user_display(r[0], r[1])}* "
                f"— R$ {float(r[2]):.2f}"
                for i, r in enumerate(rows)
            )

        if category == "depositadores":
            rows = await top_depositors(session)
            if not rows:
                return "Nenhum depósito registrado ainda."
            return "\n".join(
                f"{_medal(i + 1)} *{_user_display(r[0], r[1])}* "
                f"— R$ {float(r[2]):.2f}"
                for i, r in enumerate(rows)
            )

        if category == "indicacoes":
            rows = await top_referrers(session)
            if not rows:
                return "Nenhuma indicação registrada ainda."
            return "\n".join(
                f"{_medal(i + 1)} *{_user_display(r[0], r[1])}* "
                f"— {int(r[2])} indicado(s)"
                for i, r in enumerate(rows)
            )

    return "Categoria inválida."


async def _render_ranking(query, category: str) -> None:
    body = await _build_ranking_body(category)
    title = CATEGORY_TITLES.get(category, "Ranking")

    text = (
        "◈ *BELLAMY | RANKING*\n\n"
        f"🏆 *{title}*\n\n"
        f"{body}\n\n"
        "━━━━━━━━━━━━━━\n\n"
        "🟢 Selecionada · ⚪ Outras categorias"
    )

    try:
        await query.edit_message_text(
            text,
            reply_markup=_ranking_keyboard(category),
            parse_mode=ParseMode.MARKDOWN,
        )
    except Exception as e:
        # Mensagem idêntica (usuário clicou na mesma categoria) — ignora
        logger.debug(f"Edit sem mudança: {e}")


# ─────────────────────────────────────────────────────────
# HANDLERS
# ─────────────────────────────────────────────────────────


async def ranking_open(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Callback `ranking` — abre Ranking na categoria inicial (Serviços)."""
    await _render_ranking(update.callback_query, "servicos")


async def ranking_category(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    """Callback `rank:{categoria}` — troca de categoria."""
    query = update.callback_query
    data = query.data or ""
    category = data.split(":", 1)[1] if ":" in data else "servicos"

    valid_keys = {key for key, _ in CATEGORIES}
    if category not in valid_keys:
        category = "servicos"

    await _render_ranking(query, category)
