"""
Database module for Self-Healing Dashboard.
Handles SQLite connection, schema initialization, and CRUD operations for logs.
"""
import sqlite3
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any
from contextlib import contextmanager, asynccontextmanager

import config


# ==============================================================================
# Database Connection Management
# ==============================================================================

class Database:
    """SQLite database manager with async-safe operations."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._connection: Optional[sqlite3.Connection] = None
        self._lock = asyncio.Lock()

    def connect(self):
        """Establish connection and create tables if needed."""
        self._connection = sqlite3.connect(self.db_path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self):
        """Create database tables if they don't exist."""
        cursor = self._connection.cursor()

        # Service status table - tracks current state and failure counts
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS service_status (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service_name TEXT UNIQUE NOT NULL,
                is_up BOOLEAN DEFAULT 0,
                consecutive_failures INTEGER DEFAULT 0,
                last_failure_time TEXT,
                last_recovery_time TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Event logs table - full history of all events
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS event_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                service_name TEXT NOT NULL,
                event_type TEXT NOT NULL,
                message TEXT NOT NULL,
                details TEXT
            )
        """)

        # Recovery attempts table - tracks all recovery actions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS recovery_attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                service_name TEXT NOT NULL,
                attempt_number INTEGER NOT NULL,
                recovery_type TEXT NOT NULL,
                success BOOLEAN NOT NULL,
                error_message TEXT
            )
        """)

        self._connection.commit()

    @contextmanager
    def get_cursor(self):
        """Context manager for database cursor."""
        cursor = self._connection.cursor()
        try:
            yield cursor
        finally:
            cursor.close()

    def close(self):
        """Close database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None


# Global database instance
db = Database(config.settings.db_path)


# ==============================================================================
# Service Status Operations
# ==============================================================================

def init_database():
    """Initialize database connection and schema."""
    db.connect()


def get_service_status(service_name: str) -> Optional[Dict[str, Any]]:
    """Get current status of a service."""
    with db.get_cursor() as cursor:
        cursor.execute(
            "SELECT * FROM service_status WHERE service_name = ?",
            (service_name,)
        )
        row = cursor.fetchone()
        if row:
            return dict(row)
    return None


def upsert_service_status(
    service_name: str,
    is_up: bool,
    failures: int = 0,
    last_failure: Optional[str] = None,
    last_recovery: Optional[str] = None
):
    """Insert or update service status."""
    with db.get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO service_status (service_name, is_up, consecutive_failures, last_failure_time, last_recovery_time)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(service_name) DO UPDATE SET
                is_up = excluded.is_up,
                consecutive_failures = excluded.consecutive_failures,
                last_failure_time = excluded.last_failure_time,
                last_recovery_time = excluded.last_recovery_time,
                updated_at = CURRENT_TIMESTAMP
        """, (service_name, is_up, failures, last_failure, last_recovery))
        db._connection.commit()


def increment_failure_count(service_name: str) -> int:
    """Increment consecutive failure counter and return new value."""
    with db.get_cursor() as cursor:
        cursor.execute("""
            UPDATE service_status
            SET consecutive_failures = consecutive_failures + 1,
                last_failure_time = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE service_name = ?
        """, (service_name,))
        db._connection.commit()

        cursor.execute(
            "SELECT consecutive_failures FROM service_status WHERE service_name = ?",
            (service_name,)
        )
        row = cursor.fetchone()
        return row[0] if row else 0


def reset_failure_count(service_name: str):
    """Reset failure counter after successful recovery."""
    with db.get_cursor() as cursor:
        cursor.execute("""
            UPDATE service_status
            SET consecutive_failures = 0,
                is_up = 1,
                last_recovery_time = CURRENT_TIMESTAMP,
                updated_at = CURRENT_TIMESTAMP
            WHERE service_name = ?
        """, (service_name,))
        db._connection.commit()


# ==============================================================================
# Event Log Operations
# ==============================================================================

def add_log(
    service_name: str,
    event_type: str,
    message: str,
    details: Optional[str] = None
):
    """Add a new event log entry."""
    with db.get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO event_logs (service_name, event_type, message, details)
            VALUES (?, ?, ?, ?)
        """, (service_name, event_type, message, details))
        db._connection.commit()


def get_recent_logs(limit: int = 20, service_name: Optional[str] = None) -> List[Dict[str, Any]]:
    """Get recent event logs."""
    with db.get_cursor() as cursor:
        if service_name:
            cursor.execute("""
                SELECT * FROM event_logs
                WHERE service_name = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """, (service_name, limit))
        else:
            cursor.execute("""
                SELECT * FROM event_logs
                ORDER BY timestamp DESC
                LIMIT ?
            """, (limit,))
        return [dict(row) for row in cursor.fetchall()]


def get_all_service_logs(limit: int = 100) -> List[Dict[str, Any]]:
    """Get all logs across all services."""
    return get_recent_logs(limit=limit)


# ==============================================================================
# Recovery Attempt Operations
# ==============================================================================

def add_recovery_attempt(
    service_name: str,
    attempt_number: int,
    recovery_type: str,
    success: bool,
    error_message: Optional[str] = None
):
    """Log a recovery attempt."""
    with db.get_cursor() as cursor:
        cursor.execute("""
            INSERT INTO recovery_attempts (service_name, attempt_number, recovery_type, success, error_message)
            VALUES (?, ?, ?, ?, ?)
        """, (service_name, attempt_number, recovery_type, success, error_message))
        db._connection.commit()


def get_recovery_history(service_name: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Get recovery history for a service."""
    with db.get_cursor() as cursor:
        cursor.execute("""
            SELECT * FROM recovery_attempts
            WHERE service_name = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (service_name, limit))
        return [dict(row) for row in cursor.fetchall()]


# ==============================================================================
# Dashboard Data Aggregators
# ==============================================================================

def get_dashboard_data() -> Dict[str, Any]:
    """Get all data needed for dashboard display."""
    # Get all service statuses
    with db.get_cursor() as cursor:
        cursor.execute("SELECT * FROM service_status ORDER BY service_name")
        services = [dict(row) for row in cursor.fetchall()]

    # Get recent logs
    logs = get_recent_logs(limit=20)

    return {
        "services": services,
        "logs": logs,
        "timestamp": datetime.now().isoformat()
    }