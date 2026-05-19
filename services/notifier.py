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


# ==============================================================================
# Event Types
# ==============================================================================

class EventType:
    """Standard event type constants."""
    SERVICE_DOWN = "SERVICE_DOWN"
    SERVICE_UP = "SERVICE_UP"
    RECOVERY_STARTED = "RECOVERY_STARTED"
    RECOVERY_SUCCESS = "RECOVERY_SUCCESS"
    RECOVERY_FAILED = "RECOVERY_FAILED"
    FLAPPING_DETECTED = "FLAPPING_DETECTED"
    MAX_RETRIES_EXCEEDED = "MAX_RETRIES_EXCEEDED"


# ==============================================================================
# Notification Interface
# ==============================================================================

class NotificationDriver:
    """Base class for notification drivers."""

    async def send(self, event_type: str, service_name: str, message: str, details: Optional[str] = None):
        """Send notification. Override in subclasses."""
        raise NotImplementedError


# ==============================================================================
# Console/Log Notification Driver
# ==============================================================================

class LogNotifier(NotificationDriver):
    """Log-based notification driver (console + database)."""

    def __init__(self):
        self.log_level = config.notif_config.log_level

    async def send(self, event_type: str, service_name: str, message: str, details: Optional[str] = None):
        """Log to console and write to database."""
        log_entry = f"[{event_type}] {service_name}: {message}"
        if details:
            log_entry += f" | {details}"

        # Console output
        if event_type in [EventType.SERVICE_DOWN, EventType.MAX_RETRIES_EXCEEDED, EventType.FLAPPING_DETECTED]:
            logger.error(log_entry)
        elif event_type in [EventType.SERVICE_UP, EventType.RECOVERY_SUCCESS]:
            logger.info(log_entry)
        else:
            logger.warning(log_entry)

        # Database log
        database.add_log(service_name, event_type, message, details)


# ==============================================================================
# Telegram Notification Driver
# ==============================================================================

class TelegramNotifier(NotificationDriver):
    """Telegram Bot API notification driver."""

    def __init__(self):
        self.enabled = config.notif_config.telegram_enabled
        self.bot_token = config.notif_config.telegram_bot_token

        # Handle dataclass field properly
        chat_ids_raw = config.notif_config.telegram_chat_ids
        if hasattr(chat_ids_raw, 'default_factory'):
            self.chat_ids = chat_ids_raw.default_factory()
        else:
            self.chat_ids = chat_ids_raw or []

    def _format_message(self, event_type: str, service_name: str, message: str) -> str:
        """Format message for Telegram with emoji indicators."""
        emoji_map = {
            EventType.SERVICE_DOWN: "🔴",
            EventType.SERVICE_UP: "🟢",
            EventType.RECOVERY_STARTED: "⚡",
            EventType.RECOVERY_SUCCESS: "✅",
            EventType.RECOVERY_FAILED: "❌",
            EventType.FLAPPING_DETECTED: "⚠️",
            EventType.MAX_RETRIES_EXCEEDED: "🛑",
        }
        emoji = emoji_map.get(event_type, "📌")
        return f"{emoji} *{service_name}*\n{message}"

    async def send(self, event_type: str, service_name: str, message: str, details: Optional[str] = None):
        """Send message via Telegram Bot API."""
        if not self.enabled or not self.bot_token or not self.chat_ids:
            logger.debug("Telegram notifier disabled or not configured")
            return

        formatted_msg = self._format_message(event_type, service_name, message)
        if details:
            formatted_msg += f"\n_{details}_"

        # Send to all configured chat IDs
        async with httpx.AsyncClient(timeout=10.0) as client:
            for chat_id in self.chat_ids:
                try:
                    url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
                    payload = {
                        "chat_id": int(chat_id),
                        "text": formatted_msg
                    }
                    response = await client.post(url, json=payload)
                    if response.status_code == 200:
                        logger.info(f"Telegram notification sent to {chat_id}")
                    else:
                        logger.error(f"Telegram API error: {response.status_code} - {response.text}")
                except Exception as e:
                    logger.error(f"Failed to send Telegram notification: {e}")


# ==============================================================================
# Discord/Webhook Notification Driver
# ==============================================================================

class DiscordNotifier(NotificationDriver):
    """Discord Webhook notification driver (stub implementation)."""

    def __init__(self):
        self.enabled = config.notif_config.discord_enabled
        self.webhook_url = config.notif_config.discord_webhook_url

    def _format_embed(self, event_type: str, service_name: str, message: str, details: Optional[str] = None) -> Dict[str, Any]:
        """Format Discord embed message."""
        color_map = {
            EventType.SERVICE_DOWN: 0xFF0000,      # Red
            EventType.SERVICE_UP: 0x00FF00,       # Green
            EventType.RECOVERY_STARTED: 0xFFA500, # Orange
            EventType.RECOVERY_SUCCESS: 0x00FF00,  # Green
            EventType.RECOVERY_FAILED: 0xFF0000,   # Red
            EventType.FLAPPING_DETECTED: 0xFFA500, # Orange
            EventType.MAX_RETRIES_EXCEEDED: 0xFF0000, # Red
        }
        color = color_map.get(event_type, 0x808080)

        embed = {
            "title": f"{event_type}: {service_name}",
            "description": message,
            "color": color,
            "timestamp": datetime.now().isoformat(),
            "fields": []
        }

        if details:
            embed["fields"].append({"name": "Details", "value": details, "inline": False})

        return embed

    async def send(self, event_type: str, service_name: str, message: str, details: Optional[str] = None):
        """Send message via Discord Webhook."""
        if not self.enabled or not self.webhook_url:
            logger.debug("Discord notifier disabled or not configured")
            return

        # Stub implementation - requires actual webhook URL to be configured
        embed = self._format_embed(event_type, service_name, message, details)

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                response = await client.post(
                    self.webhook_url,
                    json={"embeds": [embed]}
                )
                if response.status_code in [200, 204]:
                    logger.info("Discord notification sent")
                else:
                    logger.error(f"Discord Webhook error: {response.status_code}")
            except Exception as e:
                logger.error(f"Failed to send Discord notification: {e}")


