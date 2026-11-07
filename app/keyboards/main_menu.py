from telegram import InlineKeyboardButton, InlineKeyboardMarkup


def lock_screen_keyboard(channel_link: str, group_link: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📢 Entrar no canal", url=channel_link)],
            [InlineKeyboardButton("👥 Entrar no grupo", url=group_link)],
            [InlineKeyboardButton("✅ Já entrei — Verificar", callback_data="verify_membership")],
        ]
    )


def main_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🛍️ Logins | Contas Premium", callback_data="catalog")],
            [InlineKeyboardButton("👤 Perfil", callback_data="profile")],
            [InlineKeyboardButton("💎 Adicionar saldo", callback_data="add_balance")],
            [InlineKeyboardButton("💬 Suporte", callback_data="support")],
            [InlineKeyboardButton("🏆 Ranking", callback_data="ranking")],
            [InlineKeyboardButton("🤝 Afiliados", callback_data="affiliates")],
        ]
    )
