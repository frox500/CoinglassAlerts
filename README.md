# CoinglassAlerts

Bot de alertas para Telegram basado en CoinGlass:

- Fuente: CoinGlass Futures Taker Buy/Sell Volume
- Endpoint: `/api/futures/taker-buy-sell-volume/exchange-list`
- Símbolo default: `BTC`
- Timeframe default: `5m`
- Trigger default: diferencia neta de `150,000,000 USD`

## Lógica

```text
delta = buy_vol_usd - sell_vol_usd
```

Si:

```text
delta >= +150M
```

envía alerta de presión compradora agresiva.

Si:

```text
delta <= -150M
```

envía alerta de presión vendedora agresiva.

## Render

Crear como:

```text
Background Worker
```

Build Command:

```bash
pip install -r requirements.txt
```

Start Command:

```bash
python bot.py
```

## Environment Variables

```env
COINGLASS_API_KEY=tu_api_key_coinglass

TELEGRAM_BOT_TOKEN=tu_token_telegram
TELEGRAM_CHAT_ID=-1002087543269
TELEGRAM_MESSAGE_THREAD_ID=topic_id

SYMBOL=BTC
RANGE=5m
THRESHOLD_USD=150000000
CHECK_EVERY_SECONDS=60
ALERT_COOLDOWN_MINUTES=10
MIN_TOTAL_VOLUME_USD=0

SEND_HEARTBEAT=false
HEARTBEAT_EVERY_MINUTES=240
RUN_ONCE=false
TIMEZONE=America/New_York
```

## Prueba

Para probar una sola corrida en Render:

```env
RUN_ONCE=true
SEND_HEARTBEAT=true
```

Luego hacer `Manual Deploy` o reiniciar el worker.

Cuando confirmes que manda al topic correcto:

```env
RUN_ONCE=false
SEND_HEARTBEAT=false
```

## Notas Operativas

El bot no entra operaciones. Solo detecta presión agresiva de taker buy/sell volume.

Una alerta no es entrada automática:

- Confirmar cierre 5M/15M.
- Confirmar estructura y liquidez.
- Evitar perseguir vela extendida.
- Usar cooldown para no duplicar señales.
