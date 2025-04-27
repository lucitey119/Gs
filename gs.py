import requests
import json
import websocket
import time
import threading
import uuid
import base64
import random
from datetime import datetime
from urllib.parse import urlparse

# ——— Proxy Setup ———

def load_proxies(file_path="proxy.txt"):
    try:
        with open(file_path) as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        print(f"[WARNING] {file_path} not found. Proceeding without proxies.")
        return []

use_proxy = input("Do you want to use a proxy? (y/n): ").strip().lower().startswith("y")

PROXIES = {}
PROXY_HOST = None
PROXY_PORT = None
PROXY_USER = None
PROXY_PASS = None

if use_proxy:
    proxy_list = load_proxies()
    if proxy_list:
        selected = random.choice(proxy_list)
        parsed = urlparse(selected)
        if not (parsed.scheme in ("http", "socks4", "socks5") and parsed.hostname and parsed.port):
            print(f"[WARNING] Invalid proxy URL '{selected}', disabling proxy.")
            use_proxy = False
        else:
            PROXY_HOST = parsed.hostname
            PROXY_PORT = parsed.port
            PROXY_USER = parsed.username
            PROXY_PASS = parsed.password
            PROXIES = {"http": selected, "https": selected}
            print(f"[INFO] Using proxy: {selected}")
    else:
        print("[WARNING] No proxies found. Disabling proxy usage.")
        use_proxy = False

# ——— Core Configuration ———

url = "https://director.getgrass.io/checkin"
payload = {
    "browserId": "53089d54-d47b-5e39-abb1-f8fadd90c3e5",
    "deviceType": "extension",
    "extensionId": "ilehaonighjijnmpnagapkhpcdbhclfg",
    "userAgent": "Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Mobile Safari/537.36",
    "userId": "2gh63HX35H0KAPIZPKiVsbUFQn2",
    "version": "5.3.1"
}
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
    "User-Agent": payload["userAgent"]
}

def get_timestamp():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")

def array_buffer_to_base64(data):
    return base64.b64encode(data.encode()).decode()

# ——— WebSocket Logic ———

def connect_websocket(destinations, token, ws_headers):
    last_idx = 0

    def on_open(ws):
        print(f"[{get_timestamp()}] WebSocket opened")
        ws.last_message_time = time.time()
        ws.is_alive = True
        def heartbeat():
            while ws.is_alive:
                time.sleep(5)
                if time.time() - ws.last_message_time > 129:
                    print(f"[{get_timestamp()}] No messages for 129s; connection stale")
        threading.Thread(target=heartbeat, daemon=True).start()

    def on_message(ws, message):
        ws.last_message_time = time.time()
        try:
            msg = json.loads(message)
            action = msg.get("action")

            if action == "HTTP_REQUEST":
                req = msg["data"]
                r_url, method = req.get("url"), req.get("method")
                hdrs, body = req.get("headers", {}), req.get("body")
                print(f"[{get_timestamp()}] HTTP {method} → {r_url}")
                if method == "GET":
                    try:
                        start = time.time()
                        resp = requests.get(
                            r_url,
                            headers=hdrs,
                            data=body,
                            timeout=10,
                            proxies=PROXIES if use_proxy else None
                        )
                        dur = time.time() - start
                        print(f"[{get_timestamp()}] {resp.status_code} in {dur:.3f}s")
                        rh = {k: v for k, v in resp.headers.items() if k.lower() != "content-encoding"}
                        out = {
                            "id": msg.get("id"),
                            "origin_action": "HTTP_REQUEST",
                            "result": {
                                "url": resp.url,
                                "status": resp.status_code,
                                "status_text": resp.reason,
                                "headers": rh,
                                "body": array_buffer_to_base64(resp.text)
                            }
                        }
                        ws.send(json.dumps(out))
                    except Exception as e:
                        print(f"[{get_timestamp()}] GET failed: {e}")
                        err = {
                            "id": msg.get("id"),
                            "origin_action": "HTTP_REQUEST",
                            "result": {
                                "url": r_url,
                                "status": 400,
                                "status_text": "Bad Request",
                                "headers": {},
                                "body": array_buffer_to_base64(str(e))
                            }
                        }
                        ws.send(json.dumps(err))

            elif action == "PONG":
                print(f"[{get_timestamp()}] PONG received")
                ping = {"id": str(uuid.uuid4()), "version":"1.0.0", "action":"PING", "data":{}}
                ws.send(json.dumps(ping))
                ws.last_ping_time = time.time()
                def delayed():
                    time.sleep(10)
                    while ws.is_alive:
                        try:
                            p = {"id": str(uuid.uuid4()), "version":"1.0.0", "action":"PING", "data":{}}
                            ws.send(json.dumps(p))
                            ws.last_ping_time = time.time()
                            time.sleep(10)
                        except:
                            break
                threading.Thread(target=delayed, daemon=True).start()

            else:
                print(f"[{get_timestamp()}] Unhandled action: {action}")

        except Exception as e:
            print(f"[{get_timestamp()}] Error in on_message: {e}")

    def on_error(ws, error):
        print(f"[{get_timestamp()}] WebSocket error: {error}")
        ws.is_alive = False

    def on_close(ws, code, msg):
        print(f"[{get_timestamp()}] Closed: {code}, {msg}")
        ws.is_alive = False
        # rotate to next destination
        next_idx = (getattr(ws, "last_idx", 0) + 1) % len(destinations)
        ws.last_idx = next_idx
        time.sleep(0.5)
        ws.url = f"{destinations[next_idx]}?token={token}"
        # reconnect with or without proxy
        if use_proxy:
            ws.run_forever(
                http_proxy_host=PROXY_HOST,
                http_proxy_port=PROXY_PORT,
                proxy_type="http",
                http_proxy_auth=(PROXY_USER, PROXY_PASS)
            )
        else:
            ws.run_forever()

    ws = websocket.WebSocketApp(
        f"{destinations[last_idx]}?token={token}",
        header=ws_headers,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close
    )
    ws.retries = 0
    ws.last_idx = last_idx
    return ws

# ——— Check-In & Start ———

def connect_websocket_with_checkin():
    for attempt in range(10):
        print(f"[{get_timestamp()}] Check-in POST {attempt+1}/10")
        resp = requests.post(
            url,
            json=payload,
            headers=headers,
            proxies=PROXIES if use_proxy else None
        )
        if resp.status_code != 201:
            print(f"[WARNING] {resp.status_code}, retrying in 5s…")
            time.sleep(5)
            continue

        data = resp.json()
        dests = [f"ws://{d}" for d in data["destinations"]]
        token = data["token"]
        ws_hdrs = {
            "User-Agent": headers["User-Agent"],
            "Accept-Encoding": headers["Accept-Encoding"],
            "Accept-Language": headers["Accept-Language"],
            "Origin": headers["Origin"]
        }
        ws = connect_websocket(dests, token, ws_hdrs)
        if use_proxy:
            ws.run_forever(
                http_proxy_host=PROXY_HOST,
                http_proxy_port=PROXY_PORT,
                proxy_type="http",
                http_proxy_auth=(PROXY_USER, PROXY_PASS)
            )
        else:
            ws.run_forever()
        break

if __name__ == "__main__":
    connect_websocket_with_checkin()
