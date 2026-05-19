"""
Configuration module for Self-Healing Dashboard.
Contains service definitions, monitoring parameters, and notification/recovery settings.
"""
import os
from typing import Dict, Any
from dataclasses import dataclass, field


# ==============================================================================
# Global Settings
# ==============================================================================

@dataclass
class Settings:
    """Application-wide settings."""

    # Database
    db_path: str = "monitor.db"

    # Monitoring interval in seconds
    check_interval: float = 1.0

    # Recovery timeout in seconds (how long to wait for service to restart)
    recovery_timeout: float = 10.0

    # Maximum consecutive restart attempts before giving up
    max_consecutive_failures: int = 3

    # Window in seconds for flapping detection (reset counter after this time)
    flapping_window: int = 300

    # Backend host and port
    host: str = "0.0.0.0"
    port: int = 8000


settings = Settings()


# ==============================================================================
# Service Configuration
# ==============================================================================

@dataclass
class ServiceConfig:
    """Configuration for a single monitored service."""

    name: str
    port: int
    host: str = "localhost"
    check_url: str = ""
    recovery_type: str = "script"
    recovery_command: str = ""
    enabled: bool = True


# List of services to monitor
# Each service can have its own recovery mechanism
# Detect if running on Railway
is_railway = os.getenv("RAILWAY_ENVIRONMENT") is not None

# Get service URL for monitoring - use self URL for Railway
service_url = os.getenv("SERVICE_URL", os.getenv("RAILWAY_PUBLIC_DOMAIN", "http://localhost:8000"))

SERVICES: Dict[str, ServiceConfig] = {
    "target_service": ServiceConfig(
        name="target_service",
        host="localhost",
        port=8000,
        check_url=f"{service_url}/internal/health",
        recovery_type="api",
        recovery_command=f"{service_url}/internal/start",
        enabled=True
    ),
}


# ==============================================================================
# Notification Drivers Configuration
# ==============================================================================

class NotificationConfig:
    """Configuration for notification channels."""

    # Console/Log notifications (always enabled)
    log_enabled: bool = True
    log_level: str = "INFO"

    # Telegram Bot configuration
    telegram_enabled: bool = True
    telegram_bot_token: str = "8266978080:AAEdL6GXg33a2ctQDLAEsZLiBqnAJV5hZlk"
    telegram_chat_ids: list = field(default_factory=lambda: [5113409595])

    # Discord Webhook configuration
    discord_enabled: bool = False
    discord_webhook_url: str = ""


notif_config = NotificationConfig()

# ===============================================
# QUICK SETUP - Replace these values:
# ===============================================
# TELEGRAM_BOT_TOKEN = "123456:ABC-DEF..."
# TELEGRAM_CHAT_ID = 123456789
# ===============================================


# ==============================================================================
# Recovery Drivers Configuration
# ==============================================================================

class RecoveryConfig:
    """Configuration for recovery mechanisms."""

    # Script-based recovery
    script_timeout: int = 30

    # Process-based recovery (for Windows/Linux process management)
    process_restart_delay: float = 2.0


recov_config = RecoveryConfig()


# ==============================================================================
# Environment Variable Overrides
# ==============================================================================

def load_env_overrides():
    """Load configuration overrides from environment variables."""
    # Telegram overrides
    if token := os.getenv("TELEGRAM_BOT_TOKEN"):
        notif_config.telegram_bot_token = token
        notif_config.telegram_enabled = True

    if chat_ids := os.getenv("TELEGRAM_CHAT_ID"):
        notif_config.telegram_chat_ids = [int(chat_ids)]
    elif chat_ids := os.getenv("TELEGRAM_CHAT_IDS"):
        notif_config.telegram_chat_ids = [int(x.strip()) for x in chat_ids.split(",")]

    # Discord overrides
    if webhook := os.getenv("DISCORD_WEBHOOK_URL"):
        notif_config.discord_webhook_url = webhook
        notif_config.discord_enabled = True

    # Database path override
    if db_path := os.getenv("DB_PATH"):
        settings.db_path = db_path


# Load environment overrides on module import
load_env_overrides()