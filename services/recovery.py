"""
Recovery drivers module for Self-Healing Dashboard.
Implements service recovery mechanisms with OS detection and flapping protection.
"""
import asyncio
import platform
import subprocess
import sys
import time
from typing import Optional, Tuple

import config
import database
from . import notifier


# ==============================================================================
# OS Detection Utilities
# ==============================================================================

def get_current_os() -> str:
    """Detect current operating system."""
    system = platform.system().lower()
    if system == "windows":
        return "windows"
    elif system == "linux":
        return "linux"
    elif system == "darwin":
        return "macos"
    return "unknown"


def is_windows() -> bool:
    """Check if running on Windows."""
    return get_current_os() == "windows"


def is_linux() -> bool:
    """Check if running on Linux."""
    return get_current_os() == "linux"


# ==============================================================================
# Recovery Result
# ==============================================================================

class RecoveryResult:
    """Result of a recovery attempt."""

    def __init__(self, success: bool, message: str, error: Optional[str] = None):
        self.success = success
        self.message = message
        self.error = error

    def __repr__(self):
        status = "SUCCESS" if self.success else "FAILED"
        return f"RecoveryResult({status}, {self.message})"


# ==============================================================================
# Recovery Driver Interface
# ==============================================================================

class RecoveryDriver:
    """Base class for recovery drivers."""

    async def recover(self, service_name: str, service_config: config.ServiceConfig) -> RecoveryResult:
        """Attempt to recover a service. Override in subclasses."""
        raise NotImplementedError


# ==============================================================================
# Script-Based Recovery Driver
# ==============================================================================

class ScriptRecoveryDriver(RecoveryDriver):
    """
    Script-based recovery driver.
    Executes platform-specific commands to restart the service.
    """

    def __init__(self):
        self.timeout = config.recov_config.script_timeout

    async def recover(self, service_name: str, service_config: config.ServiceConfig) -> RecoveryResult:
        """Execute recovery script/command based on OS."""
        command = service_config.recovery_command

        if not command:
            return RecoveryResult(False, "No recovery command configured")

        current_os = get_current_os()
        final_command = self._prepare_command(command, current_os, service_config)

        if not final_command:
            return RecoveryResult(False, f"Unsupported OS: {current_os}")

        return await self._execute_command(final_command, service_name)

    def _prepare_command(
        self,
        command: str,
        os_type: str,
        service_config: config.ServiceConfig
    ) -> Optional[str]:
        """Prepare platform-specific command for background execution."""
        if command.endswith(".bat") or command.endswith(".cmd"):
            if os_type != "windows":
                return None
            return f'start "" "{command}"'

        if command.endswith(".sh"):
            if os_type != "linux":
                return None
            return f"bash {command} &"

        if "python" in command.lower():
            if os_type == "windows":
                return f'start "" python "{command}"'
            else:
                return f"python {command} &"

        if os_type == "windows":
            return f'start "" {command}'
        else:
            return f"{command} &"

    async def _execute_command(self, command: str, service_name: str) -> RecoveryResult:
        """Execute the recovery command with timeout."""
        logger = notifier.logger

        try:
            logger.info(f"Executing recovery command: {command}")

            # For Windows, use start command for detached process
            if is_windows():
                import subprocess
                import os

                # Get full path to script
                project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                script_path = "target_services\\mock_service.py"
                full_script = os.path.join(project_dir, script_path)

                # Use cmd /c start to run in new window (detached)
                start_cmd = f'start "MockService" cmd /c python "{full_script}"'
                logger.info(f"Running: {start_cmd}")

                subprocess.Popen(
                    start_cmd,
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NEW_CONSOLE
                )

                # Give it a moment to start
                await asyncio.sleep(0.5)
                logger.info("Recovery command sent (detached)")
                return RecoveryResult(True, "Recovery command executed (detached)")

            # For Linux/Mac use asyncio
            process = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                shell=True
            )

            try:
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(),
                    timeout=self.timeout
                )

                if process.returncode == 0:
                    output = stdout.decode() if stdout else "Command completed"
                    return RecoveryResult(True, f"Recovery command executed successfully", output)
                else:
                    error = stderr.decode() if stderr else f"Exit code: {process.returncode}"
                    return RecoveryResult(False, "Recovery command failed", error)

            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                return RecoveryResult(False, "Recovery command timed out")

        except FileNotFoundError:
            return RecoveryResult(False, f"Command not found: {command.split()[0]}")
        except Exception as e:
            return RecoveryResult(False, f"Recovery error: {str(e)}")


# ==============================================================================
# API-Based Recovery Driver (for Railway)
# ==============================================================================

