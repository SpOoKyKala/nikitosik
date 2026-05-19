"""
Telegram Bot for Self-Healing Dashboard.
"""
import os
import signal
import psutil
import asyncio
import httpx

import config
import database

# Get the service URL
SERVICE_URL = os.getenv("SERVICE_URL", "http://localhost:8000")
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
            await client.post(
                f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text}
            )
    except:
        pass


async def handle_command(chat_id: int, command: str):
    if command == "/start":
        await send_message(chat_id, "Bot running. Commands:\n/kill - Kill service\n/start - Start service\n/status - Show status")

    elif command == "/status":
        async with httpx.AsyncClient(timeout=5) as client:
            try:
                r = await client.get(f"{SERVICE_URL}/internal/health")
                if r.status_code == 200:
                    await send_message(chat_id, "Service: UP")
                else:
                    await send_message(chat_id, "Service: DOWN")
            except:
                await send_message(chat_id, "Service: DOWN")

    elif command == "/kill":
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                r = await client.post(f"{SERVICE_URL}/internal/kill")
                if r.status_code == 200:
                    await send_message(chat_id, "Service KILLED")
                else:
                    await send_message(chat_id, "Failed")
            except Exception as e:
                await send_message(chat_id, f"Error: {e}")

    elif command == "/startsrv":
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                r = await client.post(f"{SERVICE_URL}/internal/start")
                if r.status_code == 200:
                    await send_message(chat_id, "Service STARTED")
                else:
                    await send_message(chat_id, "Failed")
            except Exception as e:
                await send_message(chat_id, f"Error: {e}")


async def main():
    offset = 0
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
                            if chat_id in ALLOWED_CHAT_IDS:
                                text = update["message"].get("text", "")
                                if text.startswith("/"):
                                    await handle_command(chat_id, text.split()[0])
        except:
            pass
        await asyncio.sleep(1)


if __name__ == "__main__":
    asyncio.run(main())