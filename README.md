# BELLAMY | DIGITAL STORE — Bot Telegram

## Deploy no Render

1. Suba este repositório no GitHub.
2. No Render → **New +** → **Blueprint** → conecte o repositório.
3. O `render.yaml` cria automaticamente o Web Service + PostgreSQL.
4. Preencha as variáveis (`BOT_TOKEN`, `CHANNEL_ID`, `CHANNEL_LINK`, `GROUP_ID`, `GROUP_LINK`, `WEBHOOK_URL`).
   - `WEBHOOK_URL` = URL pública do seu serviço (ex: `https://bellamy-bot.onrender.com`).
5. Deploy. Ao iniciar, o webhook é registrado automaticamente.

## Requisitos do Bot no Telegram

- O bot **precisa ser Administrador** do canal e do grupo para conseguir verificar membros.
- `CHANNEL_ID` aceita `@username` público ou `-100...` (ID interno).

## Teste

- `/start` no bot → tela de bloqueio se não estiver nos dois canais.
- Entrar no canal + grupo → clicar em **Já entrei — Verificar** → menu principal.

## Observações

- Render free: o serviço hiberna após ~15 min sem uso. Como usamos webhook, o Telegram reenvia updates quando ele acorda — pode haver até ~30s de atraso no primeiro clique após hibernar.
- PostgreSQL free do Render expira em 90 dias — renovar/upgrade quando necessário.
