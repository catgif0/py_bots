import time
import requests
import os
import logging
from collections import deque
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from threading import Thread
from datetime import datetime, timedelta
import schedule

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Telegram Bot token from environment variable
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TELEGRAM_BOT_TOKEN:
    logging.error("TELEGRAM_BOT_TOKEN environment variable not set")
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")

# Symbols to monitor (initial empty list)
SYMBOLS = []
VALID_SYMBOLS = set()

# Price and volume history to track changes over time intervals
price_history = {}
volume_history = {}

# Initialize FastAPI app
app = FastAPI()

logging.info("Starting signal_bot.py")

# Function to send a message to Telegram
def send_telegram_message(message):
    try:
        chat_ids = get_chat_ids()
        if not chat_ids:
            logging.error("No chat IDs found where the bot is admin or in private chats.")
            return
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        for chat_id in chat_ids:
            payload = {
                'chat_id': chat_id,
                'text': message,
                'parse_mode': 'HTML'
            }
            response = requests.post(url, data=payload)
            logging.info(f"Sending to Telegram chat {chat_id}: {message}")
            logging.info(f"Telegram response: {response.status_code}, {response.text}")
    except Exception as e:
        logging.error(f"Failed to send Telegram message: {e}")

# Function to get chat IDs from Telegram
def get_chat_ids():
    try:
        logging.info("Fetching updates to identify chat IDs...")
        updates_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates"
        response = requests.get(updates_url)
        if response.status_code != 200:
            logging.error(f"Failed to fetch updates: {response.status_code}, {response.text}")
            return []
        data = response.json()
        chat_ids = set()

        if 'result' in data:
            for update in data['result']:
                if 'message' in update or 'channel_post' in update:
                    chat = update.get('message', update.get('channel_post')).get('chat')
                    chat_id = chat['id']
                    chat_type = chat['type']
                    logging.info(f"Found chat ID: {chat_id} of type {chat_type}. Checking if bot is an admin...")
                    if chat_type == 'private':
                        chat_ids.add(chat_id)
                    else:
                        admin_check_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getChatAdministrators?chat_id={chat_id}"
                        admin_response = requests.get(admin_check_url)
                        admin_data = admin_response.json()
                        if admin_response.status_code == 200 and 'result' in admin_data:
                            for admin in admin_data['result']:
                                if admin['user']['id'] == int(TELEGRAM_BOT_TOKEN.split(':')[0]):
                                    chat_ids.add(chat_id)
        return list(chat_ids)
    except Exception as e:
        logging.error(f"Failed to get chat IDs: {e}")
        return []

# Fetch valid symbols from Binance and store them
def fetch_valid_symbols():
    global VALID_SYMBOLS
    try:
        logging.info("Fetching valid trading symbols from Binance...")
        url = "https://api.binance.com/api/v3/ticker/24hr"
        response = requests.get(url)
        if response.status_code != 200:
            logging.error(f"Failed to fetch valid symbols: {response.status_code}, {response.text}")
            return
        data = response.json()
        VALID_SYMBOLS = {item['symbol'] for item in data}
        logging.info(f"Valid symbols fetched: {len(VALID_SYMBOLS)} symbols.")
    except Exception as e:
        logging.error(f"Error fetching valid symbols: {e}")

# Fetch dynamic symbols based on volume < 1 million USDT in the last 24 hours
def update_symbols():
    try:
        logging.info("Fetching dynamic symbols with volume less than 1M USDT...")
        url = "https://api.binance.com/api/v3/ticker/24hr"
        response = requests.get(url)
        if response.status_code != 200:
            logging.error(f"Failed to fetch symbols: {response.status_code}, {response.text}")
            return
        data = response.json()
        
        global SYMBOLS
        SYMBOLS = [
            item['symbol'] for item in data
            if item['symbol'].endswith("USDT") and float(item['quoteVolume']) < 1_000_000 and item['symbol'] in VALID_SYMBOLS
        ]
        
        logging.info(f"Symbols updated: {SYMBOLS}")
        
        # Re-initialize price and volume history for the new symbols
        global price_history, volume_history
        price_history = {symbol: deque(maxlen=60) for symbol in SYMBOLS}
        volume_history = {symbol: deque(maxlen=60) for symbol in SYMBOLS}
        
    except Exception as e:
        logging.error(f"Failed to update symbols: {e}")

