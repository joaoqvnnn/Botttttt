import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from telegram import Update
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

from app.config import settings
from app.database import init_db
from app.handlers.buy_quantity import (
    buy_qty_handler,
    qty_cancel_handler,
    qty_change_handler,
    qty_confirm_handler,
    qty_continue_handler,
    qty_custom_prompt,
    qty_hide_creds,
    qty_reveal_creds,
    qty_select_handler,
    qty_text_input,
)
from app.handlers.cart_handler import (
    cart_buy_handler,
    cart_clear_handler,
    cart_confirm_handler,
    cart_hide_creds,
    cart_reveal_creds,
    cart_view,
)
from app.handlers.catalog import (
    back_to_catalog,
    cart_add,
    catalog_open,
    catalog_page,
    product_view,
)
from app.handlers.purchase import (
    activation_missing,
    buy_now,
    cancel_buy,
    confirm_buy,
    hide_creds,
    reveal_creds,
)
from app.handlers.start import (
    back_to_menu,
    error_handler,
    placeholder_callback,
    start_handler,
    verify_callback,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

ptb_app: Application | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global ptb_app

    await init_db()
    logger.info("Banco de dados inicializado.")

    ptb_app = Application.builder().token(settings.BOT_TOKEN).build()

    # ─── Módulo 01 — Entrada ───────────────────────────
    ptb_app.add_handler(CommandHandler("start", start_handler))
    ptb_app.add_handler(
        CallbackQueryHandler(verify_callback, pattern="^verify_membership$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(back_to_menu, pattern="^back_to_menu$")
    )

    # ─── Módulo 02 — Catálogo ──────────────────────────
    ptb_app.add_handler(
        CallbackQueryHandler(catalog_open, pattern="^catalog$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(catalog_page, pattern="^cat_page:")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(back_to_catalog, pattern="^back_to_catalog$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(product_view, pattern="^product:")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(cart_add, pattern="^cart_add:")
    )

    # ─── Módulo 03 — Compras (1 unidade) ───────────────
    ptb_app.add_handler(CallbackQueryHandler(buy_now, pattern="^buy_now:"))
    ptb_app.add_handler(
        CallbackQueryHandler(confirm_buy, pattern="^confirm_buy:")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(cancel_buy, pattern="^cancel_buy:")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(reveal_creds, pattern="^reveal_creds$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(hide_creds, pattern="^hide_creds$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(
            activation_missing, pattern="^activation_missing$"
        )
    )

    # ─── Módulo 04 — Compra por quantidade ─────────────
    ptb_app.add_handler(
        CallbackQueryHandler(buy_qty_handler, pattern="^buy_qty:")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(qty_select_handler, pattern="^qty_select:")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(qty_custom_prompt, pattern="^qty_custom:")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(qty_change_handler, pattern="^qty_change:")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(
            qty_continue_handler, pattern="^qty_continue$"
        )
    )
    ptb_app.add_handler(
        CallbackQueryHandler(qty_confirm_handler, pattern="^qty_confirm$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(qty_cancel_handler, pattern="^qty_cancel$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(qty_reveal_creds, pattern="^qty_reveal_creds$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(qty_hide_creds, pattern="^qty_hide_creds$")
    )

    # ─── Módulo 05 — Carrinho ──────────────────────────
    ptb_app.add_handler(CallbackQueryHandler(cart_view, pattern="^cart$"))
    ptb_app.add_handler(
        CallbackQueryHandler(cart_buy_handler, pattern="^cart_buy$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(cart_confirm_handler, pattern="^cart_confirm$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(cart_clear_handler, pattern="^cart_clear$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(
            cart_reveal_creds, pattern="^cart_reveal_creds$"
        )
    )
    ptb_app.add_handler(
        CallbackQueryHandler(cart_hide_creds, pattern="^cart_hide_creds$")
    )

    # ─── MessageHandler — input de texto (quantidade) ──
    ptb_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, qty_text_input)
    )

    # ─── Fallback — sempre por último ──────────────────
    ptb_app.add_handler(CallbackQueryHandler(placeholder_callback))
    ptb_app.add_error_handler(error_handler)

    await ptb_app.initialize()
    await ptb_app.start()

    if settings.USE_WEBHOOK and settings.WEBHOOK_URL:
        webhook = f"{settings.WEBHOOK_URL.rstrip('/')}/webhook/telegram"
        await ptb_app.bot.set_webhook(webhook)
        logger.info(f"Webhook configurado: {webhook}")
    else:
        await ptb_app.updater.start_polling()
        logger.info("Polling iniciado.")

    yield

    try:
        if settings.USE_WEBHOOK and settings.WEBHOOK_URL:
            await ptb_app.bot.delete_webhook()
        else:
            await ptb_app.updater.stop()
        await ptb_app.stop()
        await ptb_app.shutdown()
    except Exception as e:
        logger.warning(f"Erro no shutdown: {e}")


app = FastAPI(lifespan=lifespan, title="BELLAMY Bot")


@app.get("/")
async def root():
    return {"status": "ok", "service": "BELLAMY | DIGITAL STORE"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/webhook/telegram")
async def telegram_webhook(request: Request):
    if ptb_app is None:
        return Response(status_code=503)
    data = await request.json()
    update = Update.de_json(data, ptb_app.bot)
    await ptb_app.process_update(update)
    return Response(status_code=200)
