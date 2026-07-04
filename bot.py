import os
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import requests


COINGLASS_BASE = "https://open-api-v4.coinglass.com"
COINGLASS_API_KEY = os.getenv("COINGLASS_API_KEY")

TELEGRAM_BASE = "https://api.telegram.org"
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
TELEGRAM_MESSAGE_THREAD_ID = os.getenv("TELEGRAM_MESSAGE_THREAD_ID")

SYMBOL = os.getenv("SYMBOL", "BTC").upper()
RANGE = os.getenv("RANGE", "5m")
THRESHOLD_USD = float(os.getenv("THRESHOLD_USD", "150000000"))
CHECK_EVERY_SECONDS = int(os.getenv("CHECK_EVERY_SECONDS", "60"))
ALERT_COOLDOWN_MINUTES = int(os.getenv("ALERT_COOLDOWN_MINUTES", "10"))
MIN_TOTAL_VOLUME_USD = float(os.getenv("MIN_TOTAL_VOLUME_USD", "0"))

SEND_HEARTBEAT = os.getenv("SEND_HEARTBEAT", "false").lower() == "true"
HEARTBEAT_EVERY_MINUTES = int(os.getenv("HEARTBEAT_EVERY_MINUTES", "240"))
RUN_ONCE = os.getenv("RUN_ONCE", "false").lower() == "true"
TIMEZONE = os.getenv("TIMEZONE", "America/New_York")
TZ = ZoneInfo(TIMEZONE)


def require_env():
    missing = []
    if not COINGLASS_API_KEY:
        missing.append("COINGLASS_API_KEY")
    if not TELEGRAM_BOT_TOKEN:
        missing.append("TELEGRAM_BOT_TOKEN")
    if not TELEGRAM_CHAT_ID:
        missing.append("TELEGRAM_CHAT_ID")

    if missing:
        raise RuntimeError(f"Missing environment variables: {', '.join(missing)}")


def fmt_usd(value):
    value = float(value)
    abs_value = abs(value)

    if abs_value >= 1_000_000_000:
        return f"${value / 1_000_000_000:,.2f}B"
    if abs_value >= 1_000_000:
        return f"${value / 1_000_000:,.2f}M"
    if abs_value >= 1_000:
        return f"${value / 1_000:,.2f}K"

    return f"${value:,.2f}"


def fmt_pct(value):
    return f"{float(value):.2f}%"


def get_json(url, params=None, headers=None, timeout=20):
    response = requests.get(url, params=params, headers=headers, timeout=timeout)

    if not response.ok:
        print("Request failed:", response.status_code, response.text[:500])

    response.raise_for_status()
    return response.json()


def fetch_taker_buy_sell():
    url = f"{COINGLASS_BASE}/api/futures/taker-buy-sell-volume/exchange-list"
    headers = {
        "CG-API-KEY": COINGLASS_API_KEY,
        "accept": "application/json",
    }
    params = {
        "symbol": SYMBOL,
        "range": RANGE,
    }

    data = get_json(url, params=params, headers=headers)

    if str(data.get("code")) != "0":
        raise RuntimeError(f"CoinGlass API error: {data}")

    payload = data.get("data")
    if not payload:
        raise RuntimeError("CoinGlass returned empty data payload.")

    return payload


def fetch_bybit_price():
    try:
        data = get_json(
            "https://api.bybit.com/v5/market/tickers",
            {
                "category": "linear",
                "symbol": f"{SYMBOL}USDT",
            },
            timeout=10,
        )
        rows = data.get("result", {}).get("list", [])
        if not rows:
            return None
        return float(rows[0]["lastPrice"])
    except Exception as exc:
        print("Price unavailable:", exc)
        return None


def post_telegram_message(text):
    url = f"{TELEGRAM_BASE}/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }

    if TELEGRAM_MESSAGE_THREAD_ID:
        payload["message_thread_id"] = int(TELEGRAM_MESSAGE_THREAD_ID)

    response = requests.post(url, data=payload, timeout=30)

    if not response.ok:
        print("Telegram error:", response.status_code, response.text[:500])

    response.raise_for_status()
    return response.json()


def top_exchange_rows(exchange_list, direction, limit=5):
    if not exchange_list:
        return []

    def net_delta(row):
        return float(row.get("buy_vol_usd", 0)) - float(row.get("sell_vol_usd", 0))

    reverse = direction == "LONG"
    ranked = sorted(exchange_list, key=net_delta, reverse=reverse)
    rows = []

    for row in ranked[:limit]:
        exchange = row.get("exchange", "N/A")
        buy = float(row.get("buy_vol_usd", 0))
        sell = float(row.get("sell_vol_usd", 0))
        delta = buy - sell
        sign = "+" if delta >= 0 else "-"

        rows.append(
            f"{exchange}: Buy {fmt_usd(buy)} | Sell {fmt_usd(sell)} | Delta {sign}{fmt_usd(abs(delta))}"
        )

    return rows


