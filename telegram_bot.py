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
        await send_message(chat_id, "Bot running. Commands: /status /kill /logs")

    elif command == "/status":
        status = database.get_service_status("mock_api")
        if status:
            is_up = "UP" if status["is_up"] else "DOWN"
            await send_message(chat_id, f"mock_api: {is_up}")
        else:
            await send_message(chat_id, "No data")

    elif command == "/kill":
        await send_message(chat_id, "Killing service...")
        pid = None
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr and conn.laddr.port == 9000 and conn.status == 'LISTEN':
                pid = conn.pid
                break
        if pid:
            os.kill(pid, signal.SIGTERM)
            await send_message(chat_id, f"Killed PID {pid}")
        else:
            await send_message(chat_id, "Not running")

    elif command == "/logs":
        logs = database.get_recent_logs(limit=3)
        text = "\n".join([f"{l['event_type']}: {l['message'][:30]}" for l in logs])
        await send_message(chat_id, text or "No logs")


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