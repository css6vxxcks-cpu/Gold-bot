import requests
import time
import logging
import os
import base64
from datetime import datetime
import pytz

# DEMO MODE - $100k+ disponibili
API_KEY = os.environ.get('TRADING212_API_KEY', '')
API_SECRET = os.environ.get('TRADING212_API_SECRET', '')
BASE_URL = 'https://demo.trading212.com/api/v0'  # ✅ DEMO
SYMBOL = 'RGLD_US_EQ'

# SCALATO PER DEMO ($100k vs €20 live)
TAKE_PROFIT = 100.0      # $100 (5x più grande)
STOP_LOSS = 100.0        # $100 (5x più grande)  
CHECK_INTERVAL = 60

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

if not API_KEY or not API_SECRET:
    logging.error("❌ Manca TRADING212_API_KEY o TRADING212_API_SECRET!")
    exit(1)

credentials = base64.b64encode(f"{API_KEY}:{API_SECRET}".encode()).decode()
headers = {
    'Authorization': f'Basic {credentials}',
    'Content-Type': 'application/json'
}

def is_market_open():
    rome = pytz.timezone('Europe/Rome')
    now = datetime.now(rome)
    if now.weekday() >= 5:
        return False
    if now.hour < 15 or now.hour >= 22:
        return False
    if now.hour == 15 and now.minute < 30:
        return False
    return True

def get_account_cash():
    try:
        r = requests.get(f'{BASE_URL}/equity/account/cash', headers=headers, timeout=10)
        logging.info(f'Cash status: {r.status_code}')
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logging.error(f'Errore cash: {e}')
        return {'free': 0}

def get_positions():
    try:
        r = requests.get(f'{BASE_URL}/equity/portfolio', headers=headers, timeout=10)
        logging.info(f'Portfolio status: {r.status_code}')
        r.raise_for_status()
        return r.json()
    except Exception as e:
        logging.error(f'Errore portfolio: {e}')
        return []

def get_current_price():
    positions = get_positions()
    if positions and isinstance(positions, list):
        for pos in positions:
            if pos.get('ticker') == SYMBOL:
                return float(pos.get('currentPrice', 150))
    return 150  # Prezzo RGLD approssimativo

def place_order(quantity):
    payload = {
        'ticker': SYMBOL,
        'quantity': quantity,
        'timeValidity': 'DAY',
        'extendedHours': True
    }
    try:
        r = requests.post(f'{BASE_URL}/equity/orders/market', 
                         headers=headers, json=payload, timeout=10)
        logging.info(f'📈 Ordine {"BUY" if quantity>0 else "SELL"} {abs(quantity):.2f}: {r.status_code}')
        return r.json()
    except Exception as e:
        logging.error(f'❌ Errore ordine: {e}')
        return None

def run_bot():
    logging.info('🤖 Bot RGLD DEMO ($100k) AVVIATO - TP/SL $100')

    while True:
        try:
            if not is_market_open():
                logging.info('⏸️ Mercato chiuso (NYSE), attendo 5min...')
                time.sleep(300)
                continue

            cash_data = get_account_cash()
            free_cash = float(cash_data.get('free', 0))
            logging.info(f'💰 Cash libero: ${free_cash:,.2f}')

            positions = get_positions()
            rgld_position = None
            for pos in positions:
                if pos.get('ticker') == SYMBOL:
                    rgld_position = pos
                    break

            if rgld_position:
                ppl = float(rgld_position.get('ppl', 0))
                qty = float(rgld_position.get('quantity', 0))
                price = float(rgld_position.get('currentPrice', 150))
                value = qty * price
                logging.info(f'📊 RGLD: {qty:.2f} shares @ ${price:.1f} = ${value:,.0f} | P&L: ${ppl:,.2f}')

                if ppl >= TAKE_PROFIT:
                    logging.info(f'🎯 TAKE PROFIT! +${ppl:,.2f} (${TAKE_PROFIT} target)')
                    place_order(-qty)
                elif ppl <= -STOP_LOSS:
                    logging.info(f'🛑 STOP LOSS! -${abs(ppl):,.2f} (${STOP_LOSS} target)')
                    place_order(-qty)
                else:
                    logging.info(f'⏳ Holding | P&L: ${ppl:+,.2f} | TP:${TAKE_PROFIT} SL:${STOP_LOSS}')
            else:
                # No position → compra con 2% del cash (scalato per demo)
                if free_cash >= 1000:  # Min $1000 per trade demo
                    current_price = get_current_price()
                    trade_value = min(free_cash * 0.02, 5000)  # Max $5k per trade
                    quantity = max(1.0, trade_value / current_price)  # Min 1 share
                    logging.info(f'🚀 COMPRA {quantity:.1f} shares (~${trade_value:,.0f} @ ${current_price:.0f})')
                    place_order(quantity)
                else:
                    logging.info(f'❌ Cash basso: ${free_cash:,.2f}')

        except KeyboardInterrupt:
            logging.info('🛑 Bot fermato')
            break
        except Exception as e:
            logging.error(f'💥 Errore: {e}')

        time.sleep(CHECK_INTERVAL)

if __name__ == '__main__':
    run_bot()
