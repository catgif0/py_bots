import time
import requests
import os
import logging
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from threading import Thread

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# Telegram Bot token from environment variable
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
if not TELEGRAM_BOT_TOKEN:
    logging.error("TELEGRAM_BOT_TOKEN environment variable not set")
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")

# Symbols to monitor (You can add more symbols here)
SYMBOLS = ["BTCUSDT", "ETHUSDT"]

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

# Fetch open interest change for the symbol
def get_open_interest_change(symbol, interval):
    try:
        url = "https://fapi.binance.com/futures/data/openInterestHist"
        params = {
            "symbol": symbol,
            "period": interval,
            "limit": 2  # We need the last two data points to calculate the change
        }
        response = requests.get(url, params=params)
        if response.status_code != 200:
            logging.error(f"Failed to fetch open interest: {response.status_code}, {response.text}")
            return "N/A"
        data = response.json()
        if len(data) < 2:
            return "N/A"
        oi_change = ((float(data[-1]['sumOpenInterest']) - float(data[-2]['sumOpenInterest'])) / float(data[-2]['sumOpenInterest'])) * 100
        return f"{oi_change:.2f}%"
    except Exception as e:
        logging.error(f"Failed to fetch open interest change: {e}")
        return "N/A"

# Fetch price change percentage for the symbol
def get_price_change(symbol):
    try:
        url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
        params = {"symbol": symbol}
        response = requests.get(url, params=params)
        if response.status_code != 200:
            logging.error(f"Failed to fetch price change: {response.status_code}, {response.text}")
            return {}
        data = response.json()
        return {
            "5m": "N/A",  # Binance API doesn't provide 5m changes, but we can calculate this if needed
            "15m": "N/A",  # Same for 15m
            "1h": f"{float(data['priceChangePercent'])}%",
            "24h": f"{float(data['priceChangePercent'])}%"
        }
    except Exception as e:
        logging.error(f"Failed to fetch price change: {e}")
        return {}

# Fetch 24-hour volume change
def get_volume_change(symbol):
    try:
        url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
        params = {"symbol": symbol}
        response = requests.get(url, params=params)
        if response.status_code != 200:
            logging.error(f"Failed to fetch volume change: {response.status_code}, {response.text}")
            return "N/A"
        data = response.json()
        return f"{float(data['volume'])}"
    except Exception as e:
        logging.error(f"Failed to fetch volume change: {e}")
        return "N/A"

# Function to fetch the latest funding rate
def get_funding_rate(symbol):
    try:
        url = "https://fapi.binance.com/fapi/v1/fundingRate"
        params = {
            "symbol": symbol,
            "limit": 1
        }
        response = requests.get(url, params=params)
        if response.status_code != 200:
            logging.error(f"Failed to fetch funding rate: {response.status_code}, {response.text}")
            return "N/A"
        data = response.json()
        if len(data) > 0:
            funding_rate = float(data[0]["fundingRate"]) * 100
            return f"{funding_rate:.2f}"
        return "N/A"
    except Exception as e:
        logging.error(f"Failed to fetch funding rate: {e}")
        return "N/A"

# Function to send market data every minute
def fetch_and_send_updates():
    while True:
        for symbol in SYMBOLS:
            oi_5m = get_open_interest_change(symbol, '5m')
            oi_15m = get_open_interest_change(symbol, '15m')
            oi_1h = get_open_interest_change(symbol, '1h')
            oi_24h = get_open_interest_change(symbol, '1d')
            price_changes = get_price_change(symbol)
            volume_change = get_volume_change(symbol)
            funding_rate = get_funding_rate(symbol)
            price = price_changes.get('1h', 'N/A')  # Placeholder for the current price, should be from the price ticker

            message = (
                f"🔴 #{symbol} ${price} | OI changed in 15 mins\n\n"
                f"┌ 🌐 Open Interest \n"
                f"├ 🟥{oi_5m} (5m) \n"
                f"├ 🟥{oi_15m} (15m)\n"
                f"├ 🟥{oi_1h} (1h)\n"
                f"└ 🟥{oi_24h} (24h)\n\n"
                f"┌ 📈 Price change \n"
                f"├ 🟥{price_changes.get('5m', 'N/A')} (5m) \n"
                f"├ 🟥{price_changes.get('15m', 'N/A')} (15m)\n"
                f"├ 🟥{price_changes.get('1h', 'N/A')} (1h)\n"
                f"└ 🟥{price_changes.get('24h', 'N/A')} (24h)\n\n"
                f"📊 Volume change {volume_change}% (24h)\n"
                f"➕ Funding rate {funding_rate}%\n"
                f"💲Price ${price}"
            )
            send_telegram_message(message)

        # Wait for 1 minute before fetching data again
        time.sleep(60)

# API Endpoint to check the status of the bot
@app.get("/status")
async def status():
    return JSONResponse(content={"status": "Bot is running", "websocket": "connected"})


# Background task to run the data fetching process
@app.on_event("startup")
async def startup_event():
    thread = Thread(target=fetch_and_send_updates)
    thread.daemon = True
    thread.start()

if __name__ == "__main__":
    import uvicorn
    logging.info("Starting FastAPI with periodic updates...")
    uvicorn.run(app, host="0.0.0.0", port=8080)