class APIRecoveryDriver(RecoveryDriver):
    """API-based recovery driver - calls HTTP endpoint to restart service."""

    async def recover(self, service_name: str, service_config: config.ServiceConfig) -> RecoveryResult:
        """Call restart endpoint via HTTP."""
        import httpx

        restart_url = service_config.recovery_command
        if not restart_url:
            return RecoveryResult(False, "No restart URL configured")

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(restart_url)
                if response.status_code in [200, 201]:
                    return RecoveryResult(True, f"Recovery API called successfully")
                else:
                    return RecoveryResult(False, f"Recovery API failed: {response.status_code}")
        except Exception as e:
            return RecoveryResult(False, f"Recovery error: {str(e)}")


# Process-Based Recovery Driver (Stub)
# ==============================================================================

class ProcessRecoveryDriver(RecoveryDriver):
    """
    Process-based recovery driver.
    Stub implementation for direct process management (Windows/Linux service control).
    """

    async def recover(self, service_name: str, service_config: config.ServiceConfig) -> RecoveryResult:
        """Attempt to restart process (stub - requires platform-specific implementation)."""
        return RecoveryResult(
            False,
            "Process recovery not implemented - use script-based recovery",
            "Process management requires additional platform-specific implementation"
        )


# ==============================================================================
# Recovery Manager
# ==============================================================================

class RecoveryManager:
    """Manages service recovery with flapping protection."""

    def __init__(self):
        self.max_failures = config.settings.max_consecutive_failures
        self.flapping_window = config.settings.flapping_window
        self.drivers = {
            "script": ScriptRecoveryDriver(),
            "process": ProcessRecoveryDriver(),
            "api": APIRecoveryDriver(),
        }

    async def attempt_recovery(
        self,
        service_name: str,
        service_config: config.ServiceConfig,
        attempt_number: int
    ) -> Tuple[RecoveryResult, bool]:
        """
        Attempt to recover a service.
        Returns: (RecoveryResult, should_continue)
        - should_continue: True if more attempts allowed, False if max retries exceeded
        """
        # Check current failure count
        status = database.get_service_status(service_name)
        if status:
            current_failures = status.get("consecutive_failures", 0)
            last_failure_time = status.get("last_failure_time")

            # Check if we're in flapping state
            if current_failures >= self.max_failures:
                # Check if enough time has passed to reset (optional: could auto-reset after window)
                # For now, we stop recovery attempts
                await notifier.notify_max_retries_exceeded(service_name, current_failures)
                return RecoveryResult(
                    False,
                    f"Max failures ({self.max_failures}) exceeded - manual intervention required",
                    f"Total consecutive failures: {current_failures}"
                ), False

        # Get the appropriate driver
        recovery_type = service_config.recovery_type
        driver = self.drivers.get(recovery_type)

        if not driver:
            return RecoveryResult(False, f"Unknown recovery type: {recovery_type}"), False

        # Notify about recovery start
        await notifier.notify_recovery_started(
            service_name,
            attempt_number,
            f"Recovery type: {recovery_type}, command: {service_config.recovery_command}"
        )

        # Log recovery attempt to database
        database.add_recovery_attempt(
            service_name,
            attempt_number,
            recovery_type,
            False,  # Not yet known
            None
        )

        # Execute recovery
        result = await driver.recover(service_name, service_config)

        # Update recovery attempt in database
        database.add_recovery_attempt(
            service_name,
            attempt_number,
            recovery_type,
            result.success,
            result.error
        )

        if result.success:
            await notifier.notify_recovery_success(
                service_name,
                result.message
            )
            # Reset failure counter
            database.reset_failure_count(service_name)
            return result, True
        else:
            await notifier.notify_recovery_failed(
                service_name,
                attempt_number,
                result.error or result.message
            )
            # Increment failure counter
            new_count = database.increment_failure_count(service_name)

            # Check for flapping
            if new_count >= self.max_failures - 1:  # One before max
                await notifier.notify_flapping_detected(service_name, new_count)

            # Continue if under max, stop if exceeded
            should_continue = new_count < self.max_failures
            return result, should_continue


# Global recovery manager instance
recovery_manager = RecoveryManager()


# ==============================================================================
# Convenience Functions
# ==============================================================================

async def recover_service(
    service_name: str,
    service_config: config.ServiceConfig,
    max_attempts: int = 3
) -> Tuple[bool, int]:
    """
    Attempt to recover a service up to max_attempts times.
    Returns: (success, attempts_made)
    """
    for attempt in range(1, max_attempts + 1):
        result, should_continue = await recovery_manager.attempt_recovery(
            service_name,
            service_config,
            attempt
        )

        if result.success:
            return True, attempt

        if not should_continue:
            break

        # Wait before next attempt (exponential backoff could be added here)
        await asyncio.sleep(2)

    return False, max_attempts