import requests
import time
import logging
import os
import base64
from datetime import datetime
import pytz

# Environment variables per Railway
API_KEY = os.environ.get('TRADING212_API_KEY', '')
API_SECRET = os.environ.get('TRADING212_API_SECRET', '')  # AGGIUNTO: serve il secret
BASE_URL = 'https://live.trading212.com/api/v0'
SYMBOL = 'RGLD_US_EQ'  # CORRETTO: formato Trading212 per US stocks
TAKE_PROFIT = 1.0
STOP_LOSS = 1.0
CHECK_INTERVAL = 60

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

# CORRETTO: Basic Auth con API Key + Secret
if not API_KEY or not API_SECRET:
    logging.error("Manca TRADING212_API_KEY o TRADING212_API_SECRET!")
    exit(1)

credentials = base64.b64encode(f"{API_KEY}:{API_SECRET}".encode()).decode()
headers = {
    'Authorization': f'Basic {credentials}',
    'Content-Type': 'application/json'
}

def is_market_open():
    rome = pytz.timezone('Europe/Rome')
    now = datetime.now(rome)
    if now.weekday() >= 5:  # Weekend
        return False
    # NYSE: 15:30-22:00 CET (9:30-16:00 ET)
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
    """Prende prezzo corrente da prima posizione o portfolio"""
    positions = get_positions()
    if positions and isinstance(positions, list):
        for pos in positions:
            if pos.get('ticker') == SYMBOL:
                return float(pos.get('currentPrice', 100))
    return 100  # Default price

def place_order(quantity):
    """Ordinativa unificata buy/sell"""
    payload = {
        'ticker': SYMBOL,
        'quantity': quantity,
        'timeValidity': 'DAY',
        'extendedHours': True  # AGGIUNTO: per pre/after market
    }
    try:
        r = requests.post(f'{BASE_URL}/equity/orders/market', 
                         headers=headers, json=payload, timeout=10)
        logging.info(f'Ordine {quantity>0 and "BUY" or "SELL"} {quantity}: {r.status_code} - {r.text[:200]}')
        return r.json()
    except Exception as e:
        logging.error(f'Errore ordine: {e}')
        return None

def run_bot():
    logging.info('🤖 Bot RGLD Trading212 AVVIATO')
    
    while True:
        try:
            if not is_market_open():
                logging.info('⏸️ Mercato chiuso, attendo 5min...')
                time.sleep(300)
                continue

            # Cash
            cash_data = get_account_cash()
            free_cash = float(cash_data.get('free', 0))
            logging.info(f'💰 Cash libero: {free_cash:.2f} EUR')

            # Posizione RGLD
            positions = get_positions()
            rgld_position = None
            if isinstance(positions, list):
                for pos in positions:
                    if pos.get('ticker') == SYMBOL:
                        rgld_position = pos
                        break

            if rgld_position:
                ppl = float(rgld_position.get('ppl', 0))
                qty = float(rgld_position.get('quantity', 0))
                logging.info(f'📊 RGLD - P&L: {ppl:+.2f}€ Qty: {qty}')

                if ppl >= TAKE_PROFIT:
                    logging.info(f'🎯 TAKE PROFIT! +{ppl:.2f}€')
                    place_order(-qty)  # CORRETTO: negativo per sell
                elif ppl <= -STOP_LOSS:
                    logging.info(f'🛑 STOP LOSS! {ppl:.2f}€')
                    place_order(-qty)  # CORRETTO: negativo per sell
                else:
                    logging.info(f'⏳ Holding - P&L: {ppl:+.2f}€')
            else:
                # No position - apri nuova
                if free_cash >= 10:
                    current_price = get_current_price()
                    trade_amount = min(free_cash * 0.2, 20)
                    quantity = max(0.01, trade_amount / current_price)  # CORRETTO: calcola qty
                    logging.info(f'🚀 Compro {quantity:.3f} azioni (~{trade_amount:.1f}€ @ {current_price:.1f}$)')
                    place_order(quantity)
                else:
                    logging.info(f'❌ Cash basso: {free_cash:.2f}€')

        except KeyboardInterrupt:
            logging.info('🛑 Bot fermato manualmente')
            break
        except Exception as e:
            logging.error(f'💥 Errore: {e}')

        time.sleep(CHECK_INTERVAL)

if __name__ == '__main__':
    run_bot()
