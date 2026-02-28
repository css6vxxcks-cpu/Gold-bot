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

KRAKEN_API_KEY = os.environ.get(‘KRAKEN_API_KEY’, ‘’)
KRAKEN_API_SECRET = os.environ.get(‘KRAKEN_API_SECRET’, ‘’)
BASE_URL = ‘https://api.kraken.com’
PAIR = ‘XETHZEUR’
RISK_PERCENT = 0.01
CHECK_INTERVAL = 5
TRADE_LOG_FILE = ‘/tmp/trade_log.json’

logging.basicConfig(level=logging.INFO, format=’%(asctime)s - %(message)s’)

def load_trade_log():
try:
with open(TRADE_LOG_FILE, ‘r’) as f:
return json.load(f)
except:
return {
‘trades’: [],
‘tp_multiplier’: 1.0,
‘wins’: 0,
‘losses’: 0,
‘total_pnl’: 0.0,
‘best_possible_tp’: []
}

def save_trade_log(log):
with open(TRADE_LOG_FILE, ‘w’) as f:
json.dump(log, f)

def update_tp_multiplier(log):
trades = log[‘trades’]
if len(trades) < 3:
return log[‘tp_multiplier’]

```
recent = trades[-10:]
wins = [t for t in recent if t['result'] == 'win']

if not wins:
    return max(0.5, log['tp_multiplier'] - 0.05)

avg_possible = sum(t.get('max_possible_gain', 0) for t in wins) / len(wins)
avg_actual = sum(t.get('actual_gain', 0) for t in wins) / len(wins)

if avg_possible > avg_actual * 1.5:
    new_multiplier = min(3.0, log['tp_multiplier'] + 0.1)
    logging.info(f'TP multiplier aumentato a {new_multiplier:.2f} - avrei potuto guadagnare di piu!')
elif len([t for t in recent if t['result'] == 'loss']) > len(wins):
    new_multiplier = max(0.5, log['tp_multiplier'] - 0.05)
    logging.info(f'TP multiplier ridotto a {new_multiplier:.2f} - troppe perdite')
else:
    new_multiplier = log['tp_multiplier']

return new_multiplier
```

def get_kraken_signature(urlpath, data, secret):
postdata = urllib.parse.urlencode(data)
encoded = (str(data[‘nonce’]) + postdata).encode()
message = urlpath.encode() + hashlib.sha256(encoded).digest()
mac = hmac.new(base64.b64decode(secret), message, hashlib.sha512)
sigdigest = base64.b64encode(mac.digest())
return sigdigest.decode()

def kraken_request(uri_path, data):
data[‘nonce’] = str(int(1000 * time.time()))
headers = {
‘API-Key’: KRAKEN_API_KEY,
‘API-Sign’: get_kraken_signature(uri_path, data, KRAKEN_API_SECRET)
}
r = requests.post(BASE_URL + uri_path, headers=headers, data=data)
return r.json()

def get_balance():
result = kraken_request(’/0/private/Balance’, {})
if result.get(‘error’):
logging.error(f’Balance error: {result[“error”]}’)
return 0, 0
balances = result.get(‘result’, {})
eur = float(balances.get(‘ZEUR’, 0))
eth = float(balances.get(‘XETH’, 0))
return eur, eth

def get_eth_price():
r = requests.get(f’{BASE_URL}/0/public/Ticker?pair={PAIR}’)
data = r.json()
if data.get(‘error’):
return 0
ticker = data[‘result’].get(PAIR, {})
price = float(ticker.get(‘c’, [0])[0])
return price

def get_ohlc():
r = requests.get(f’{BASE_URL}/0/public/OHLC?pair={PAIR}&interval=1’)
data = r.json()
if data.get(‘error’):
return []
candles = data[‘result’].get(PAIR, [])
return candles

def simple_signal(candles):
if len(candles) < 10:
return ‘hold’
closes = [float(c[4]) for c in candles[-10:]]
ma5 = sum(closes[-5:]) / 5
ma10 = sum(closes) / 10
current = closes[-1]
prev = closes[-2]
if ma5 > ma10 and current > prev:
return ‘buy’
elif ma5 < ma10 and current < prev:
return ‘sell’
return ‘hold’

