"""
Telegram Bot for Self-Healing Dashboard.
"""
import os
import asyncio
import httpx
import logging

logging.basicConfig(level=logging.DEBUG)

import config
import database

SERVICE_URL = os.getenv("SERVICE_URL", os.getenv("RAILWAY_PUBLIC_DOMAIN", "http://localhost:8000"))
TARGET_URL = os.getenv("TARGET_SERVICE_URL", "")

TELEGRAM_TOKEN = config.notif_config.telegram_bot_token
print(f"TOKEN: {TELEGRAM_TOKEN}")

chat_ids_raw = config.notif_config.telegram_chat_ids
if hasattr(chat_ids_raw, 'default_factory'):
    ALLOWED_CHAT_IDS = chat_ids_raw.default_factory()
elif isinstance(chat_ids_raw, list):
    ALLOWED_CHAT_IDS = chat_ids_raw
else:
    ALLOWED_CHAT_IDS = []

print(f"CHAT_IDS: {ALLOWED_CHAT_IDS}")

database.init_database()


async def send_message(chat_id: int, text: str):
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(url, json=payload)
            print(f"SEND to {chat_id}: {resp.status_code}")
    except Exception as e:
        print(f"SEND ERROR: {e}")


async def handle_command(chat_id: int, cmd: str):
    print(f"HANDLE: {cmd} from {chat_id}")
    
    if cmd == "/start":
        await send_message(chat_id, "Bot is running!\n\nCommands:\n/kill - Kill target\n/start - Start target\n/status - Check status")

    elif cmd == "/status":
        if not TARGET_URL:
            await send_message(chat_id, "TARGET_SERVICE_URL not configured")
            return
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{TARGET_URL}/health")
                if r.status_code == 200:
                    await send_message(chat_id, "Target: UP")
                else:
                    await send_message(chat_id, "Target: DOWN")
        except Exception as e:
            await send_message(chat_id, f"Target: DOWN ({e})")

    elif cmd == "/kill":
        if not TARGET_URL:
            await send_message(chat_id, "TARGET_SERVICE_URL not configured")
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{TARGET_URL}/kill")
                await send_message(chat_id, "Target KILLED")
        except Exception as e:
            await send_message(chat_id, f"Error: {e}")

    elif cmd == "/startsrv":
        if not TARGET_URL:
            await send_message(chat_id, "TARGET_SERVICE_URL not configured")
            return
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{TARGET_URL}/restart")
                await send_message(chat_id, "Target RESTARTED")
        except Exception as e:
            await send_message(chat_id, f"Error: {e}")

    else:
        await send_message(chat_id, f"Unknown: {cmd}")


async def main():
    print("Starting bot polling...")
    offset = None
    
    while True:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                params = {"timeout": 30}
                if offset is not None:
                    params["offset"] = offset
                
                resp = await client.get(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                    params=params
                )
                
                data = resp.json()
                print(f"Got updates: {len(data.get('result', []))}")
                
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    
                    if "message" in update:
                        msg = update["message"]
                        chat_id = msg["chat"]["id"]
                        text = msg.get("text", "")
                        
                        print(f"MSG: chat={chat_id} text={text}")
                        
                        if text.startswith("/"):
                            cmd = text.split()[0]
                            if chat_id in ALLOWED_CHAT_IDS:
                                await handle_command(chat_id, cmd)
                            else:
                                print(f"Chat {chat_id} not in allowed: {ALLOWED_CHAT_IDS}")
                                
        except Exception as e:
            print(f"Error: {e}")
        
        await asyncio.sleep(2)


if __name__ == "__main__":
    print("Bot starting...")
    asyncio.run(main())