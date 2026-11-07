from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from app.models.product import Product


def catalog_keyboard(
    products: list[Product], page: int, total_pages: int
) -> InlineKeyboardMarkup:
    buttons: list[list[InlineKeyboardButton]] = []

    for p in products:
        buttons.append(
            [
                InlineKeyboardButton(
                    f"{p.name} — R$ {float(p.price):.2f}",
                    callback_data=f"product:{p.id}",
                )
            ]
        )

    nav_row: list[InlineKeyboardButton] = []
    if page > 1:
        nav_row.append(
            InlineKeyboardButton(
                "⬅️ Anterior", callback_data=f"cat_page:{page - 1}"
            )
        )
    if page < total_pages:
        nav_row.append(
            InlineKeyboardButton(
                "Próxima ➡️", callback_data=f"cat_page:{page + 1}"
            )
        )
    if nav_row:
        buttons.append(nav_row)

    buttons.append(
        [InlineKeyboardButton("↩️ Voltar", callback_data="back_to_menu")]
    )
    return InlineKeyboardMarkup(buttons)


def product_keyboard(product: Product) -> InlineKeyboardMarkup:
    pid = product.id
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🛒 Comprar agora", callback_data=f"buy_now:{pid}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🔢 Comprar quantidade", callback_data=f"buy_qty:{pid}"
                )
            ],
            [
                InlineKeyboardButton(
                    "🧺 Adicionar ao carrinho", callback_data=f"cart_add:{pid}"
                )
            ],
            [
                InlineKeyboardButton(
                    "💎 Adicionar saldo", callback_data="add_balance"
                )
            ],
            [InlineKeyboardButton("↩️ Voltar", callback_data="back_to_catalog")],
        ]
    )
