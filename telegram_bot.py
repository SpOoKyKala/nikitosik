"""
Telegram Bot for Self-Healing Dashboard.
"""
import os
import asyncio
import httpx

import config
import database

SERVICE_URL = os.getenv("SERVICE_URL", os.getenv("RAILWAY_PUBLIC_DOMAIN", "http://localhost:8000"))
TARGET_URL = os.getenv("TARGET_SERVICE_URL", "http://localhost:9000")

TELEGRAM_TOKEN = config.notif_config.telegram_bot_token
chat_ids_raw = config.notif_config.telegram_chat_ids
if hasattr(chat_ids_raw, 'default_factory'):
    ALLOWED_CHAT_IDS = chat_ids_raw.default_factory()
else:
    ALLOWED_CHAT_IDS = chat_ids_raw or []

database.init_database()


async def send_message(chat_id: int, text: str):
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text}
            )
            print(f"Sent to {chat_id}: {text[:30]} - {resp.status_code}")
    except Exception as e:
        print(f"Send error: {e}")


async def handle_command(chat_id: int, command: str):
    if command == "/start":
        await send_message(chat_id, "Bot running\n/kill - Kill target\n/start - Start target\n/status - Check status")

    elif command == "/status":
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.get(f"{TARGET_URL}/health")
                if r.status_code == 200:
                    await send_message(chat_id, "Target: UP")
                else:
                    await send_message(chat_id, "Target: DOWN")
        except:
            await send_message(chat_id, "Target: DOWN")

    elif command == "/kill":
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{TARGET_URL}/kill")
                if r.status_code == 200:
                    await send_message(chat_id, "Target KILLED")
                else:
                    await send_message(chat_id, "Failed")
        except Exception as e:
            await send_message(chat_id, f"Error: {e}")

    elif command == "/startsrv":
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.post(f"{TARGET_URL}/restart")
                if r.status_code == 200:
                    await send_message(chat_id, "Target STARTED")
                else:
                    await send_message(chat_id, "Failed")
        except Exception as e:
            await send_message(chat_id, f"Error: {e}")


async def main():
    offset = None  # Start from latest
    while True:
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates",
                    params={"timeout": 30, "offset": offset}
                )
                data = resp.json()
                if data.get("ok"):
                    for update in data.get("result", []):
                        offset = update["update_id"] + 1
                        if "message" in update:
                            chat_id = update["message"]["chat"]["id"]
                            text = update["message"].get("text", "")
                            print(f"Message from {chat_id}: {text}")
                            if chat_id in ALLOWED_CHAT_IDS:
                                if text.startswith("/"):
                                    await handle_command(chat_id, text.split()[0])
        except Exception as e:
            print(f"Polling error: {e}")
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())