def buy_eth(eur_amount, eth_price):
volume = round(eur_amount / eth_price, 5)
if volume < 0.001:
logging.warning(f’Volume troppo basso: {volume} ETH’)
return None
data = {
‘pair’: PAIR,
‘type’: ‘buy’,
‘ordertype’: ‘market’,
‘volume’: str(volume)
}
result = kraken_request(’/0/private/AddOrder’, data)
logging.info(f’BUY {volume} ETH a {eth_price:.2f} EUR - Result: {result}’)
return result

def sell_eth(eth_volume):
volume = round(eth_volume, 5)
if volume < 0.001:
return None
data = {
‘pair’: PAIR,
‘type’: ‘sell’,
‘ordertype’: ‘market’,
‘volume’: str(volume)
}
result = kraken_request(’/0/private/AddOrder’, data)
logging.info(f’SELL {volume} ETH - Result: {result}’)
return result

def run_bot():
logging.info(‘Bot avviato - ETH/EUR Kraken - Modalita SMART 24/7’)

```
in_position = False
entry_price = 0
entry_volume = 0
peak_price = 0
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

        logging.info(f'Capitale: {total_capital:.2f} EUR | ETH: {eth_price:.2f} | TP mult: {tp_mult:.2f} | W:{trade_log["wins"]} L:{trade_log["losses"]}')

        if in_position and eth_balance > 0.001:
            current_value = eth_balance * eth_price
            entry_value = entry_volume * entry_price
            pnl = current_value - entry_value
            pnl_pct = pnl / entry_value

            if eth_price > peak_price:
                peak_price = eth_price

            take_profit_eur = entry_value * take_profit_pct
            stop_loss_eur = entry_value * stop_loss_pct

            logging.info(f'Posizione: P&L {pnl:.2f} EUR ({pnl_pct*100:.2f}%) | TP: +{take_profit_eur:.2f} | SL: -{stop_loss_eur:.2f}')

            if pnl >= take_profit_eur:
                logging.info(f'TAKE PROFIT! +{pnl:.2f} EUR')
                max_possible = (peak_price - entry_price) * entry_volume
                sell_eth(eth_balance)
                trade_log['wins'] += 1
                trade_log['total_pnl'] += pnl
                trade_log['trades'].append({
                    'result': 'win',
                    'actual_gain': pnl,
                    'max_possible_gain': max_possible,
                    'entry': entry_price,
                    'exit': eth_price,
                    'peak': peak_price,
                    'timestamp': str(datetime.now())
                })
                trade_log['tp_multiplier'] = update_tp_multiplier(trade_log)
                save_trade_log(trade_log)
                in_position = False
                entry_price = 0
                entry_volume = 0
                peak_price = 0

            elif pnl <= -stop_loss_eur:
                logging.info(f'STOP LOSS! {pnl:.2f} EUR')
                sell_eth(eth_balance)
                trade_log['losses'] += 1
                trade_log['total_pnl'] += pnl
                trade_log['trades'].append({
                    'result': 'loss',
                    'actual_gain': pnl,
                    'entry': entry_price,
                    'exit': eth_price,
                    'timestamp': str(datetime.now())
                })
                trade_log['tp_multiplier'] = update_tp_multiplier(trade_log)
                save_trade_log(trade_log)
                in_position = False
                entry_price = 0
                entry_volume = 0
                peak_price = 0

        elif not in_position:
            candles = get_ohlc()
            signal = simple_signal(candles)
            logging.info(f'Segnale: {signal}')

            if signal == 'buy' and eur_balance >= 5:
                trade_amount = eur_balance * 0.95
                logging.info(f'COMPRO ETH con {trade_amount:.2f} EUR')
                result = buy_eth(trade_amount, eth_price)
                if result and not result.get('error'):
                    entry_price = eth_price
                    entry_volume = trade_amount / eth_price
                    peak_price = eth_price
                    in_position = True

    except Exception as e:
        logging.error(f'Errore: {e}')

    time.sleep(CHECK_INTERVAL)
```

if **name** == ‘**main**’:
run_bot()
