import requests
import time
import logging
import os
import hmac
import hashlib
import base64
import urllib.parse
import json
from datetime import datetime

# ===================== CONFIG =====================

KRAKEN_API_KEY = os.environ.get('KRAKEN_API_KEY', '')
KRAKEN_API_SECRET = os.environ.get('KRAKEN_API_SECRET', '')

BASE_URL = 'https://api.kraken.com'
PAIR = 'XETHZEUR'

TAKE_PROFIT_PCT = 0.03      # +3%
STOP_LOSS_PCT = 0.02        # -2%
TRAILING_START = 0.02       # trailing attivo da +2%
TRAILING_GIVEBACK = 0.01    # lascia 1%
COOLDOWN_SECONDS = 300      # 5 minuti
ATR_PERIOD = 14
MIN_ATR_PCT = 0.0025        # filtro volatilità
CHECK_INTERVAL = 10
TRADE_LOG_FILE = 'trade_log.json'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')


# ===================== UTIL =====================

def get_kraken_signature(urlpath, data, secret):
    postdata = urllib.parse.urlencode(data)
    encoded = (str(data['nonce']) + postdata).encode()
    message = urlpath.encode() + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    return base64.b64encode(mac.digest()).decode()


def kraken_request(uri_path, data):
    data['nonce'] = str(int(1000 * time.time()))
    headers = {
        'API-Key': KRAKEN_API_KEY,
        'API-Sign': get_kraken_signature(uri_path, data, KRAKEN_API_SECRET)
    }
    r = requests.post(BASE_URL + uri_path, headers=headers, data=data)
    return r.json()


def get_balance():
    result = kraken_request('/0/private/Balance', {})
    if result.get('error'):
        logging.error(result['error'])
        return 0, 0
    balances = result['result']
    eur = float(balances.get('ZEUR', 0))
    eth = float(balances.get('XETH', 0))
    return eur, eth


def get_price():
    r = requests.get(f'{BASE_URL}/0/public/Ticker?pair={PAIR}')
    data = r.json()
    return float(data['result'][PAIR]['c'][0])


def get_ohlc(interval=1):
    r = requests.get(f'{BASE_URL}/0/public/OHLC?pair={PAIR}&interval={interval}')
    data = r.json()
    return data['result'][PAIR]


# ===================== INDICATORS =====================

def calculate_atr(candles, period=14):
    if len(candles) < period + 1:
        return 0

    trs = []
    for i in range(-period, 0):
        high = float(candles[i][2])
        low = float(candles[i][3])
        prev_close = float(candles[i-1][4])
        tr = max(high - low, abs(high - prev_close), abs(low - prev_close))
        trs.append(tr)

    return sum(trs) / period


def advanced_signal():
    candles_1m = get_ohlc(1)
    if len(candles_1m) < 20:
        return "hold"

    closes_1m = [float(c[4]) for c in candles_1m[-20:]]
    ma5 = sum(closes_1m[-5:]) / 5
    ma20 = sum(closes_1m) / 20

    candles_5m = get_ohlc(5)
    if len(candles_5m) < 20:
        return "hold"

    closes_5m = [float(c[4]) for c in candles_5m[-20:]]
    ma5_5m = sum(closes_5m[-5:]) / 5
    ma20_5m = sum(closes_5m) / 20

    atr = calculate_atr(candles_1m, ATR_PERIOD)
    current_price = closes_1m[-1]
    atr_pct = atr / current_price

    if atr_pct < MIN_ATR_PCT:
        return "hold"

    if ma5 > ma20 and ma5_5m > ma20_5m:
        return "buy"

    return "hold"


# ===================== TRADING =====================

def buy_all(eur_balance, price):
    volume = round(eur_balance / price, 5)
    if volume < 0.001:
        return None

    data = {
        'pair': PAIR,
        'type': 'buy',
        'ordertype': 'market',
        'volume': str(volume)
    }

    result = kraken_request('/0/private/AddOrder', data)
    logging.info(f'BUY {volume} ETH @ {price}')
    return result


def sell_all(eth_balance):
    volume = round(eth_balance, 5)
    if volume < 0.001:
        return None

    data = {
        'pair': PAIR,
        'type': 'sell',
        'ordertype': 'market',
        'volume': str(volume)
    }

    result = kraken_request('/0/private/AddOrder', data)
    logging.info(f'SELL {volume} ETH')
    return result


# ===================== BOT LOOP =====================

def run_bot():

    logging.info("🔥 AI DUEL MODE STARTED 🔥")

    in_position = False
    entry_price = 0
    entry_volume = 0
    peak_price = 0
    last_trade_time = 0

    while True:
        try:

            eur_balance, eth_balance = get_balance()
            price = get_price()

            if in_position and eth_balance > 0.001:

                current_value = eth_balance * price
                entry_value = entry_volume * entry_price
                pnl_pct = (current_value - entry_value) / entry_value

                if price > peak_price:
                    peak_price = price

                trailing_stop = peak_price * (1 - TRAILING_GIVEBACK)

                logging.info(f'PnL: {pnl_pct*100:.2f}%')

                # TAKE PROFIT
                if pnl_pct >= TAKE_PROFIT_PCT:
                    logging.info("✅ TAKE PROFIT 3%")
                    sell_all(eth_balance)
                    in_position = False
                    last_trade_time = time.time()

                # TRAILING
                elif pnl_pct >= TRAILING_START and price < trailing_stop:
                    logging.info("📉 TRAILING STOP")
                    sell_all(eth_balance)
                    in_position = False
                    last_trade_time = time.time()

                # STOP LOSS
                elif pnl_pct <= -STOP_LOSS_PCT:
                    logging.info("❌ STOP LOSS 2%")
                    sell_all(eth_balance)
                    in_position = False
                    last_trade_time = time.time()

            elif not in_position:

                if time.time() - last_trade_time < COOLDOWN_SECONDS:
                    time.sleep(CHECK_INTERVAL)
                    continue

                signal = advanced_signal()
                logging.info(f"Segnale: {signal}")

                if signal == "buy" and eur_balance > 5:
                    result = buy_all(eur_balance, price)
                    if result and not result.get('error'):
                        entry_price = price
                        entry_volume = eur_balance / price
                        peak_price = price
                        in_position = True

        except Exception as e:
            logging.error(f"Errore: {e}")

        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    run_bot()