# ==============================================================================
# Notification Manager
# ==============================================================================

class NotificationManager:
    """Manages all notification drivers and dispatches notifications."""

    def __init__(self):
        self.drivers: List[NotificationDriver] = []

        # Always add log notifier
        if config.notif_config.log_enabled:
            self.drivers.append(LogNotifier())

        # Add Telegram notifier if configured
        if config.notif_config.telegram_enabled:
            self.drivers.append(TelegramNotifier())

        # Add Discord notifier if configured
        if config.notif_config.discord_enabled:
            self.drivers.append(DiscordNotifier())

        logger.info(f"Notification manager initialized with {len(self.drivers)} driver(s)")

    async def notify(
        self,
        event_type: str,
        service_name: str,
        message: str,
        details: Optional[str] = None
    ):
        """Send notification to all enabled drivers (only on state change)."""
        # Only send notifications for state changes, not every check
        if event_type not in [EventType.SERVICE_DOWN, EventType.SERVICE_UP,
                              EventType.RECOVERY_STARTED, EventType.RECOVERY_SUCCESS,
                              EventType.FLAPPING_DETECTED, EventType.MAX_RETRIES_EXCEEDED]:
            return

        # Check if we already notified for this state
        key = f"{service_name}_{event_type}"
        last_state = _last_notified_state.get(service_name)

        # For SERVICE_DOWN - only notify if was UP before
        if event_type == EventType.SERVICE_DOWN and last_state == "up":
            _last_notified_state[service_name] = "down"
        # For SERVICE_UP - only notify if was DOWN before
        elif event_type == EventType.SERVICE_UP and last_state == "down":
            _last_notified_state[service_name] = "up"
        # For recovery events - always send
        elif event_type in [EventType.RECOVERY_STARTED, EventType.RECOVERY_SUCCESS,
                           EventType.FLAPPING_DETECTED, EventType.MAX_RETRIES_EXCEEDED]:
            pass  # Always send
        else:
            # Already notified for this state
            return

        # Send notifications
        tasks = []
        for driver in self.drivers:
            tasks.append(driver.send(event_type, service_name, message, details))

        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)


# Global notification manager instance
notification_manager = NotificationManager()

# Track last notified state to avoid duplicates
_last_notified_state = {}


# ==============================================================================
# Convenience Functions
# ==============================================================================

async def notify_service_down(service_name: str, details: Optional[str] = None):
    """Notify that a service is down."""
    await notification_manager.notify(
        EventType.SERVICE_DOWN,
        service_name,
        f"Service '{service_name}' is not responding",
        details
    )


async def notify_service_up(service_name: str, details: Optional[str] = None):
    """Notify that a service is up."""
    await notification_manager.notify(
        EventType.SERVICE_UP,
        service_name,
        f"Service '{service_name}' is healthy",
        details
    )


async def notify_recovery_started(service_name: str, attempt: int, details: Optional[str] = None):
    """Notify that recovery has started."""
    await notification_manager.notify(
        EventType.RECOVERY_STARTED,
        service_name,
        f"Starting recovery attempt #{attempt}",
        details
    )


async def notify_recovery_success(service_name: str, details: Optional[str] = None):
    """Notify that recovery was successful."""
    await notification_manager.notify(
        EventType.RECOVERY_SUCCESS,
        service_name,
        f"Service '{service_name}' recovered successfully",
        details
    )


async def notify_recovery_failed(service_name: str, attempt: int, error: str):
    """Notify that recovery attempt failed."""
    await notification_manager.notify(
        EventType.RECOVERY_FAILED,
        service_name,
        f"Recovery attempt #{attempt} failed",
        error
    )


async def notify_flapping_detected(service_name: str, attempts: int):
    """Notify that service is flapping (repeated failures)."""
    await notification_manager.notify(
        EventType.FLAPPING_DETECTED,
        service_name,
        f"Service '{service_name}' is flapping - {attempts} consecutive failures",
        f"Recovery paused to prevent infinite restart loop"
    )


async def notify_max_retries_exceeded(service_name: str, total_attempts: int):
    """Notify that maximum retry attempts have been exceeded."""
    await notification_manager.notify(
        EventType.MAX_RETRIES_EXCEEDED,
        service_name,
        f"MAX RETRIES EXCEEDED for '{service_name}'",
        f"Total recovery attempts: {total_attempts}. Manual intervention required."
    )