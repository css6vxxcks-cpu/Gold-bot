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

KRAKEN_API_KEY = os.environ.get('KRAKEN_API_KEY', '')
KRAKEN_API_SECRET = os.environ.get('KRAKEN_API_SECRET', '')
BASE_URL = 'https://api.kraken.com'
PAIR = 'XETHZEUR'
RISK_PERCENT = 0.01
CHECK_INTERVAL = 5
TRADE_LOG_FILE = '/tmp/trade_log.json'

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def load_trade_log():
    try:
        with open(TRADE_LOG_FILE, 'r') as f:
            return json.load(f)
    except:
        return {
            'trades': [],
            'tp_multiplier': 1.0,
            'wins': 0,
            'losses': 0,
            'total_pnl': 0.0
        }

def save_trade_log(log):
    with open(TRADE_LOG_FILE, 'w') as f:
        json.dump(log, f)

def update_tp_multiplier(log):
    trades = log['trades']
    if len(trades) < 3:
        return log['tp_multiplier']
    recent = trades[-10:]
    wins = [t for t in recent if t['result'] == 'win']
    losses = [t for t in recent if t['result'] == 'loss']
    if not wins:
        return max(0.5, log['tp_multiplier'] - 0.05)
    avg_possible = sum(t.get('max_possible_gain', 0) for t in wins) / len(wins)
    avg_actual = sum(t.get('actual_gain', 0) for t in wins) / len(wins)
    if avg_possible > avg_actual * 1.5:
        new_mult = min(3.0, log['tp_multiplier'] + 0.1)
        logging.info(f'TP multiplier aumentato a {new_mult:.2f}')
        return new_mult
    elif len(losses) > len(wins):
        new_mult = max(0.5, log['tp_multiplier'] - 0.05)
        logging.info(f'TP multiplier ridotto a {new_mult:.2f}')
        return new_mult
    return log['tp_multiplier']

def get_kraken_signature(urlpath, data, secret):
    postdata = urllib.parse.urlencode(data)
    encoded = (str(data['nonce']) + postdata).encode()
    message = urlpath.encode() + hashlib.sha256(encoded).digest()
    mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
    sigdigest = base64.b64encode(mac.digest())
    return sigdigest.decode()

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
        logging.error(f'Balance error: {result["error"]}')
        return 0, 0
    balances = result.get('result', {})
    eur = float(balances.get('ZEUR', 0))
    eth = float(balances.get('XETH', 0))
    return eur, eth

def get_open_positions():
    result = kraken_request('/0/private/OpenPositions', {})
    if result.get('error'):
        logging.error(f'Positions error: {result["error"]}')
        return {}
    return result.get('result', {})

def get_eth_price():
    r = requests.get(f'{BASE_URL}/0/public/Ticker?pair={PAIR}')
    data = r.json()
    if data.get('error'):
        return 0
    ticker = data['result'].get(PAIR, {})
    price = float(ticker.get('c', [0])[0])
    return price

def get_ohlc():
    r = requests.get(f'{BASE_URL}/0/public/OHLC?pair={PAIR}&interval=1')
    data = r.json()
    if data.get('error'):
        return []
    return data['result'].get(PAIR, [])

def get_signal(candles):
    if len(candles) < 10:
        return 'hold'
    closes = [float(c[4]) for c in candles[-10:]]
    ma5 = sum(closes[-5:]) / 5
    ma10 = sum(closes) / 10
    current = closes[-1]
    prev = closes[-2]
    prev2 = closes[-3]
    momentum = current - prev2
    if ma5 > ma10 and current > prev and momentum > 0:
        return 'buy'
    elif ma5 < ma10 and current < prev and momentum < 0:
        return 'sell'
    return 'hold'

def place_order(direction, volume, leverage=1):
    data = {
        'pair': PAIR,
        'type': direction,
        'ordertype': 'market',
        'volume': str(round(volume, 5)),
    }
    if leverage > 1:
        data['leverage'] = str(leverage)
    result = kraken_request('/0/private/AddOrder', data)
    logging.info(f'{direction.upper()} {volume:.5f} ETH - Result: {result}')
    return result

def close_short(volume):
    data = {
        'pair': PAIR,
        'type': 'buy',
        'ordertype': 'market',
        'volume': str(round(volume, 5)),
        'leverage': '2'
    }
    result = kraken_request('/0/private/AddOrder', data)
    logging.info(f'CLOSE SHORT {volume:.5f} ETH - Result: {result}')
    return result

