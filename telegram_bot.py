"""
Telegram Bot for Self-Healing Dashboard.
Provides commands to control and monitor services.
"""
import os
import signal
import psutil
import asyncio
import httpx
from datetime import datetime

import config
import database
from services import notifier

# Telegram Bot API
TELEGRAM_TOKEN = config.notif_config.telegram_bot_token

# Get chat IDs from config - handle both dataclass field and direct list
chat_ids_raw = config.notif_config.telegram_chat_ids
if hasattr(chat_ids_raw, 'default_factory'):
    ALLOWED_CHAT_IDS = chat_ids_raw.default_factory()
else:
    ALLOWED_CHAT_IDS = chat_ids_raw or []

print(f"   Chat IDs: {ALLOWED_CHAT_IDS}")

# Initialize database
database.init_database()


async def send_message(chat_id: int, text: str):
    """Send message via Telegram Bot API."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
            response = await client.post(url, json={
                "chat_id": chat_id,
                "text": text
            })
            if response.status_code != 200:
                print(f"Error sending: {response.text}")
    except Exception as e:
        print(f"Send error: {e}")


async def handle_command(chat_id: int, command: str, args: list):
    """Handle bot commands."""
    if command == "/start":
        await send_message(chat_id, "Self-Healing Dashboard Bot\n\n"
            "Commands:\n"
            "/status - Show service status\n"
            "/kill - Kill mock service\n"
            "/logs - Recent events")

    elif command == "/status":
        status = database.get_service_status("mock_api")
        if status:
            is_up = "✅ UP" if status["is_up"] else "🔴 DOWN"
            failures = status["consecutive_failures"]
            await send_message(chat_id, f"Service: *mock_api*\nStatus: {is_up}\nFailures: {failures}")
        else:
            await send_message(chat_id, "No status data")

    elif command == "/kill":
        await send_message(chat_id, "Killing service...")

        # Find and kill process
        pid = None
        for conn in psutil.net_connections(kind='inet'):
            if conn.laddr and conn.laddr.port == 9000 and conn.status == 'LISTEN':
                pid = conn.pid
                break

        if pid:
            try:
                os.kill(pid, signal.SIGTERM)
                await send_message(chat_id, f"Process {pid} killed")
            except:
                await send_message(chat_id, "Failed to kill")
        else:
            await send_message(chat_id, "Service not running")

    elif command == "/logs":
        logs = database.get_recent_logs(limit=5)
        text = "Recent Events:\n"
        for log in logs:
            text += f"- {log['event_type']}: {log['message'][:40]}\n"
        await send_message(chat_id, text)


async def poll_updates(offset: int = 0):
    """Poll for updates from Telegram."""
    async with httpx.AsyncClient(timeout=30) as client:
        while True:
            try:
                url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getUpdates"
                params = {"timeout": 30, "offset": offset} if offset else {"timeout": 30}
                response = await client.get(url, params=params)

                if response.status_code == 200:
                    data = response.json()
                    if data.get("ok"):
                        for update in data.get("result", []):
                            offset = update["update_id"] + 1

                            if "message" in update:
                                chat_id = update["message"]["chat"]["id"]
                                text = update["message"].get("text", "")

                                # Check if from allowed chat
                                if chat_id in ALLOWED_CHAT_IDS:
                                    if text.startswith("/"):
                                        parts = text.split()
                                        command = parts[0]
                                        args = parts[1:] if len(parts) > 1 else []
                                        await handle_command(chat_id, command, args)

            except Exception as e:
                print(f"Polling error: {e}")

            await asyncio.sleep(1)


async def notify_telegram(event_type: str, service_name: str, message: str):
    """Send notification to Telegram."""
    emoji_map = {
        "SERVICE_DOWN": "🔴",
        "SERVICE_UP": "🟢",
        "RECOVERY_STARTED": "⚡",
        "RECOVERY_SUCCESS": "✅",
        "RECOVERY_FAILED": "❌"
    }
    emoji = emoji_map.get(event_type, "📌")

    text = f"{emoji} *{service_name}*\n{message}"

    for chat_id in ALLOWED_CHAT_IDS:
        try:
            await send_message(chat_id, text)
        except Exception as e:
            print(f"Failed to send to {chat_id}: {e}")


async def main():
    """Run the bot."""
    print(f"🤖 Telegram bot started")
    print(f"   Token: {TELEGRAM_TOKEN[:20]}...")
    print(f"   Allowed chats: {ALLOWED_CHAT_IDS}")
    await poll_updates()


if __name__ == "__main__":
    asyncio.run(main())