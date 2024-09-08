import time
import requests
import os
import logging
from collections import deque
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
SYMBOLS = ["BTCUSDT", "ETHUSDT" , "MANAUSDT"]

# Price and volume history to track changes over time intervals
price_history = {
    symbol: deque(maxlen=60) for symbol in SYMBOLS  # Store up to 60 prices (one price per minute)
}
volume_history = {
    symbol: deque(maxlen=60) for symbol in SYMBOLS  # Store up to 60 volume data points (one volume per minute)
}

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
        return oi_change
    except Exception as e:
        logging.error(f"Failed to fetch open interest change: {e}")
        return "N/A"

# Fetch latest price and price change percentage for the symbol
def get_price_data(symbol):
    try:
        url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
        params = {"symbol": symbol}
        response = requests.get(url, params=params)
        if response.status_code != 200:
            logging.error(f"Failed to fetch price data: {response.status_code}, {response.text}")
            return {}
        data = response.json()
        price = float(data['lastPrice'])  # Fetch the current price
        price_change_24h = float(data['priceChangePercent'])  # 24-hour price change percentage
        return {
            "price": price,
            "price_change_24h": price_change_24h
        }
    except Exception as e:
        logging.error(f"Failed to fetch price data: {e}")
        return {}

# Fetch 24-hour volume
def get_volume(symbol):
    try:
        url = "https://fapi.binance.com/fapi/v1/ticker/24hr"
        params = {"symbol": symbol}
        response = requests.get(url, params=params)
        if response.status_code != 200:
            logging.error(f"Failed to fetch volume: {response.status_code}, {response.text}")
            return "N/A"
        data = response.json()
        volume = float(data['volume'])  # Current cumulative volume for the last 24 hours
        return volume
    except Exception as e:
        logging.error(f"Failed to fetch volume: {e}")
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
            return f"{funding_rate:.2f}%"
        return "N/A"
    except Exception as e:
        logging.error(f"Failed to fetch funding rate: {e}")
        return "N/A"

# Calculate change percentage with emojis
def calculate_change_with_emoji(current_value, previous_value):
    if previous_value == 0:
        return "N/A"
    change = ((current_value - previous_value) / previous_value) * 100
    if change > 0:
        return f"🟩{change:.3f}%"
    elif change < 0:
        return f"🟥{change:.3f}%"
    else:
        return "⬜0.000%"

# Calculate and return emoji-based OI percentage
def get_open_interest_change_with_emoji(symbol, interval):
    oi_change = get_open_interest_change(symbol, interval)
    if isinstance(oi_change, str):
        return "N/A"
    return calculate_change_with_emoji(oi_change, 0)

# Function to send market data every minute
def fetch_and_send_updates():
    while True:
        for symbol in SYMBOLS:
            # Open Interest Changes
            oi_5m = calculate_change_with_emoji(get_open_interest_change(symbol, '5m'), 0)
            oi_15m = calculate_change_with_emoji(get_open_interest_change(symbol, '15m'), 0)
            oi_1h = calculate_change_with_emoji(get_open_interest_change(symbol, '1h'), 0)
            oi_24h = calculate_change_with_emoji(get_open_interest_change(symbol, '1d'), 0)

            # Price Changes
            price_data = get_price_data(symbol)
            current_price = price_data.get('price', 'N/A')
            price_change_24h = price_data.get('price_change_24h', 'N/A')

            price_history[symbol].append(current_price)
            price_change_1m = calculate_change_with_emoji(current_price, price_history[symbol][-2]) if len(price_history[symbol]) >= 2 else "N/A"
            price_change_5m = calculate_change_with_emoji(current_price, price_history[symbol][-5]) if len(price_history[symbol]) >= 5 else "N/A"
            price_change_15m = calculate_change_with_emoji(current_price, price_history[symbol][-15]) if len(price_history[symbol]) >= 15 else "N/A"
            price_change_1h = calculate_change_with_emoji(current_price, price_history[symbol][-60]) if len(price_history[symbol]) >= 60 else "N/A"

            # Volume Changes
            current_volume = get_volume(symbol)
            volume_history[symbol].append(current_volume)
            volume_change_1m = calculate_change_with_emoji(current_volume, volume_history[symbol][-2]) if len(volume_history[symbol]) >= 2 else "N/A"
            volume_change_15m = calculate_change_with_emoji(current_volume, volume_history[symbol][-15]) if len(volume_history[symbol]) >= 15 else "N/A"
            volume_change_1h = calculate_change_with_emoji(current_volume, volume_history[symbol][-60]) if len(volume_history[symbol]) >= 60 else "N/A"

            # Funding Rate
            funding_rate = get_funding_rate(symbol)

            # Construct and send the message
            message = (
                f"🔴 #{symbol} ${current_price} | OI changed in 15 mins\n\n"
                f"┌ 🌐 Open Interest \n"
                f"├ {oi_5m} (5m) \n"
                f"├ {oi_15m} (15m)\n"
                f"├ {oi_1h} (1h)\n"
                f"└ {oi_24h} (24h)\n\n"
                f"┌ 📈 Price change \n"
                f"├ {price_change_1m} (1m)\n"
                f"├ {price_change_5m} (5m) \n"
                f"├ {price_change_15m} (15m)\n"
                f"├ {price_change_1h} (1h)\n"
                f"└ 🟥{price_change_24h}% (24h)\n\n"
                f"📊 Volume change {volume_change_1m} (1m)\n"
                f"📊 Volume change {volume_change_15m} (15m)\n"
                f"📊 Volume change {volume_change_1h} (1h)\n"
                f"📊 Volume: {current_volume:,.2f} (24h)\n"
                f"➕ Funding rate {funding_rate}\n"
                f"💲Price ${current_price}"
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
