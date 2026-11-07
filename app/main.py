import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from telegram import Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from app.config import settings
from app.database import init_db
from app.handlers.start import (
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

    ptb_app.add_handler(CommandHandler("start", start_handler))
    ptb_app.add_handler(
        CallbackQueryHandler(verify_callback, pattern="^verify_membership$")
    )
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
