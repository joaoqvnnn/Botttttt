from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.config import settings


def lock_screen_keyboard(channel_link: str, group_link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📢 Entrar no canal", url=channel_link)],
            [InlineKeyboardButton("👥 Entrar no grupo", url=group_link)],
            [
                InlineKeyboardButton(
                    "✅ Já entrei — Verificar",
                    callback_data="verify_membership",
                )
            ],
        ]
    )


def _support_button() -> InlineKeyboardButton | None:
    """
    Monta o botão de suporte como URL direta ao chat privado.
    Retorna None se SUPPORT_CONTACT não estiver configurado
    (o botão não aparece, evitando clique em botão inútil).
    """
    contact = (settings.SUPPORT_CONTACT or "").strip()
    if not contact:
        return None

    if contact.startswith("@"):
        username = contact[1:].strip()
        if not username:
            return None
        return InlineKeyboardButton(
            "💬 Suporte", url=f"https://t.me/{username}"
        )

    if contact.isdigit():
        return InlineKeyboardButton(
            "💬 Suporte", url=f"tg://user?id={contact}"
        )

    return None


def main_menu_keyboard(cart_count: int = 0) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                "🛍️ Logins | Contas Premium", callback_data="catalog"
            )
        ],
        [InlineKeyboardButton("👤 Perfil", callback_data="profile")],
        [InlineKeyboardButton("💎 Adicionar saldo", callback_data="add_balance")],
    ]

    support = _support_button()
    if support is not None:
        buttons.append([support])

    buttons.extend(
        [
            [InlineKeyboardButton("🏆 Ranking", callback_data="ranking")],
            [InlineKeyboardButton("🤝 Afiliados", callback_data="affiliates")],
        ]
    )

    if cart_count > 0:
        buttons.append(
            [
                InlineKeyboardButton(
                    f"🧺 Carrinho ({cart_count})", callback_data="cart"
                )
            ]
        )

    return InlineKeyboardMarkup(buttons)
