"""
Telegram Bot for Self-Healing Dashboard.
"""
import os
import sys
import asyncio
import httpx

# Force output to stdout
print("BOT STARTING", flush=True)
print(f"TOKEN: {os.environ.get('TELEGRAM_BOT_TOKEN', 'NOT SET')}", flush=True)

import config
import database

TARGET_URL = os.getenv("TARGET_SERVICE_URL", "")
TELEGRAM_TOKEN = config.notif_config.telegram_bot_token

print(f"CHAT_IDS: {config.notif_config.telegram_chat_ids}", flush=True)

database.init_database()

ALLOWED_CHAT_IDS = config.notif_config.telegram_chat_ids
if not isinstance(ALLOWED_CHAT_IDS, list):
    ALLOWED_CHAT_IDS = [5113409595]


async def send_message(chat_id: int, text: str):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json={"chat_id": chat_id, "text": text})
            print(f"SENT to {chat_id}: {resp.status_code}", flush=True)
    except Exception as e:
        print(f"SEND ERR: {e}", flush=True)


async def handle_command(chat_id: int, cmd: str):
    print(f"CMD: {cmd} from {chat_id}", flush=True)
    
    if cmd == "/start":
        await send_message(chat_id, "Bot running! /status /kill /startsrv")
    elif cmd == "/status":
        await send_message(chat_id, f"Target: {'UP' if TARGET_URL else 'NO TARGET'}")
    elif cmd == "/kill" and TARGET_URL:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{TARGET_URL}/kill")
                await send_message(chat_id, "KILLED")
        except Exception as e:
            await send_message(chat_id, f"ERR: {e}")
    elif cmd == "/startsrv" and TARGET_URL:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                await client.post(f"{TARGET_URL}/restart")
                await send_message(chat_id, "STARTED")
        except Exception as e:
            await send_message(chat_id, f"ERR: {e}")
    else:
        await send_message(chat_id, f"Unknown: {cmd}")


async def main():
    print("Polling started", flush=True)
    offset = None
    
    while True:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                params = {"timeout": 30}
                if offset:
                    params["offset"] = offset
                
                resp = await client.get(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                    params=params
                )
                
                data = resp.json()
                results = data.get("result", [])
                print(f"Updates: {len(results)}", flush=True)
                
                for update in results:
                    offset = update["update_id"] + 1
                    
                    if "message" in update:
                        chat_id = update["message"]["chat"]["id"]
                        text = update["message"].get("text", "")
                        
                        print(f"MSG: {chat_id} - {text}", flush=True)
                        
                        if text.startswith("/") and chat_id in ALLOWED_CHAT_IDS:
                            await handle_command(chat_id, text.split()[0])
                            
        except Exception as e:
            print(f"ERR: {e}", flush=True)
        
        await asyncio.sleep(2)


if __name__ == "__main__":
    print("EXEC", flush=True)
    asyncio.run(main())