"""
Background service checker for Self-Healing Dashboard.
Performs periodic health checks and triggers recovery on failure.
"""
import asyncio
import socket
import sys
from datetime import datetime
from typing import Dict, Optional

import httpx

import config
import database
from . import notifier
from . import recovery


# ==============================================================================
# Service Health Checker
# ==============================================================================

class ServiceChecker:
    """Async service health checker with recovery integration."""

    def __init__(self):
        self.services = config.SERVICES
        self.check_interval = config.settings.check_interval
        self.recovery_timeout = config.settings.recovery_timeout
        self.running = False

    async def check_service_health(self, service_name: str, service_config: config.ServiceConfig) -> bool:
        """Check if a service is healthy via HTTP health endpoint or port check."""
        # Try HTTP health check first
        if service_config.check_url:
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    response = await client.get(service_config.check_url)
                    if response.status_code == 200:
                        return True
            except (httpx.ConnectError, httpx.TimeoutException, httpx.RequestError):
                pass

        # Fallback: port check
        return await self._check_port(service_config.host, service_config.port)

    async def _check_port(self, host: str, port: int) -> bool:
        """Check if a port is open."""
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(host, port),
                timeout=3.0
            )
            writer.close()
            await writer.wait_closed()
            return True
        except (asyncio.TimeoutError, OSError, ConnectionRefusedError):
            return False

    async def handle_service_down(
        self,
        service_name: str,
        service_config: config.ServiceConfig
    ):
        """Handle service down event - trigger notification and recovery."""
        # Get current status
        status = database.get_service_status(service_name)
        current_failures = status.get("consecutive_failures", 0) if status else 0

        # Notify service down
        await notifier.notify_service_down(
            service_name,
            f"Port {service_config.port} not responding, failures: {current_failures}"
        )

        # Update status to down
        database.upsert_service_status(service_name, is_up=False, failures=current_failures)

        # Start recovery in background without blocking
        asyncio.create_task(self._run_recovery(service_name, service_config))

    async def _run_recovery(self, service_name: str, service_config: config.ServiceConfig):
        """Run recovery in background after a delay."""
        # Wait a bit before recovery to let user see RED status
        await asyncio.sleep(5)

        # Check if service recovered on its own
        if await self.check_service_health(service_name, service_config):
            notifier.logger.info(f"Service {service_name} recovered on its own")
            database.upsert_service_status(service_name, is_up=True, failures=0)
            return

        # Get current failures
        status = database.get_service_status(service_name)
        current_failures = status.get("consecutive_failures", 0) if status else 0

        # Try recovery
        if current_failures < config.settings.max_consecutive_failures:
            success, attempts = await recovery.recover_service(
                service_name,
                service_config,
                max_attempts=1
            )

            # Wait for service to start
            await asyncio.sleep(self.recovery_timeout)

            # Verify
            if await self.check_service_health(service_name, service_config):
                await notifier.notify_service_up(
                    service_name,
                    f"Service recovered after {attempts} attempt(s)"
                )
                database.upsert_service_status(service_name, is_up=True, failures=0)
            else:
                notifier.logger.warning(f"Recovery verification failed for {service_name}")

    async def handle_service_up(
        self,
        service_name: str,
        service_config: config.ServiceConfig
    ):
        """Handle service up event - update status."""
        # Check if this is a state change (was down, now up)
        status = database.get_service_status(service_name)

        if status and not status.get("is_up", True):
            # Service came back up (possibly without our help)
            await notifier.notify_service_up(
                service_name,
                "Service became available"
            )
            database.upsert_service_status(service_name, is_up=True, failures=0)
        elif not status:
            # First time seeing this service
            database.upsert_service_status(service_name, is_up=True, failures=0)

    async def check_single_service(self, service_name: str, service_config: config.ServiceConfig):
        """Check a single service and handle result."""
        is_healthy = await self.check_service_health(service_name, service_config)

        if is_healthy:
            await self.handle_service_up(service_name, service_config)
        else:
            await self.handle_service_down(service_name, service_config)

    async def run_monitoring_loop(self):
        """Main monitoring loop - runs continuously."""
        self.running = True
        notifier.logger.info(f"Starting monitoring loop (interval: {self.check_interval}s)")

        # Initialize service statuses in database
        for name, svc_config in self.services.items():
            if not database.get_service_status(name):
                database.upsert_service_status(name, is_up=False, failures=0)

        while self.running:
            try:
                # Check all services concurrently
                tasks = [
                    self.check_single_service(name, svc_config)
                    for name, svc_config in self.services.items()
                    if svc_config.enabled
                ]

                if tasks:
                    await asyncio.gather(*tasks, return_exceptions=True)

            except Exception as e:
                notifier.logger.error(f"Error in monitoring loop: {e}")

            # Wait before next check cycle
            await asyncio.sleep(self.check_interval)

    def stop(self):
        """Stop the monitoring loop."""
        self.running = False
        notifier.logger.info("Monitoring loop stopped")


# Global checker instance
service_checker = ServiceChecker()


# ==============================================================================
# Background Task Management
# ==============================================================================

async def start_monitoring():
    """Start the background monitoring task."""
    asyncio.create_task(service_checker.run_monitoring_loop())


def stop_monitoring():
    """Stop the background monitoring task."""
    service_checker.stop()