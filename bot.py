import requests
import time
import logging
from datetime import datetime

# Configurazione
API_KEY = "4208665ZkKXxRAYXBVIIWEiQOoiVvleFfkfY"
BASE_URL = "https://live.trading212.com/api/v0"
SYMBOL = "RGLD"
TAKE_PROFIT = 1.0
STOP_LOSS = 1.0
CHECK_INTERVAL = 60  # secondi tra ogni controllo

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

headers = {
    "Authorization": API_KEY,
    "Content-Type": "application/json"
}

def get_account_cash():
    r = requests.get(f"{BASE_URL}/equity/account/cash", headers=headers)
    return r.json()

def get_positions():
    r = requests.get(f"{BASE_URL}/equity/portfolio", headers=headers)
    return r.json()

def get_instruments():
    r = requests.get(f"{BASE_URL}/equity/metadata/instruments", headers=headers)
    return r.json()

def place_order(quantity, direction="BUY"):
    payload = {
        "ticker": SYMBOL,
        "quantity": quantity,
        "limitPrice": None,
        "stopPrice": None,
        "timeValidity": "DAY"
    }
    if direction == "BUY":
        r = requests.post(f"{BASE_URL}/equity/orders/market", headers=headers, json=payload)
    else:
        r = requests.post(f"{BASE_URL}/equity/orders/market", headers=headers, json=payload)
    return r.json()

def calculate_rsi(prices, period=14):
    if len(prices) < period + 1:
        return None
    gains = []
    losses = []
    for i in range(1, period + 1):
        diff = prices[i] - prices[i-1]
        if diff > 0:
            gains.append(diff)
            losses.append(0)
        else:
            gains.append(0)
            losses.append(abs(diff))
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

price_history = []

def run_bot():
    logging.info("Bot avviato - Trading oro XAU/USD")
    position_open = False
    entry_price = 0
    quantity = 0

    while True:
        try:
            cash_data = get_account_cash()
            logging.info(f"Conto: {cash_data}")

            positions = get_positions()
            
            # Controlla posizioni aperte
            gold_position = None
            for pos in positions if isinstance(positions, list) else []:
                if pos.get("ticker") == SYMBOL:
                    gold_position = pos
                    break

            if gold_position:
                current_price = float(gold_position.get("currentPrice", 0))
                ppl = float(gold_position.get("ppl", 0))
                logging.info(f"Posizione aperta - P&L: {ppl:.2f}€")

                # Chiudi se raggiunto TP o SL
                if ppl >= TAKE_PROFIT:
                    logging.info(f"✅ Take profit raggiunto! +{ppl:.2f}€")
                    # Chiudi posizione
                    qty = float(gold_position.get("quantity", 0))
                    place_order(qty, "SELL")
                    logging.info("Posizione chiusa")
                elif ppl <= -STOP_LOSS:
                    logging.info(f"❌ Stop loss raggiunto! {ppl:.2f}€")
                    qty = float(gold_position.get("quantity", 0))
                    place_order(qty, "SELL")
                    logging.info("Posizione chiusa")
            else:
                # Nessuna posizione - valuta se aprire
                free_cash = float(cash_data.get("free", 0)) if isinstance(cash_data, dict) else 0
                logging.info(f"Cash disponibile: {free_cash:.2f}€")

                if free_cash > 10:
                    # Usa il 10% del capitale per operazione
                    trade_amount = min(free_cash * 0.1, 20)
                    logging.info(f"Apro posizione con {trade_amount:.2f}€")
                    # Quantità minima per oro (dipende da T212)
                    result = place_order(0.01, "BUY")
                    logging.info(f"Ordine: {result}")

        except Exception as e:
            logging.error(f"Errore: {e}")

        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    run_bot()
