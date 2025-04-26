import requests
import json
import websocket
import time
import threading
import uuid
import base64
from datetime import datetime

# Define the URL for the initial POST request
url = "https://director.getgrass.io/checkin"

# Define the payload
payload = {
    "browserId": "53089d54-d47b-5e39-abb1-f8fadd90c3e5",
    "deviceType": "extension",
    "extensionId": "ilehaonighjijnmpnagapkhpcdbhclfg",
    "userAgent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
    "userId": "2gh63HX35H0KAPIZPKiVsbUFQn2",
    "version": "5.3.1"
}

# Define the headers for the POST request
headers = {
    "Accept": "*/*",
    "Accept-Encoding": "gzip, deflate, br, zstd",
    "Accept-Language": "en-US,en;q=0.9",
    "Content-Type": "application/json",
    "Origin": "chrome-extension://ilehaonighjijnmpnagapkhpcdbhclfg",
    "Priority": "u=1, i",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "none",
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36"
}

# Helper function to get timestamp
def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

# Helper function to encode body to Base64
def array_buffer_to_base64(data):
    return base64.b64encode(data.encode()).decode()

# Function to establish WebSocket connection
def connect_websocket(destinations, token, ws_headers):
    max_destinations = len(destinations) - 1
    retries = 0
    last_destination_index = 0

    def on_open(ws):
        print(f"[{get_timestamp()}] WebSocket connection opened")
        ws.last_message_time = time.time()
        ws.is_alive = True
        ws.ping_enabled = False
        # Start connection heartbeat monitor (no outgoing messages)
        def heartbeat():
            while ws.is_alive:
                time.sleep(5)
                if time.time() - ws.last_message_time > 129:
                    print(f"[{get_timestamp()}] No messages received for 129 seconds, connection may be stale")
                if not ws.is_alive:
                    break
        threading.Thread(target=heartbeat, daemon=True).start()
        # Start PING after HTTP_REQUEST
        def ping_loop():
            while ws.is_alive and ws.ping_enabled:
                try:
                    ping_message = {
                        "id": str(uuid.uuid4()),
                        "version": "1.0.0",
                        "action": "PING",
                        "data": {}
                    }
                    ws.send(json.dumps(ping_message))
                    ws.last_ping_time = time.time()
                    print(f"[{get_timestamp()}] Sent PING: {json.dumps(ping_message)}")
                    time.sleep(120)  # 2 minutes
                except Exception as e:
                    print(f"[{get_timestamp()}] PING failed: {e}")
                    ws.ping_enabled = False
                    break
        ws.ping_thread = threading.Thread(target=ping_loop, daemon=True)

    def on_message(ws, message):
        ws.last_message_time = time.time()
        print(f"[{get_timestamp()}] Raw message: {repr(message)}")
        try:
            message_data = json.loads(message)
            if message_data.get("action") == "HTTP_REQUEST":
                http_request = message_data.get("data", {})
                url = http_request.get("url")
                method = http_request.get("method")
                headers = http_request.get("headers", {})
                body = http_request.get("body")

                print(f"[{get_timestamp()}] Processing HTTP {method} request to: {url}")
                if method == "GET":
                    try:
                        start_time = time.time()
                        print(f"[{get_timestamp()}] Starting GET request")
                        response = requests.get(url, headers=headers, data=body, timeout=10)
                        end_time = time.time()
                        print(f"[{get_timestamp()}] HTTP request status: {response.status_code}")
                        print(f"[{get_timestamp()}] HTTP response: {response.text}")
                        print(f"[{get_timestamp()}] GET request completed in {end_time - start_time:.3f} seconds")
                        # Send HTTP_RESPONSE matching background.js
                        response_headers = {
                            k: v for k, v in response.headers.items()
                            if k.lower() != "content-encoding"
                        }
                        response_data = {
                            "id": message_data.get("id"),
                            "origin_action": "HTTP_REQUEST",
                            "result": {
                                "url": response.url,
                                "status": response.status_code,
                                "status_text": response.reason,
                                "headers": response_headers,
                                "body": array_buffer_to_base64(response.text)
                            }
                        }
                        ws.send(json.dumps(response_data))
                        print(f"[{get_timestamp()}] Sent HTTP_RESPONSE: {json.dumps(response_data)}")
                        # Start PING after first HTTP_REQUEST
                        if not ws.ping_enabled:
                            ws.ping_enabled = True
                            ws.ping_thread.start()
                    except requests.RequestException as e:
                        print(f"[{get_timestamp()}] HTTP request failed: {e}")
                        response_data = {
                            "id": message_data.get("id"),
                            "origin_action": "HTTP_REQUEST",
                            "result": {
                                "url": url,
                                "status": 400,
                                "status_text": "Bad Request",
                                "headers": {},
                                "body": array_buffer_to_base64(str(e))
                            }
                        }
                        ws.send(json.dumps(response_data))
                        print(f"[{get_timestamp()}] Sent HTTP_RESPONSE: {json.dumps(response_data)}")
                else:
                    print(f"[{get_timestamp()}] Unsupported HTTP method: {method}")
            elif message_data.get("action") == "PONG":
                print(f"[{get_timestamp()}] Received PONG")
            else:
                print(f"[{get_timestamp()}] Unknown action: {message_data.get('action')}")
        except json.JSONDecodeError:
            print(f"[{get_timestamp()}] Failed to parse WebSocket message as JSON")
        except Exception as e:
            print(f"[{get_timestamp()}] Unexpected error processing message: {e}")

    def on_error(ws, error):
        print(f"[{get_timestamp()}] WebSocket error: {error}")
        ws.is_alive = False

    def on_close(ws, close_status_code, close_msg):
        print(f"[{get_timestamp()}] WebSocket closed with code: {close_status_code}, message: {close_msg}")
        ws.is_alive = False
        if hasattr(ws, "last_message_time"):
            time_since_last_message = time.time() - ws.last_message_time
            print(f"[{get_timestamp()}] Time since last message: {time_since_last_message:.3f} seconds")
        if hasattr(ws, "last_ping_time") and ws.last_ping_time and (time.time() - ws.last_ping_time < 2):
            print(f"[{get_timestamp()}] Closure likely caused by PING, disabling PING")
            ws.ping_enabled = False
        retries = getattr(ws, "retries", 0) + 1
        ws.retries = retries
        if retries > max_destinations:
            print(f"[{get_timestamp()}] All destinations failed, re-running checkin")
            connect_websocket_with_checkin()
            return
        last_destination_index = getattr(ws, "last_destination_index", 0)
        next_destination_index = (last_destination_index + 1) % len(destinations)
        ws.last_destination_index = next_destination_index
        print(f"[{get_timestamp()}] Attempting to reconnect to destination {next_destination_index + 1}/{len(destinations)}")
        time.sleep(0.5)  # 500ms delay
        ws.url = f"{destinations[next_destination_index]}?token={token}"
        ws.run_forever()

    # Create WebSocket connection
    ws = websocket.WebSocketApp(
        f"{destinations[last_destination_index]}?token={token}",
        header=ws_headers,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws.is_alive = False
    ws.last_message_time = 0
    ws.retries = retries
    ws.last_destination_index = last_destination_index
    return ws

# Function to perform checkin and connect
def connect_websocket_with_checkin():
    max_retries = 10
    retry_delay = 5
    for attempt in range(max_retries):
        print(f"[{get_timestamp()}] Attempting POST request (attempt {attempt + 1}/{max_retries})")
        response = requests.post(url, json=payload, headers=headers)
        if response.status_code != 201:
            print(f"[{get_timestamp()}] POST request failed with status code: {response.status_code}")
            print(f"[{get_timestamp()}] Response text: {response.text}")
            if attempt < max_retries - 1:
                print(f"[{get_timestamp()}] Retrying POST in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print(f"[{get_timestamp()}] Max POST retries reached. Exiting.")
            continue

        print(f"[{get_timestamp()}] POST request successful!")
        response_data = response.json()
        destinations = response_data["destinations"]
        token = response_data["token"]
        destinations = [f"ws://{dest}" for dest in destinations]

        print(f"[{get_timestamp()}] Connecting to WebSocket with destinations: {destinations}")
        ws_headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "en-US,en;q=0.9",
            "Origin": "chrome-extension://ilehaonighjijnmpnagapkhpcdbhclfg"
        }

        try:
            ws = connect_websocket(destinations, token, ws_headers)
            ws.run_forever()
            break
        except Exception as e:
            print(f"[{get_timestamp()}] WebSocket connection failed: {e}")
            if attempt < max_retries - 1:
                print(f"[{get_timestamp()}] Retrying in {retry_delay} seconds...")
                time.sleep(retry_delay)
            else:
                print(f"[{get_timestamp()}] Max retries reached. Exiting.")

# Start the connection
connect_websocket_with_checkin()
