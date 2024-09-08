import websocket
import json
import requests
import os
import logging
from datetime import datetime, timedelta

# Configure logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

# WebSocket URL
SOCKET = "wss://fstream.binance.com/ws/!forceOrder@arr"

# Telegram Bot token from environment variable
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')

if not TELEGRAM_BOT_TOKEN:
    logging.error("TELEGRAM_BOT_TOKEN environment variable not set")
    raise ValueError("TELEGRAM_BOT_TOKEN environment variable not set")

logging.info("Starting liquidation_alert.py")

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

# Function to format large values
def format_value(value):
    try:
        if value >= 1_000_000:
            return f"{value/1_000_000:.1f}M"
        elif value >= 1_000:
            return f"{value/1_000:.1f}K"
        return str(value)
    except Exception as e:
        logging.error(f"Failed to format value: {e}")
        return str(value)

# Function to process incoming liquidation data
def on_message(ws, message):
    try:
        data = json.loads(message)
        logging.info(f"Received raw data: {data}")

        if 'o' in data:
            try:
                order = data['o']
                symbol = order.get('s', 'Unknown')
                side = "Short" if order.get('S') == 'BUY' else "Long"  # Corrected logic
                price = float(order.get('ap'))
                quantity = float(order.get('q'))
                total_value = price * quantity

                # Only send alerts for liquidations over 400000 USD in value
                if total_value >= 700000:
                    oi_5m = get_open_interest_change(symbol, '5m')
                    oi_15m = get_open_interest_change(symbol, '15m')
                    oi_1h = get_open_interest_change(symbol, '1h')
                    oi_24h = get_open_interest_change(symbol, '1d')
                    price_changes = get_price_change(symbol)
                    volume_change = get_volume_change(symbol)
                    funding_rate = get_funding_rate(symbol)
                    color_emoji = "🟢" if side == "Short" else "🔴"  # Red for short, green for long
                    # Create a message for every received liquidation order
                    message = (
                        f"🔴 #{symbol} ${price:.4f}  | OI changed in 15 mins\n\n"
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
                        f"💲Price ${price:.4f}"
                    )
                    send_telegram_message(message)
                    logging.info(f"Alert sent: {message}")
            except KeyError as e:
                logging.error(f"KeyError: {e} in liquidation {data}")
            except ValueError as e:
                logging.error(f"ValueError: {e} in liquidation {data}")
            except TypeError as e:
                logging.error(f"TypeError: {e} in liquidation {data}")
        else:
            logging.error(f"Unexpected structure: {data}")

    except json.JSONDecodeError as e:
        logging.error(f"JSONDecodeError: {e} for message {message}")
    except Exception as e:
        logging.error(f"Exception in on_message: {e}")

def on_error(ws, error):
    logging.error(f"WebSocket Error: {error}")

def on_close(ws):
    logging.info("### WebSocket closed ###")

def on_open(ws):
    logging.info("### WebSocket opened ###")

def run():
    try:
        websocket.enableTrace(True)
        ws = websocket.WebSocketApp(SOCKET, on_message=on_message, on_error=on_error, on_close=on_close)
        ws.on_open = on_open
        ws.run_forever()
    except Exception as e:
        logging.error(f"Failed to run WebSocket: {e}")

if __name__ == "__main__":
    logging.info("Starting liquidation bot...")
    run()