def build_alert_message(payload, price, delta, direction):
    now = datetime.now(TZ)
    buy_vol = float(payload.get("buy_vol_usd", 0))
    sell_vol = float(payload.get("sell_vol_usd", 0))
    buy_ratio = float(payload.get("buy_ratio", 0))
    sell_ratio = float(payload.get("sell_ratio", 0))
    total_vol = buy_vol + sell_vol
    exchange_list = payload.get("exchange_list", [])

    pressure_word = "comprador" if direction == "LONG" else "vendedor"
    sign = "+" if delta >= 0 else "-"
    price_line = f"Precio ref: ${price:,.2f}" if price is not None else "Precio ref: N/A"

    top_rows = top_exchange_rows(exchange_list, direction)
    top_text = "\n".join(f"- {row}" for row in top_rows) if top_rows else "- No disponible"

    return f"""🚨 COINGLASS BTC TAKER ALERT — {RANGE}

Dirección: {direction} agresivo
{price_line}
Hora NY: {now.strftime("%H:%M:%S")} | {now.strftime("%d %b %Y")}

Buy Vol: {fmt_usd(buy_vol)} | {fmt_pct(buy_ratio)}
Sell Vol: {fmt_usd(sell_vol)} | {fmt_pct(sell_ratio)}
Delta neto: {sign}{fmt_usd(abs(delta))}
Volumen total: {fmt_usd(total_vol)}
Umbral: {fmt_usd(THRESHOLD_USD)}

Top exchanges por presión {pressure_word}:
{top_text}

Lectura:
Entrada agresiva de volumen {pressure_word} en {SYMBOL} {RANGE}. No perseguir vela. Confirmar cierre 5M/15M, estructura y liquidez antes de ejecutar.

@FROX500"""


def build_heartbeat_message(payload, price, delta):
    now = datetime.now(TZ)
    buy_vol = float(payload.get("buy_vol_usd", 0))
    sell_vol = float(payload.get("sell_vol_usd", 0))
    buy_ratio = float(payload.get("buy_ratio", 0))
    sell_ratio = float(payload.get("sell_ratio", 0))
    sign = "+" if delta >= 0 else "-"
    price_line = f"Precio ref: ${price:,.2f}" if price is not None else "Precio ref: N/A"

    return f"""COINGLASS BTC MONITOR — {RANGE}

Estado: activo, sin alerta de umbral.
{price_line}
Hora NY: {now.strftime("%H:%M:%S")} | {now.strftime("%d %b %Y")}

Buy Vol: {fmt_usd(buy_vol)} | {fmt_pct(buy_ratio)}
Sell Vol: {fmt_usd(sell_vol)} | {fmt_pct(sell_ratio)}
Delta neto: {sign}{fmt_usd(abs(delta))}
Umbral: {fmt_usd(THRESHOLD_USD)}

@FROX500"""


def analyze_payload(payload):
    buy_vol = float(payload.get("buy_vol_usd", 0))
    sell_vol = float(payload.get("sell_vol_usd", 0))
    total_vol = buy_vol + sell_vol
    delta = buy_vol - sell_vol

    if total_vol < MIN_TOTAL_VOLUME_USD:
        return {
            "should_alert": False,
            "direction": "NONE",
            "delta": delta,
            "reason": "min_total_volume",
        }

    if delta >= THRESHOLD_USD:
        return {
            "should_alert": True,
            "direction": "LONG",
            "delta": delta,
            "reason": "threshold",
        }

    if delta <= -THRESHOLD_USD:
        return {
            "should_alert": True,
            "direction": "SHORT",
            "delta": delta,
            "reason": "threshold",
        }

    return {
        "should_alert": False,
        "direction": "NONE",
        "delta": delta,
        "reason": "below_threshold",
    }


def run_monitor():
    require_env()

    print("COINGLASS_ALERTS_VERSION=2026-07-03")
    print(f"Monitoring {SYMBOL} {RANGE} | threshold={fmt_usd(THRESHOLD_USD)}")

    last_alert_at = None
    last_alert_direction = None
    last_heartbeat_at = None

    while True:
        try:
            payload = fetch_taker_buy_sell()
            price = fetch_bybit_price()
            result = analyze_payload(payload)
            delta = result["delta"]

            now = datetime.now(TZ)
            sign = "+" if delta >= 0 else "-"
            print(
                f"{now.strftime('%Y-%m-%d %H:%M:%S')} {SYMBOL} {RANGE} "
                f"delta={sign}{fmt_usd(abs(delta))} alert={result['should_alert']} "
                f"direction={result['direction']} reason={result['reason']}"
            )

            cooldown_ok = (
                last_alert_at is None
                or datetime.now(TZ) - last_alert_at >= timedelta(minutes=ALERT_COOLDOWN_MINUTES)
            )

            direction_changed = (
                last_alert_direction is not None
                and result["direction"] != "NONE"
                and result["direction"] != last_alert_direction
            )

            if result["should_alert"] and (cooldown_ok or direction_changed):
                message = build_alert_message(payload, price, delta, result["direction"])
                post_telegram_message(message)
                last_alert_at = datetime.now(TZ)
                last_alert_direction = result["direction"]
                print("Alert sent.")

            elif SEND_HEARTBEAT:
                heartbeat_ok = (
                    last_heartbeat_at is None
                    or datetime.now(TZ) - last_heartbeat_at >= timedelta(minutes=HEARTBEAT_EVERY_MINUTES)
                )

                if heartbeat_ok:
                    message = build_heartbeat_message(payload, price, delta)
                    post_telegram_message(message)
                    last_heartbeat_at = datetime.now(TZ)
                    print("Heartbeat sent.")

        except Exception as exc:
            print("Monitor error:", repr(exc))

        if RUN_ONCE:
            break

        time.sleep(CHECK_EVERY_SECONDS)


if __name__ == "__main__":
    run_monitor()
