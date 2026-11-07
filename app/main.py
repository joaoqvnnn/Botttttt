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
from app.database import SessionLocal, init_db
from app.db.payments import confirm_payment, get_payment_by_mp_id
from app.handlers.affiliates import (
    affiliates_history,
    affiliates_how_it_works,
    affiliates_performance,
    affiliates_redeem,
    affiliates_redeem_all,
    affiliates_redeem_cancel,
    affiliates_redeem_confirm,
    affiliates_redeem_custom_input,
    affiliates_redeem_custom_prompt,
    affiliates_referrals,
    affiliates_referrals_page,
    affiliates_view,
)
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
from app.handlers.pix import (
    pix_back,
    pix_cancel,
    pix_check,
    pix_entry,
    pix_start,
    pix_value_input,
)
from app.handlers.profile import (
    back_to_profile,
    generate_pdf_handler,
    profile_history,
    profile_view,
)
from app.handlers.purchase import (
    activation_missing,
    buy_now,
    cancel_buy,
    confirm_buy,
    hide_creds,
    reveal_creds,
)
from app.handlers.ranking import ranking_category, ranking_open
from app.handlers.start import (
    back_to_menu,
    error_handler,
    placeholder_callback,
    start_handler,
    verify_callback,
)
from app.handlers.subscriptions import (
    subscription_detail,
    subscription_hide,
    subscription_reveal,
    subscriptions_page,
    subscriptions_view,
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

    # ─── Módulo 06 — PIX ───────────────────────────────
    ptb_app.add_handler(
        CallbackQueryHandler(pix_entry, pattern="^add_balance")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(pix_start, pattern="^pix_start$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(pix_check, pattern="^pix_check$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(pix_cancel, pattern="^pix_cancel$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(pix_back, pattern="^pix_back:")
    )

    # ─── Módulo 07 — Assinaturas ───────────────────────
    ptb_app.add_handler(
        CallbackQueryHandler(subscriptions_view, pattern="^profile_subs$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(subscriptions_page, pattern="^sub_page:")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(subscription_detail, pattern="^sub_detail:")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(subscription_reveal, pattern="^sub_reveal:")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(subscription_hide, pattern="^sub_hide:")
    )

    # ─── Módulo 08 — Perfil e Histórico ────────────────
    ptb_app.add_handler(CallbackQueryHandler(profile_view, pattern="^profile$"))
    ptb_app.add_handler(
        CallbackQueryHandler(back_to_profile, pattern="^back_to_profile$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(profile_history, pattern="^profile_history$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(generate_pdf_handler, pattern="^history_pdf$")
    )

    # ─── Módulo 09 — Ranking ───────────────────────────
    ptb_app.add_handler(
        CallbackQueryHandler(ranking_open, pattern="^ranking$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(ranking_category, pattern="^rank:")
    )

    # ─── Módulo 10 — Afiliados ─────────────────────────
    ptb_app.add_handler(
        CallbackQueryHandler(affiliates_view, pattern="^affiliates$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(affiliates_redeem, pattern="^aff_redeem$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(
            affiliates_redeem_all, pattern="^aff_redeem_all$"
        )
    )
    ptb_app.add_handler(
        CallbackQueryHandler(
            affiliates_redeem_custom_prompt,
            pattern="^aff_redeem_custom$",
        )
    )
    ptb_app.add_handler(
        CallbackQueryHandler(
            affiliates_redeem_confirm, pattern="^aff_redeem_confirm$"
        )
    )
    ptb_app.add_handler(
        CallbackQueryHandler(
            affiliates_redeem_cancel, pattern="^aff_redeem_cancel$"
        )
    )
    ptb_app.add_handler(
        CallbackQueryHandler(
            affiliates_referrals, pattern="^aff_referrals$"
        )
    )
    ptb_app.add_handler(
        CallbackQueryHandler(
            affiliates_referrals_page, pattern="^aff_refs_page:"
        )
    )
    ptb_app.add_handler(
        CallbackQueryHandler(
            affiliates_performance, pattern="^aff_performance$"
        )
    )
    ptb_app.add_handler(
        CallbackQueryHandler(affiliates_history, pattern="^aff_history$")
    )
    ptb_app.add_handler(
        CallbackQueryHandler(
            affiliates_how_it_works, pattern="^aff_how$"
        )
    )

    # ─── MessageHandler — inputs de texto ──────────────
    ptb_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, qty_text_input)
    )
    ptb_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, pix_value_input)
    )
    ptb_app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND, affiliates_redeem_custom_input
        )
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


# ─────────────────────────────────────────────────────────
# MÓDULO 06 — WEBHOOK MERCADO PAGO
# ─────────────────────────────────────────────────────────


@app.post("/webhook/mercadopago")
async def mercadopago_webhook(request: Request):
    try:
        body = await request.json()
    except Exception:
        return Response(status_code=400)

    notif_type = body.get("type") or body.get("topic")
    data_id = (body.get("data") or {}).get("id") or body.get("data_id")

    if notif_type not in ("payment", "merchant_order") or not data_id:
        return Response(status_code=200)

    try:
        mp_payment_id = int(data_id)
    except (TypeError, ValueError):
        return Response(status_code=200)

    try:
        headers = {"Authorization": f"Bearer {settings.MP_ACCESS_TOKEN}"}
        import httpx as _httpx

        async with _httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"https://api.mercadopago.com/v1/payments/{mp_payment_id}",
                headers=headers,
            )
            if resp.status_code != 200:
                return Response(status_code=200)
            mp_data = resp.json()
    except Exception:
        logger.exception("Falha ao consultar pagamento no MP")
        return Response(status_code=200)

    if mp_data.get("status") != "approved":
        return Response(status_code=200)

    async with SessionLocal() as session:
        payment = await get_payment_by_mp_id(session, mp_payment_id)
        if payment is None:
            logger.warning(f"Pagamento MP {mp_payment_id} sem registro local")
            return Response(status_code=200)
        await confirm_payment(session, payment)

    return Response(status_code=200)