def run_bot():
    logging.info('Bot avviato - ETH/EUR Kraken - LONG e SHORT - 24/7')

    in_position = False
    position_type = None
    entry_price = 0
    entry_volume = 0
    peak_price = 0
    trough_price = 999999
    trade_log = load_trade_log()

    while True:
        try:
            eur_balance, eth_balance = get_balance()
            eth_price = get_eth_price()

            if eth_price == 0:
                time.sleep(CHECK_INTERVAL)
                continue

            total_capital = eur_balance + (eth_balance * eth_price)
            tp_mult = trade_log['tp_multiplier']
            take_profit_pct = RISK_PERCENT * tp_mult
            stop_loss_pct = RISK_PERCENT

            logging.info(f'Capitale: {total_capital:.2f} EUR | ETH: {eth_price:.2f} | TP mult: {tp_mult:.2f} | W:{trade_log["wins"]} L:{trade_log["losses"]} | PnL totale: {trade_log["total_pnl"]:.2f} EUR')

            if in_position:
                if position_type == 'long':
                    current_value = entry_volume * eth_price
                    entry_value = entry_volume * entry_price
                    pnl = current_value - entry_value
                    if eth_price > peak_price:
                        peak_price = eth_price
                elif position_type == 'short':
                    pnl = entry_volume * (entry_price - eth_price)
                    if eth_price < trough_price:
                        trough_price = eth_price

                entry_value = entry_volume * entry_price
                take_profit_eur = entry_value * take_profit_pct
                stop_loss_eur = entry_value * stop_loss_pct

                logging.info(f'Posizione {position_type.upper()}: P&L {pnl:.2f} EUR | TP: +{take_profit_eur:.2f} | SL: -{stop_loss_eur:.2f}')

                if pnl >= take_profit_eur:
                    logging.info(f'TAKE PROFIT {position_type.upper()}! +{pnl:.2f} EUR')
                    if position_type == 'long':
                        max_possible = (peak_price - entry_price) * entry_volume
                        place_order('sell', eth_balance if eth_balance > 0.001 else entry_volume)
                    else:
                        max_possible = (entry_price - trough_price) * entry_volume
                        close_short(entry_volume)
                    trade_log['wins'] += 1
                    trade_log['total_pnl'] += pnl
                    trade_log['trades'].append({
                        'result': 'win',
                        'type': position_type,
                        'actual_gain': pnl,
                        'max_possible_gain': max_possible,
                        'entry': entry_price,
                        'exit': eth_price,
                        'timestamp': str(datetime.now())
                    })
                    trade_log['tp_multiplier'] = update_tp_multiplier(trade_log)
                    save_trade_log(trade_log)
                    in_position = False
                    position_type = None

                elif pnl <= -stop_loss_eur:
                    logging.info(f'STOP LOSS {position_type.upper()}! {pnl:.2f} EUR')
                    if position_type == 'long':
                        place_order('sell', eth_balance if eth_balance > 0.001 else entry_volume)
                    else:
                        close_short(entry_volume)
                    trade_log['losses'] += 1
                    trade_log['total_pnl'] += pnl
                    trade_log['trades'].append({
                        'result': 'loss',
                        'type': position_type,
                        'actual_gain': pnl,
                        'entry': entry_price,
                        'exit': eth_price,
                        'timestamp': str(datetime.now())
                    })
                    trade_log['tp_multiplier'] = update_tp_multiplier(trade_log)
                    save_trade_log(trade_log)
                    in_position = False
                    position_type = None

            else:
                candles = get_ohlc()
                signal = get_signal(candles)
                logging.info(f'Segnale: {signal}')

                if signal == 'buy' and eur_balance >= 5:
                    trade_amount = eur_balance * 0.95
                    volume = trade_amount / eth_price
                    logging.info(f'APRO LONG con {trade_amount:.2f} EUR')
                    result = place_order('buy', volume)
                    if result and not result.get('error'):
                        entry_price = eth_price
                        entry_volume = volume
                        peak_price = eth_price
                        position_type = 'long'
                        in_position = True

                elif signal == 'sell' and eur_balance >= 5:
                    trade_amount = eur_balance * 0.95
                    volume = trade_amount / eth_price
                    logging.info(f'APRO SHORT con {trade_amount:.2f} EUR')
                    result = place_order('sell', volume, leverage=2)
                    if result and not result.get('error'):
                        entry_price = eth_price
                        entry_volume = volume
                        trough_price = eth_price
                        position_type = 'short'
                        in_position = True

        except Exception as e:
            logging.error(f'Errore: {e}')

        time.sleep(CHECK_INTERVAL)

if __name__ == '__main__':
    run_bot()
