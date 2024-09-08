import websocket
import json
import requests
import os
import logging
import random
from threading import Timer

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# WebSocket URL (Example: Binance Futures WebSocket)
SOCKET = "wss://fstream.binance.com/ws/!ticker@arr"

# Telegram Bot token from environment variable
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

if not TELEGRAM_BOT_TOKEN:
    logging.error("TELEGRAM_BOT_TOKEN environment variable not set")
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")

logging.info("Starting market_alert.py")

# List of trading pairs (you can add more pairs)
TRADING_PAIRS = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'CETUSUSDT', 'SOLUSDT', 'XRPUSDT']

# Pick 3-4 random pairs to track
SELECTED_PAIRS = random.sample(TRADING_PAIRS, random.randint(3, 4))

# Variables to store the latest data for selected pairs
latest_data = {pair: {} for pair in SELECTED_PAIRS}

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

def get_chat_ids():
    try:
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
                    chat_ids.add(chat_id)

        return list(chat_ids)
    except Exception as e:
        logging.error(f"Failed to get chat IDs: {e}")
        return []

# Function to create a formatted message for each pair
def create_message(pair, data):
    message = (
        f"🟢 #{pair} ${data['price']} | OI changed in 15 mins\n\n"
        f"┌ 🌐 Open Interest\n"
        f"├ 🟩{data['oi_5m']} (5m)\n"
        f"├ 🟩{data['oi_15m']} (15m)\n"
        f"├ 🟩{data['oi_1h']} (1h)\n"
        f"└ 🟩{data['oi_24h']} (24h)\n\n"
        f"┌ 📈 Price change\n"
        f"├ 🟥{data['price_change_5m']} (5m)\n"
        f"├ 🟩{data['price_change_15m']} (15m)\n"
        f"├ 🟩{data['price_change_1h']} (1h)\n"
        f"└ 🟩{data['price_change_24h']} (24h)\n\n"
        f"📊 Volume change {data['volume_change_24h']} (24h)\n"
        f"➕ Funding rate {data['funding_rate']}%\n"
        f"💲Price ${data['price']}\n\n"
        f"Daily low: ${data['daily_low']}\n"
        f"Weekly low: ${data['weekly_low']}"
    )
    return message

# Function to process WebSocket messages for selected pairs
def on_message(ws, message):
    global latest_data
    data = json.loads(message)

    for ticker in data:
        symbol = ticker.get('s')
        if symbol in SELECTED_PAIRS:  # Process only selected pairs
            latest_data[symbol] = {
                'price': ticker.get('c'),
                'price_change_5m': ticker.get('P'),
                'price_change_15m': ticker.get('P'),
                'price_change_1h': ticker.get('P'),
                'price_change_24h': ticker.get('P'),
                'volume_change_24h': ticker.get('q'),  # Example field for volume
                'funding_rate': "0.0029",  # Placeholder, fetch actual funding rate
                'oi_5m': "+2.43%",  # Placeholder
                'oi_15m': "+31.02%",  # Placeholder
                'oi_1h': "+62.51%",  # Placeholder
                'oi_24h': "+60.38%",  # Placeholder
                'daily_low': ticker.get('c'),  # Placeholder, fetch actual low
                'weekly_low': ticker.get('c')  # Placeholder, fetch actual low
            }

# Function to send message every 2 minutes
def periodic_alert():
    global latest_data
    for pair in SELECTED_PAIRS:
        if latest_data[pair]:
            message = create_message(pair, latest_data[pair])
            send_telegram_message(message)
    Timer(120, periodic_alert).start()  # Schedule to run every 2 minutes (120 seconds)

# WebSocket error handling
def on_error(ws, error):
    logging.error(f"WebSocket Error: {error}")

# WebSocket close handling
def on_close(ws):
    logging.info("### WebSocket closed ###")

# WebSocket open handling
def on_open(ws):
    logging.info("### WebSocket opened ###")

# WebSocket runner
def run():
    websocket.enableTrace(True)
    ws = websocket.WebSocketApp(SOCKET, on_message=on_message, on_error=on_error, on_close=on_close)
    ws.on_open = on_open
    ws.run_forever()

if __name__ == "__main__":
    logging.info(f"Starting market data bot with selected pairs: {SELECTED_PAIRS}")
    periodic_alert()  # Start sending messages every 2 minutes
    run()  # Start WebSocket connection