# Function to fetch open interest change for the symbol
def get_open_interest_change(symbol, interval):
    try:
        if symbol not in VALID_SYMBOLS:
            logging.warning(f"Skipping invalid symbol: {symbol}")
            return None
        url = "https://fapi.binance.com/futures/data/openInterestHist"
        params = {
            "symbol": symbol,
            "period": interval,
            "limit": 2
        }
        response = requests.get(url, params=params)
        if response.status_code != 200:
            logging.error(f"Failed to fetch open interest: {response.status_code}, {response.text}")
            return None
        data = response.json()
        if len(data) < 2:
            return None
        oi_change = ((float(data[-1]['sumOpenInterest']) - float(data[-2]['sumOpenInterest'])) / float(data[-2]['sumOpenInterest'])) * 100
        return oi_change
    except Exception as e:
        logging.error(f"Failed to fetch open interest change: {e}")
        return None

# Fetch price data for the symbol
def get_price_data(symbol):
    try:
        if symbol not in VALID_SYMBOLS:
            logging.warning(f"Skipping invalid symbol: {symbol}")
            return {}
        url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
        params = {"symbol": symbol}
        response = requests.get(url, params=params)
        if response.status_code != 200:
            logging.error(f"Failed to fetch price data: {response.status_code}, {response.text}")
            return {}
        data = response.json()
        price = float(data['lastPrice'])  # Current price
        price_change_24h = float(data['priceChangePercent'])  # 24-hour price change
        return {
            "price": price,
            "price_change_24h": price_change_24h
        }
    except Exception as e:
        logging.error(f"Failed to fetch price data: {e}")
        return {}

# Fetch volume data
def get_volume(symbol):
    try:
        if symbol not in VALID_SYMBOLS:
            logging.warning(f"Skipping invalid symbol: {symbol}")
            return "N/A"
        url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
        params = {"symbol": symbol}
        response = requests.get(url, params=params)
        if response.status_code != 200:
            logging.error(f"Failed to fetch volume: {response.status_code}, {response.text}")
            return "N/A"
        data = response.json()
        volume = float(data['volume'])
        return volume
    except Exception as e:
        logging.error(f"Failed to fetch volume: {e}")
        return "N/A"

# Signal generation logic here...

# Function to monitor pairs and generate signals
def monitor_pairs():
    for symbol in SYMBOLS:
        oi_5m = get_open_interest_change(symbol, '5m')
        oi_15m = get_open_interest_change(symbol, '15m')
        oi_1h = get_open_interest_change(symbol, '1h')
        oi_24h = get_open_interest_change(symbol, '1d')
        
        price_data = get_price_data(symbol)
        current_price = price_data.get("price", None)
        
        price_history[symbol].append(current_price)
        
        price_change_1m = ((current_price - price_history[symbol][-2]) / price_history[symbol][-2]) * 100 if len(price_history[symbol]) >= 2 else None
        price_change_5m = ((current_price - price_history[symbol][-5]) / price_history[symbol][-5]) * 100 if len(price_history[symbol]) >= 5 else None
        price_change_15m = ((current_price - price_history[symbol][-15]) / price_history[symbol][-15]) * 100 if len(price_history[symbol]) >= 15 else None
        price_change_1h = ((current_price - price_history[symbol][-60]) / price_history[symbol][-60]) * 100 if len(price_history[symbol]) >= 60 else None
        price_change_24h = price_data.get("price_change_24h", None)

        current_volume = get_volume(symbol)
        volume_history[symbol].append(current_volume)
        volume_change_1m = ((current_volume - volume_history[symbol][-2]) / volume_history[symbol][-2]) * 100 if len(volume_history[symbol]) >= 2 else None
        volume_change_5m = ((current_volume - volume_history[symbol][-5]) / volume_history[symbol][-5]) * 100 if len(volume_history[symbol]) >= 5 else None
        volume_change_15m = ((current_volume - volume_history[symbol][-15]) / volume_history[symbol][-15]) * 100 if len(volume_history[symbol]) >= 15 else None
        volume_change_1h = ((current_volume - volume_history[symbol][-60]) / volume_history[symbol][-60]) * 100 if len(volume_history[symbol]) >= 60 else None

        # Check for signal generation and send to Telegram (similar logic as before)

# Schedule symbol update every 24 hours at 5:30 GMT
schedule.every().day.at("05:30").do(update_symbols)

# Fetch valid symbols on startup
fetch_valid_symbols()

# Update symbols on startup
update_symbols()

# Start monitoring pairs every minute
while True:
    schedule.run_pending()
    monitor_pairs()
    time.sleep(60)
