"""
Notification drivers module for Self-Healing Dashboard.
Implements multiple notification channels: Log, Telegram, Discord/Webhook.
"""
import asyncio
import json
import logging
import sys
from datetime import datetime
from typing import List, Optional, Dict, Any

import httpx

import config
import database

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


class EventType:
    SERVICE_DOWN = "SERVICE_DOWN"
    SERVICE_UP = "SERVICE_UP"
    RECOVERY_STARTED = "RECOVERY_STARTED"
    RECOVERY_SUCCESS = "RECOVERY_SUCCESS"
    RECOVERY_FAILED = "RECOVERY_FAILED"
    FLAPPING_DETECTED = "FLAPPING_DETECTED"
    MAX_RETRIES_EXCEEDED = "MAX_RETRIES_EXCEEDED"


class NotificationDriver:
    async def send(self, event_type: str, service_name: str, message: str, details: Optional[str] = None):
        raise NotImplementedError


class LogNotifier(NotificationDriver):
    def __init__(self):
        self.log_level = config.notif_config.log_level

    async def send(self, event_type: str, service_name: str, message: str, details: Optional[str] = None):
        log_entry = f"[{event_type}] {service_name}: {message}"
        if details:
            log_entry += f" | {details}"

        if event_type in [EventType.SERVICE_DOWN, EventType.MAX_RETRIES_EXCEEDED, EventType.FLAPPING_DETECTED]:
            logger.error(log_entry)
        elif event_type in [EventType.SERVICE_UP, EventType.RECOVERY_SUCCESS]:
            logger.info(log_entry)
        else:
            logger.warning(log_entry)

        database.add_log(service_name, event_type, message, details)


class TelegramNotifier(NotificationDriver):
    def __init__(self):
        self.enabled = config.notif_config.telegram_enabled
        self.bot_token = config.notif_config.telegram_bot_token

        chat_ids_raw = config.notif_config.telegram_chat_ids
        if hasattr(chat_ids_raw, 'default_factory'):
            self.chat_ids = chat_ids_raw.default_factory()
        else:
            self.chat_ids = chat_ids_raw or []

    def _format_message(self, event_type: str, service_name: str, message: str) -> str:
        emoji_map = {
            EventType.SERVICE_DOWN: "DOWN",
            EventType.SERVICE_UP: "UP",
            EventType.RECOVERY_STARTED: "RECOVERY",
            EventType.RECOVERY_SUCCESS: "RECOVERED",
            EventType.RECOVERY_FAILED: "FAILED",
            EventType.FLAPPING_DETECTED: "FLAPPING",
            EventType.MAX_RETRIES_EXCEEDED: "MAX RETRIES",
        }
        emoji = emoji_map.get(event_type, "")
        return f"{emoji} {service_name}: {message}"

    async def send(self, event_type: str, service_name: str, message: str, details: Optional[str] = None):
        if not self.enabled or not self.bot_token or not self.chat_ids:
            logger.debug("Telegram notifier disabled or not configured")
            return

        formatted_msg = self._format_message(event_type, service_name, message)

        async with httpx.AsyncClient(timeout=10.0) as client:
            for chat_id in self.chat_ids:
                try:
                    url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
                    payload = {"chat_id": int(chat_id), "text": formatted_msg}
                    response = await client.post(url, json=payload)
                    if response.status_code == 200:
                        logger.info(f"Telegram notification sent to {chat_id}")
                    else:
                        logger.error(f"Telegram API error: {response.status_code} - {response.text}")
                except Exception as e:
                    logger.error(f"Failed to send Telegram notification: {e}")


class DiscordNotifier(NotificationDriver):
    def __init__(self):
        self.enabled = config.notif_config.discord_enabled
        self.webhook_url = config.notif_config.discord_webhook_url

    async def send(self, event_type: str, service_name: str, message: str, details: Optional[str] = None):
        if not self.enabled or not self.webhook_url:
            logger.debug("Discord notifier disabled")
            return

        color_map = {
            EventType.SERVICE_DOWN: 0xFF0000,
            EventType.SERVICE_UP: 0x00FF00,
            EventType.RECOVERY_STARTED: 0xFFA500,
            EventType.RECOVERY_SUCCESS: 0x00FF00,
            EventType.RECOVERY_FAILED: 0xFF0000,
            EventType.FLAPPING_DETECTED: 0xFFA500,
            EventType.MAX_RETRIES_EXCEEDED: 0xFF0000,
        }

        embed = {
            "title": f"{event_type}: {service_name}",
            "description": message,
            "color": color_map.get(event_type, 0x808080),
            "timestamp": datetime.now().isoformat(),
        }

        if details:
            embed["fields"] = [{"name": "Details", "value": details}]

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                await client.post(self.webhook_url, json={"embeds": [embed]})
            except Exception as e:
                logger.error(f"Failed to send Discord notification: {e}")


class NotificationManager:
    def __init__(self):
        self.drivers: List[NotificationDriver] = []

        if config.notif_config.log_enabled:
            self.drivers.append(LogNotifier())

        if config.notif_config.telegram_enabled:
            self.drivers.append(TelegramNotifier())

        if config.notif_config.discord_enabled:
            self.drivers.append(DiscordNotifier())

        logger.info(f"Notification manager initialized with {len(self.drivers)} driver(s)")

    async def notify(self, event_type: str, service_name: str, message: str, details: Optional[str] = None):
        tasks = []
        for driver in self.drivers:
            tasks.append(driver.send(event_type, service_name, message, details))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


notification_manager = NotificationManager()


_last_notified_state = {}


async def notify_service_down(service_name: str, details: Optional[str] = None):
    status = _last_notified_state.get(service_name)
    if status != "down":
        _last_notified_state[service_name] = "down"
        await notification_manager.notify(EventType.SERVICE_DOWN, service_name, f"Service '{service_name}' is DOWN", details)


async def notify_service_up(service_name: str, details: Optional[str] = None):
    status = _last_notified_state.get(service_name)
    if status != "up":
        _last_notified_state[service_name] = "up"
        await notification_manager.notify(EventType.SERVICE_UP, service_name, f"Service '{service_name}' is UP", details)


async def notify_recovery_started(service_name: str, attempt: int, details: Optional[str] = None):
    await notification_manager.notify(EventType.RECOVERY_STARTED, service_name, f"Recovery attempt #{attempt}", details)


async def notify_recovery_success(service_name: str, details: Optional[str] = None):
    await notification_manager.notify(EventType.RECOVERY_SUCCESS, service_name, f"Service '{service_name}' recovered", details)


async def notify_recovery_failed(service_name: str, attempt: int, error: str):
    await notification_manager.notify(EventType.RECOVERY_FAILED, service_name, f"Recovery attempt #{attempt} failed", error)


async def notify_flapping_detected(service_name: str, attempts: int):
    await notification_manager.notify(EventType.FLAPPING_DETECTED, service_name, f"Service '{service_name}' is flapping - {attempts} failures")


async def notify_max_retries_exceeded(service_name: str, total_attempts: int):
    await notification_manager.notify(EventType.MAX_RETRIES_EXCEEDED, service_name, f"MAX RETRIES exceeded for '{service_name}'", f"Attempts: {total_attempts}")