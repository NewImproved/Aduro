"""Coordinator for Aduro Hybrid Stove integration."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
import logging
from typing import Any

from pyduro.actions import discover, get, set, raw, STATUS_PARAMS

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import (
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.exceptions import ConfigEntryAuthFailed


from .const import (
    DOMAIN,
    CONF_STOVE_SERIAL,
    CONF_STOVE_PIN,
    CONF_STOVE_MODEL,
    CONF_STOVE_IP,
    DEFAULT_SCAN_INTERVAL,
    UPDATE_INTERVAL_FAST,
    UPDATE_INTERVAL_NORMAL,
    UPDATE_COUNT_AFTER_COMMAND,
    POWER_HEAT_LEVEL_MAP,
    HEAT_LEVEL_POWER_MAP,
    TIMER_STARTUP_1,
    TIMER_STARTUP_2,
    TIMEOUT_MODE_TRANSITION,
    TIMEOUT_CHANGE_IN_PROGRESS,
    TIMEOUT_COMMAND_RESPONSE,
    STARTUP_STATES,
    SHUTDOWN_STATES,
)

_LOGGER = logging.getLogger(__name__)

CLOUD_BACKUP_ADDRESS = "apprelay20.stokercloud.dk"


class AduroCoordinator(DataUpdateCoordinator):
    """Class to manage fetching Aduro stove data."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""
        self.entry = entry
        self.hass = hass
        self._store = Store(hass, version=1, key=f"{DOMAIN}_{entry.entry_id}_pellet_data")
        # Configuration from config entry
        self.serial = entry.data[CONF_STOVE_SERIAL]
        self.pin = entry.data[CONF_STOVE_PIN]
        self.fixed_ip = entry.data.get(CONF_STOVE_IP)
        self.stove_model = entry.data.get(CONF_STOVE_MODEL, "H2")
        
        # Stove connection details
        self.stove_ip: str | None = None
        self.last_discovery: datetime | None = None

        #Stove software details
        self.firmware_version: str | None = None
        self.firmware_build: str | None = None
        self.device_id = f"aduro_{entry.entry_id}"
        
        # Fast polling management
        self._fast_poll_count = 0
        self._expecting_change = False
        
        # Mode change tracking
        self._toggle_heat_target = False
        self._target_heatlevel: int | None = None
        self._target_temperature: float | None = None
        self._target_operation_mode: int | None = None
        self._mode_change_started: datetime | None = None
        self._change_in_progress = False
        self._resend_attempt = 0
        self._max_resend_attempts = 3
        
        # Pellet tracking
        self._pellet_capacity = 9.5  # kg, configurable
        self._pellets_consumed = 0.0  # kg - accumulated from daily increments
        self._refill_counter = 0
        self._notification_level = 10  # % remaining when to notify
        self._shutdown_level = 5  # % remaining when to auto-shutdown
        self._auto_shutdown_enabled = False
        self._shutdown_notification_sent = False
        self._low_pellet_notification_sent = False

        # Historical consumption tracking (in __init__)
        self._consumption_snapshots = {}  # Stores monthly snapshots by year-month

        # Daily consumption tracking
        self._last_consumption_day: date | None = None
        
        # Wood mode tracking
        self._auto_resume_after_wood = False  # User preference
        self._was_in_wood_mode = False
        self._pre_wood_mode_heatlevel: int | None = None
        self._pre_wood_mode_temperature: float | None = None
        self._pre_wood_mode_operation_mode: int | None = None

        # Temperature alert tracking
        self._high_smoke_temp_threshold = 370.0  # °C
        self._high_smoke_duration_threshold = 30  # seconds
        self._high_smoke_temp_start_time: datetime | None = None
        self._high_smoke_alert_active = False
        self._high_smoke_alert_sent = False

        self._low_wood_temp_threshold = 175.0  # °C
        self._low_wood_duration_threshold = 300  # seconds
        self._low_wood_temp_start_time: datetime | None = None
        self._low_wood_alert_active = False
        self._low_wood_alert_sent = False
        
        # Timer tracking
        self._timer_startup_1_started: datetime | None = None
        self._timer_startup_2_started: datetime | None = None
        
        # Previous values for change detection
        self._previous_heatlevel: int | None = None
        self._previous_temperature: float | None = None
        self._previous_operation_mode: int | None = None
        self._previous_state: str | None = None
        
        # Initialize timestamp attributes to prevent errors
        self._last_network_update = datetime.now() - timedelta(minutes=10)
        self._last_consumption_update = datetime.now() - timedelta(minutes=10)
        
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the stove."""
        try:
            _LOGGER.debug("Starting data update cycle")
            
            # Discover stove IP if not known or too old
            if self.stove_ip is None or self._should_rediscover():
                _LOGGER.debug("Attempting stove discovery")
                await self._async_discover_stove()
            
            # Fetch all data
            data = {}
            
            # Get status data (most important)
            _LOGGER.debug("Fetching status data")
            status_data = await self._async_get_status()
            if status_data:
                data.update(status_data)
            
            # Get operating data
            _LOGGER.debug("Fetching operating data")
            operating_data = await self._async_get_operating_data()
            if operating_data:
                data.update(operating_data)
            
            # Get network data (less frequently)
            if self._should_update_network():
                _LOGGER.debug("Fetching network data")
                network_data = await self._async_get_network_data()
                if network_data:
                    data.update(network_data)
            
            # Get consumption data (less frequently)
            if self._should_update_consumption():
                _LOGGER.debug("Fetching consumption data")
                consumption_data = await self._async_get_consumption_data()
                if consumption_data:
                    data.update(consumption_data)
            else:
                # Preserve existing consumption data if we're not updating it
                if self.data and "consumption" in self.data:
                    data["consumption"] = self.data["consumption"]
                    _LOGGER.debug("Preserving existing consumption data")
            
            # Process state changes and auto-actions
            _LOGGER.debug("Processing state changes")
            await self._process_state_changes(data)
            
            # Check mode change progress
            _LOGGER.debug("Checking mode change progress")
            await self._check_mode_change_progress(data)
            
            # Handle auto-resume after wood mode
            if data.get("auto_resume_wood_mode", False):
                _LOGGER.info("Auto-resuming pellet operation after wood mode")
                await self._async_resume_pellet_operation()
            
            # Update timers
            _LOGGER.debug("Updating timers")
            self._update_timers(data)
            
            # Calculate pellet levels
            _LOGGER.debug("Calculating pellet levels")
            self._calculate_pellet_levels(data)
            
            # Check for low pellet conditions
            _LOGGER.debug("Checking pellet levels")
            await self._check_pellet_levels(data)
            
            # Check temperature alert conditions
            _LOGGER.debug("Checking temperature alerts")
            await self._check_temperature_alerts(data)

            # Add calculated/derived data
            _LOGGER.debug("Adding calculated data")
            self._add_calculated_data(data)
            
            # Manage polling interval
            self._manage_polling_interval()

            if not hasattr(self, '_last_pellet_save'):
                self._last_pellet_save = datetime.now()
        
            if (datetime.now() - self._last_pellet_save) > timedelta(hours=1):
                asyncio.create_task(self.async_save_pellet_data())
                self._last_pellet_save = datetime.now()
                _LOGGER.debug("Periodic pellet data save triggered")
            
            _LOGGER.debug("Data update cycle completed successfully")
            return data
            
        except Exception as err:
            _LOGGER.error("Error fetching stove data: %s", err, exc_info=True)
            # Try to rediscover on next update
            self.stove_ip = None
            raise UpdateFailed(f"Error communicating with stove: {err}")

    def _should_rediscover(self) -> bool:
        """Determine if we should rediscover the stove."""
        # Don't rediscover if using fixed IP
        if self.fixed_ip:
            return False
        
        if self.last_discovery is None:
            return True
        # Rediscover every hour
        try:
            return (datetime.now() - self.last_discovery) > timedelta(hours=1)
        except TypeError:
            _LOGGER.debug("Invalid last_discovery timestamp, forcing rediscovery")
            return True

    def _should_update_network(self) -> bool:
        """Network data doesn't change often, update every 5 minutes."""
        try:
            return (datetime.now() - self._last_network_update) > timedelta(minutes=5)
        except (TypeError, AttributeError) as err:
            _LOGGER.debug("Error checking network update time: %s, forcing update", err)
            self._last_network_update = datetime.now() - timedelta(minutes=10)
            return True

    def _should_update_consumption(self) -> bool:
        """Consumption data changes daily, update every 5 minutes."""
        try:
            return (datetime.now() - self._last_consumption_update) > timedelta(minutes=5)
        except (TypeError, AttributeError) as err:
            _LOGGER.debug("Error checking consumption update time: %s, forcing update", err)
            self._last_consumption_update = datetime.now() - timedelta(minutes=10)
            return True

    def _manage_polling_interval(self) -> None:
        """Adjust polling interval based on whether we're expecting changes."""
        if self._expecting_change and self._fast_poll_count > 0:
            # Fast polling mode
            self.update_interval = UPDATE_INTERVAL_FAST
            self._fast_poll_count -= 1
            _LOGGER.debug(
                "Fast polling: %d updates remaining",
                self._fast_poll_count
            )
        elif self._change_in_progress:
            # Keep fast polling while change in progress
            self.update_interval = UPDATE_INTERVAL_FAST
        else:
            # Normal polling mode
            self.update_interval = UPDATE_INTERVAL_NORMAL
            self._expecting_change = False
            self._fast_poll_count = 0

    def trigger_fast_polling(self) -> None:
        """Enable fast polling after sending a command."""
        self._expecting_change = True
        self._fast_poll_count = UPDATE_COUNT_AFTER_COMMAND
        self.update_interval = UPDATE_INTERVAL_FAST
        _LOGGER.debug("Fast polling enabled for %d updates", self._fast_poll_count)

    async def _process_state_changes(self, data: dict[str, Any]) -> None:
            """Process state changes and trigger auto-actions."""
            if "operating" not in data:
                return
            
            current_state = data["operating"].get("state")
            current_heatlevel = data["operating"].get("heatlevel")
            current_operation_mode = data["status"].get("operation_mode")
            current_temperature_ref = data["operating"].get("boiler_ref")
            
            _LOGGER.debug(
                "State change check - Previous HL: %s, Current HL: %s, Previous Mode: %s, Current Mode: %s, Change in progress: %s",
                self._previous_heatlevel,
                current_heatlevel,
                self._previous_operation_mode,
                current_operation_mode,
                self._change_in_progress
            )

            # Track wood mode transitions
            is_in_wood_mode = current_state in ["9"]
            
            # Entering wood mode - save current settings AND trigger auto-resume if enabled
            if is_in_wood_mode and not self._was_in_wood_mode:
                _LOGGER.info("Entering wood mode (state: %s), saving pellet mode settings", current_state)
                self._pre_wood_mode_operation_mode = current_operation_mode
                self._pre_wood_mode_heatlevel = current_heatlevel
                self._pre_wood_mode_temperature = current_temperature_ref
                self._was_in_wood_mode = True
                
                # NEW: Trigger auto-resume immediately when entering wood mode
                if self._auto_resume_after_wood:
                    _LOGGER.info("Auto-resume enabled, sending resume command to stove")
                    success = await self._async_resume_pellet_operation()
                    if success:
                        data["auto_resume_commanded"] = True
                    else:
                        _LOGGER.error("Failed to send auto-resume command")
            
            # Exiting wood mode - just clear the flag
            if not is_in_wood_mode and self._was_in_wood_mode:
                _LOGGER.info("Exiting wood mode, was in state: %s", self._previous_state)
                self._was_in_wood_mode = False

            # Initialize previous values on first run
            if self._previous_heatlevel is None:
                self._previous_heatlevel = current_heatlevel
                self._previous_temperature = current_temperature_ref
                self._previous_operation_mode = current_operation_mode
                _LOGGER.debug("Initialized previous values on first run")
                # Don't detect changes on first run
                self._previous_state = current_state
                data["app_change_detected"] = False
                return

            # =========================================================================
            # CRITICAL: Check for external stop command FIRST
            # =========================================================================
            if (self._previous_state is not None and 
                current_state in SHUTDOWN_STATES and 
                self._previous_state not in SHUTDOWN_STATES):
                
                _LOGGER.info("Stove stopped externally, state: %s", current_state)
                data["auto_stop_detected"] = True
                
                # CRITICAL FIX: Clear ALL pending changes and targets when externally stopped
                if self._change_in_progress or self._toggle_heat_target:
                    _LOGGER.warning(
                        "Clearing pending changes due to external stop command - "
                        "was targeting: HL=%s, Temp=%s, Mode=%s",
                        self._target_heatlevel,
                        self._target_temperature,
                        self._target_operation_mode
                    )
                
                # Clear all change tracking flags
                self._change_in_progress = False
                self._toggle_heat_target = False
                self._mode_change_started = None
                self._resend_attempt = 0
                
                # Clear all targets
                self._target_heatlevel = None
                self._target_temperature = None
                self._target_operation_mode = None
                
                # Update previous state immediately to prevent further processing
                self._previous_state = current_state
                self._previous_heatlevel = current_heatlevel
                self._previous_temperature = current_temperature_ref
                self._previous_operation_mode = current_operation_mode
                
                # Mark that no app change should be detected since we're handling the stop
                data["app_change_detected"] = False
                
                _LOGGER.info("All pending commands cleared - stove will remain off")
                return

            # Detect external changes (from app)
            app_change_detected = False
            
            # Always check for changes and update targets, but only flag as "app_change" when not in progress
            if current_operation_mode == 0:  # Heatlevel mode
                if (self._previous_heatlevel is not None and 
                    current_heatlevel != self._previous_heatlevel):
                    if not self._change_in_progress:
                        app_change_detected = True
                    _LOGGER.info(
                        "External heatlevel change detected: %s -> %s (power_pct: %d%%)",
                        self._previous_heatlevel,
                        current_heatlevel,
                        data["operating"].get("power_pct", 0)
                    )
                    # Always update our target to match current value
                    self._target_heatlevel = current_heatlevel
                    
            elif current_operation_mode == 1:  # Temperature mode
                if (self._previous_temperature is not None and 
                    current_temperature_ref != self._previous_temperature):
                    if not self._change_in_progress:
                        app_change_detected = True
                    _LOGGER.info("External temperature change detected: %s -> %s", 
                            self._previous_temperature, current_temperature_ref)
                    # Always update our target to match current value
                    self._target_temperature = current_temperature_ref
            
            # Detect operation mode changes
            if (self._previous_operation_mode is not None and 
                current_operation_mode != self._previous_operation_mode):
                if not self._change_in_progress:
                    app_change_detected = True
                _LOGGER.info("External operation mode change detected: %s -> %s",
                        self._previous_operation_mode, current_operation_mode)
                self._target_operation_mode = current_operation_mode
                
            else:
                # When change is in progress, don't flag as app change
                _LOGGER.debug("Change in progress, skipping app change detection")
            
            # Auto turn on when stove starts
            if (self._previous_state is not None and 
                current_state in STARTUP_STATES and 
                self._previous_state not in STARTUP_STATES):
                _LOGGER.info("Stove started, state: %s", current_state)
                data["auto_start_detected"] = True
            
            # Start timers based on state
            if current_state == "2" and self._previous_state != "2":
                self._timer_startup_1_started = datetime.now()
                _LOGGER.debug("Started startup timer 1")
            
            if current_state == "4" and self._previous_state != "4":
                self._timer_startup_2_started = datetime.now()
                _LOGGER.debug("Started startup timer 2")

            # Update targets to match current values when external change detected
            if app_change_detected:
                if current_operation_mode == 0:
                    self._target_heatlevel = current_heatlevel
                    self._target_operation_mode = 0
                elif current_operation_mode == 1:
                    self._target_temperature = current_temperature_ref
                    self._target_operation_mode = 1
                
                # ADDED: Clear change_in_progress when external change is detected
                # This prevents resending old commands
                if self._change_in_progress:
                    _LOGGER.info("External change detected - clearing change_in_progress flag")
                    self._change_in_progress = False
                    self._toggle_heat_target = False
                    self._mode_change_started = None
                    self._resend_attempt = 0

            # Update previous values
            self._previous_state = current_state
            self._previous_heatlevel = current_heatlevel
            self._previous_temperature = current_temperature_ref
            self._previous_operation_mode = current_operation_mode
            
            # Add detection flag to data
            data["app_change_detected"] = app_change_detected

    async def _check_mode_change_progress(self, data: dict[str, Any]) -> None:
        """Check if mode change is complete and handle retries."""
        if not self._change_in_progress:
            return
        
        if "operating" not in data or "status" not in data:
            return
        
        current_state = data["operating"].get("state")
        current_heatlevel = data["operating"].get("heatlevel")
        current_temperature_ref = data["operating"].get("boiler_ref")
        current_operation_mode = data["status"].get("operation_mode")
        
        # ADDED: If stove is in shutdown state, abort any pending changes
        if current_state in SHUTDOWN_STATES:
            _LOGGER.warning(
                "Stove is in shutdown state (%s) - aborting pending mode change",
                current_state
            )
            self._change_in_progress = False
            self._toggle_heat_target = False
            self._mode_change_started = None
            self._resend_attempt = 0
            self._target_heatlevel = None
            self._target_temperature = None
            self._target_operation_mode = None
            return
        
        # Check if change is complete
        change_complete = True
        
        if self._target_heatlevel is not None:
            if current_heatlevel != self._target_heatlevel:
                change_complete = False
                
        if self._target_temperature is not None:
            if current_temperature_ref != self._target_temperature:
                change_complete = False
        
        if self._target_operation_mode is not None:
            if current_operation_mode != self._target_operation_mode:
                change_complete = False
        
        if change_complete:
            _LOGGER.info(
                "Mode change completed - HL: %s, Temp: %s, Mode: %s",
                current_heatlevel,
                current_temperature_ref,
                current_operation_mode
            )
            # Clear ALL flags
            self._change_in_progress = False
            self._toggle_heat_target = False
            self._mode_change_started = None
            self._resend_attempt = 0
            # Clear targets
            self._target_heatlevel = None
            self._target_temperature = None
            self._target_operation_mode = None
            return
        
        # Check for timeout
        if self._mode_change_started:
            try:
                elapsed = (datetime.now() - self._mode_change_started).total_seconds()
            except TypeError:
                _LOGGER.warning("Invalid _mode_change_started timestamp, resetting")
                self._mode_change_started = datetime.now()
                elapsed = 0
            
            # Try resending after TIMEOUT_COMMAND_RESPONSE
            if elapsed > TIMEOUT_COMMAND_RESPONSE and self._resend_attempt < self._max_resend_attempts:
                self._resend_attempt += 1
                _LOGGER.warning(
                    "Mode change timeout, resending command (attempt %d/%d)",
                    self._resend_attempt,
                    self._max_resend_attempts
                )
                await self._resend_pending_commands()
                self._mode_change_started = datetime.now()
            
            # Final timeout - give up
            elif elapsed > TIMEOUT_CHANGE_IN_PROGRESS:
                _LOGGER.error("Mode change failed after timeout and retries")
                self._change_in_progress = False
                self._toggle_heat_target = False
                self._mode_change_started = None
                self._resend_attempt = 0
                # ADDED: Clear targets on timeout
                self._target_heatlevel = None
                self._target_temperature = None
                self._target_operation_mode = None

    async def _resend_pending_commands(self) -> None:
        """Resend pending commands that haven't been confirmed."""
        if self._target_operation_mode is not None:
            _LOGGER.debug("Resending operation mode: %s", self._target_operation_mode)
            await self._async_send_command(
                "regulation.operation_mode",
                self._target_operation_mode,
                retries=1
            )
        
        await asyncio.sleep(3)
        
        if self._target_heatlevel is not None:
            _LOGGER.debug("Resending heatlevel: %s", self._target_heatlevel)
            fixed_power = POWER_HEAT_LEVEL_MAP[self._target_heatlevel]
            await self._async_send_command(
                "regulation.fixed_power",
                fixed_power,
                retries=1
            )
        
        if self._target_temperature is not None:
            _LOGGER.debug("Resending temperature: %s", self._target_temperature)
            await self._async_send_command(
                "boiler.temp",
                self._target_temperature,
                retries=1
            )

    def _update_timers(self, data: dict[str, Any]) -> None:
        """Update timer countdown values."""
        timers = {}
        
        # Timer 1
        if self._timer_startup_1_started:
            try:
                elapsed = (datetime.now() - self._timer_startup_1_started).total_seconds()
                remaining = max(0, TIMER_STARTUP_1 - int(elapsed))
                timers["startup_1_remaining"] = remaining
                
                if remaining == 0:
                    self._timer_startup_1_started = None
            except (TypeError, AttributeError) as err:
                _LOGGER.debug("Error calculating timer 1: %s", err)
                timers["startup_1_remaining"] = 0
                self._timer_startup_1_started = None
        else:
            timers["startup_1_remaining"] = 0
        
        # Timer 2
        if self._timer_startup_2_started:
            try:
                elapsed = (datetime.now() - self._timer_startup_2_started).total_seconds()
                remaining = max(0, TIMER_STARTUP_2 - int(elapsed))
                timers["startup_2_remaining"] = remaining
                
                if remaining == 0:
                    self._timer_startup_2_started = None
            except (TypeError, AttributeError) as err:
                _LOGGER.debug("Error calculating timer 2: %s", err)
                timers["startup_2_remaining"] = 0
                self._timer_startup_2_started = None
        else:
            timers["startup_2_remaining"] = 0
        
        data["timers"] = timers

    def _calculate_pellet_levels(self, data: dict[str, Any]) -> None:
        """Calculate pellet levels based on consumption_day increments."""
        
        # Get today's consumption from sensor
        if "consumption" not in data:
            _LOGGER.debug("No consumption data available")
            return
        
        current_day_consumption = data["consumption"].get("day", 0)
        
        # Initialize on first run
        if not hasattr(self, '_last_consumption_day_value'):
            self._last_consumption_day_value = current_day_consumption
            _LOGGER.info(
                "Initialized consumption tracking: baseline=%.2f kg",
                current_day_consumption
            )
        
        # Calculate the change in consumption_day
        consumption_change = current_day_consumption - self._last_consumption_day_value
        
        # Handle midnight reset (consumption_day decreased)
        if consumption_change < 0:
            _LOGGER.info(
                "Midnight reset detected - consumption_day went from %.2f to %.2f kg",
                self._last_consumption_day_value,
                current_day_consumption
            )
            # Update baseline to new (reset) value, don't change pellets_consumed
            self._last_consumption_day_value = current_day_consumption
            
        # Handle normal consumption increase
        elif consumption_change > 0:
            # Add the increment to total consumed
            self._pellets_consumed += consumption_change
            self._last_consumption_day_value = current_day_consumption
            
            _LOGGER.debug(
                "Consumption increment: +%.2f kg (total consumed: %.2f kg, today: %.2f kg)",
                consumption_change,
                self._pellets_consumed,
                current_day_consumption
            )
        
        # No change - do nothing
        else:
            pass
        
        # Calculate remaining pellets
        amount_remaining = max(0, self._pellet_capacity - self._pellets_consumed)
        percentage_remaining = (
            (amount_remaining / self._pellet_capacity * 100) 
            if self._pellet_capacity > 0 
            else 0
        )
        
        pellets = {
            "capacity": self._pellet_capacity,
            "consumed": self._pellets_consumed,
            "amount": amount_remaining,
            "percentage": percentage_remaining,
            "refill_counter": self._refill_counter,
            "notification_level": self._notification_level,
            "shutdown_level": self._shutdown_level,
            "auto_shutdown_enabled": self._auto_shutdown_enabled,
            "last_day_value": self._last_consumption_day_value,  # For debugging
        }
        
        data["pellets"] = pellets

    async def _check_pellet_levels(self, data: dict[str, Any]) -> None:
        """Check pellet levels and trigger notifications or shutdown."""
        if "pellets" not in data:
            return
        
        percentage = data["pellets"]["percentage"]
        
        # Check for low pellet notification
        if percentage <= self._notification_level and not self._low_pellet_notification_sent:
            _LOGGER.warning(
                "Low pellet level: %.1f%% (notification threshold: %.1f%%)",
                percentage,
                self._notification_level
            )
            data["pellets"]["low_pellet_alert"] = True
            self._low_pellet_notification_sent = True
        elif percentage > self._notification_level:
            # Reset notification flag when level rises above threshold
            self._low_pellet_notification_sent = False
            data["pellets"]["low_pellet_alert"] = False
        
        # Check for auto-shutdown
        if (self._auto_shutdown_enabled and 
            percentage <= self._shutdown_level and 
            not self._shutdown_notification_sent):
            
            _LOGGER.warning(
                "Critical pellet level: %.1f%% (shutdown threshold: %.1f%%), initiating shutdown",
                percentage,
                self._shutdown_level
            )
            data["pellets"]["shutdown_alert"] = True
            self._shutdown_notification_sent = True
            
            # Attempt to stop the stove
            await self.async_stop_stove()
        elif percentage > self._shutdown_level:
            # Reset shutdown flag when level rises above threshold
            self._shutdown_notification_sent = False
            data["pellets"]["shutdown_alert"] = False

    def _add_calculated_data(self, data: dict[str, Any]) -> None:
        """Add calculated and derived data."""
        if "operating" not in data or "status" not in data:
            return
        
        current_operation_mode = data["status"].get("operation_mode", 0)
        current_heatlevel = data["operating"].get("heatlevel", 1)
        current_temperature_ref = data["operating"].get("boiler_ref", 20)
        current_temperature = data["operating"].get("boiler_temp", 20)
        
        # Boolean checks
        heatlevel_match = (self._target_heatlevel == current_heatlevel 
            if self._target_heatlevel is not None 
            else True
            )
        temp_match = (self._target_temperature == current_temperature_ref 
            if self._target_temperature is not None 
            else True
            )
        mode_match = (self._target_operation_mode == current_operation_mode 
            if self._target_operation_mode is not None 
            else True
            )
        
        # Mode transition state
        if self._toggle_heat_target:
            mode_transition = "starting"
        elif current_operation_mode == 0 and not heatlevel_match:
            mode_transition = "heatlevel_adjusting"
        elif current_operation_mode == 1 and not temp_match:
            mode_transition = "temperature_adjusting"
        else:
            mode_transition = "idle"
        
        # Determine display target
        if self._change_in_progress:
            display_mode = self._target_operation_mode if self._target_operation_mode is not None else current_operation_mode
        else:
            display_mode = current_operation_mode
        
        if display_mode == 0:  # Heatlevel mode
            display_target = self._target_heatlevel if self._target_heatlevel is not None else current_heatlevel
            display_target_type = "heatlevel"
        elif display_mode == 1:  # Temperature mode
            display_target = self._target_temperature if self._target_temperature is not None else current_temperature_ref
            display_target_type = "temperature"
        else:  # Wood mode
            display_target = 0
            display_target_type = "wood"
        
        # Format display
        if display_target_type == "heatlevel":
            from .const import HEAT_LEVEL_DISPLAY
            display_format = f"Heat Level (room temp.): {display_target} ({current_temperature})°C"
        elif display_target_type == "temperature":
            display_format = f"Target temp. (room temp.): {display_target} ({current_temperature})°C"
        else:
            display_format = "Wood Mode"
        
        data["calculated"] = {
            "heatlevel_match": heatlevel_match,
            "temperature_match": temp_match,
            "operation_mode_match": mode_match,
            "change_in_progress": self._change_in_progress,
            "toggle_heat_target": self._toggle_heat_target,
            "mode_transition": mode_transition,
            "display_target": display_target,
            "display_target_type": display_target_type,
            "display_format": display_format,
        }

    async def _async_discover_stove(self) -> None:
        """Discover the stove on the network."""
        # If fixed IP is configured, use it instead of discovery
        if self.fixed_ip:
            _LOGGER.info("Using fixed IP address: %s", self.fixed_ip)
            self.stove_ip = self.fixed_ip
            self.last_discovery = datetime.now()
            
            # Try to get firmware info if possible
            try:
                response = await self.hass.async_add_executor_job(discover.run)
                data = response.parse_payload()
                
                old_version = self.firmware_version
                old_build = self.firmware_build
                
                self.firmware_version = data.get("Ver")
                self.firmware_build = data.get("Build")
                
                version_changed = (old_version != self.firmware_version or 
                                old_build != self.firmware_build)
                
                if version_changed and old_version is not None:
                    _LOGGER.info(
                        "Firmware version changed from %s.%s to %s.%s",
                        old_version or "?",
                        old_build or "?",
                        self.firmware_version or "?",
                        self.firmware_build or "?"
                    )
                    await self._update_device_registry()
            except Exception as err:
                _LOGGER.debug("Could not get firmware info via discovery: %s", err)
            
            return
        
        # Discovery logic for when no fixed IP is set
        try:
            response = await self.hass.async_add_executor_job(discover.run)
            data = response.parse_payload()

            self.stove_ip = data.get("IP", CLOUD_BACKUP_ADDRESS)
            
            # Store previous versions to detect changes
            old_version = self.firmware_version
            old_build = self.firmware_build
            
            self.firmware_version = data.get("Ver")
            self.firmware_build = data.get("Build")

            _LOGGER.debug(
                "Discovery complete - IP: %s, Version: %s, Build: %s",
                self.stove_ip,
                self.firmware_version,
                self.firmware_build,
            )

            if not self.stove_ip or "0.0.0.0" in self.stove_ip:
                self.stove_ip = CLOUD_BACKUP_ADDRESS
                _LOGGER.warning(
                    "Invalid stove IP, using cloud backup: %s", CLOUD_BACKUP_ADDRESS
                )

            self.last_discovery = datetime.now()
            _LOGGER.info(
                "Discovered stove at: %s (Firmware: %s Build: %s)",
                self.stove_ip,
                self.firmware_version,
                self.firmware_build,
            )

            # Check if firmware changed
            version_changed = (old_version != self.firmware_version or 
                            old_build != self.firmware_build)
            
            if version_changed and old_version is not None:
                _LOGGER.info(
                    "Firmware version changed from %s.%s to %s.%s",
                    old_version or "?",
                    old_build or "?",
                    self.firmware_version or "?",
                    self.firmware_build or "?"
                )
                await self._update_device_registry()

        except Exception as err:
            _LOGGER.warning("Discovery failed, using cloud backup: %s", err)
            self.stove_ip = CLOUD_BACKUP_ADDRESS
            self.last_discovery = datetime.now()

    async def _async_get_status(self) -> dict[str, Any] | None:
        """Get comprehensive status from the stove."""
        try:
            response = await self.hass.async_add_executor_job(
                raw.run,
                self.stove_ip,
                self.serial,
                self.pin,
                11,  # function_id
                "*"  # payload
            )
            
            status = response.parse_payload().split(",")
            
            # Map status to STATUS_PARAMS
            status_dict = {}
            i = 0
            for key in STATUS_PARAMS:
                if i < len(status):
                    status_dict[key] = status[i]
                i += 1
            
            # Extract commonly used values for easier access
            extracted_status = {
                "consumption_total": float(status_dict.get("consumption_total", 0)),
                "operation_mode": int(status_dict.get("operation_mode", 0)),
                "raw": status_dict  # Keep full status data available
            }
            
            return {"status": extracted_status}
            
        except Exception as err:
            _LOGGER.error("Error getting status: %s", err)
            return None

    async def _async_get_operating_data(self) -> dict[str, Any] | None:
        """Get detailed operating data from the stove."""
        try:
            response = await self.hass.async_add_executor_job(
                raw.run,
                self.stove_ip,
                self.serial,
                self.pin,
                11,  # function_id
                "001*"  # payloadasync def _async_discover_stove(self) -> None:
            )
            
            #data = response.parse_payload().split(',')
            payload = response.parse_payload() #
            _LOGGER.debug("Full payload received from stove: %s", payload) #

            data = payload.split(',') #
            
            operating_data = {
                "boiler_temp": float(data[0]) if data[0] else 0,
                "boiler_ref": float(data[1]) if data[1] else 0,
                "dhw_temp": float(data[4]) if data[4] else 0,
                "state": data[6],
                "substate": data[5],
                "power_kw": float(data[31]) if data[31] else 0,
                "power_pct": float(data[99]) if data[104] else 0,  # CHANGED from data[36]
                "shaft_temp": float(data[35]) if data[35] else 0,
                "smoke_temp": float(data[37]) if data[37] else 0,
                "internet_uptime": data[38],
                "milli_ampere": float(data[24]) if data[24] else 0,
                "carbon_monoxide": float(data[26]) if data[26] else 0,
                "carbon_monoxide_yellow": float(data[101]) if data[101] else 0,
                "carbon_monoxide_red": float(data[102]) if data[102] else 0,
                "operating_time_auger": int(data[119]) if data[119] else 0,
                "operating_time_ignition": int(data[120]) if data[120] else 0,
                "operating_time_stove": int(data[121]) if data[121] else 0,
            }
            
            # Extract heatlevel from power_pct with tolerance for inexact values
            power_pct = int(float(data[99])) if data[104] else 0

            # Map power percentage to heatlevel with tolerance
            # The stove returns approximate values, not exactly 10, 50, or 100
            if power_pct <= 30:  # Level 1: around 10% ± 20
                heatlevel = 1
            elif power_pct <= 75:  # Level 2: around 50% ± 25
                heatlevel = 2
            else:  # Level 3: around 100%
                heatlevel = 3

            operating_data["heatlevel"] = heatlevel

            _LOGGER.debug(
                "Extracted heatlevel: %d from power_pct: %d%% (tolerance-based)",
                heatlevel,
                power_pct
            )
            
            # Get operation mode from status if available
            if self.data and "status" in self.data:
                operation_mode = self.data["status"].get("operation_mode", 0)
                operating_data["operation_mode"] = int(operation_mode)
            
            return {"operating": operating_data}
            
        except Exception as err:
            _LOGGER.error("Error getting operating data: %s", err)
            return None

    async def _async_get_network_data(self) -> dict[str, Any] | None:
        """Get network information from the stove."""
        try:
            response = await self.hass.async_add_executor_job(
                raw.run,
                self.stove_ip,
                self.serial,
                self.pin,
                1,  # function_id
                "wifi.router"  # payload
            )
            
            data = response.parse_payload().split(',')
            
            network_data = {
                "router_ssid": data[0][7:] if len(data) > 0 else "",
                "stove_ip": data[4] if len(data) > 4 else "",
                "router_ip": data[5] if len(data) > 5 else "",
                "stove_rssi": data[6] if len(data) > 6 else "",
                "stove_mac": data[9] if len(data) > 9 else "",
            }
            
            self._last_network_update = datetime.now()
            return {"network": network_data}
            
        except Exception as err:
            _LOGGER.error("Error getting network data: %s", err)
            return None

    async def _async_get_consumption_data(self) -> dict[str, Any] | None:
        """Get consumption data from the stove."""
        try:
            from datetime import date
            
            # Initialize with empty structures
            consumption_data = {
                "day": 0,
                "yesterday": 0,
                "month": 0,
                "year": 0,
                "monthly_history": {},
                "yearly_history": {},
                "year_from_stove": 0,
            }
            
            # Get daily consumption
            response = await self.hass.async_add_executor_job(
                raw.run,
                self.stove_ip,
                self.serial,
                self.pin,
                6,  # function_id
                "total_days"  # payload
            )
            
            data = response.parse_payload().split(',')
            data[0] = data[0][11:]  # Remove "total_days" prefix
            
            today = date.today().day
            yesterday = (date.today() - timedelta(1)).day
            
            consumption_data["day"] = float(data[today - 1]) if len(data) >= today else 0
            consumption_data["yesterday"] = float(data[yesterday - 1]) if len(data) >= yesterday else 0
            
            # Get monthly consumption
            response = await self.hass.async_add_executor_job(
                raw.run,
                self.stove_ip,
                self.serial,
                self.pin,
                6,  # function_id
                "total_months"  # payload
            )
            
            data = response.parse_payload().split(',')
            data[0] = data[0][13:]  # Remove "total_months" prefix
            
            current_month = date.today().month
            current_year = date.today().year
            
            # Current month consumption
            consumption_data["month"] = float(data[current_month - 1]) if len(data) >= current_month else 0
            
            # Store all monthly data - this is a calendar year array (Jan=0, Dec=11)
            # Note: December (position 11) contains last year's December until this year's December is recorded
            monthly_history = {}
            month_names = [
                "january", "february", "march", "april", "may", "june",
                "july", "august", "september", "october", "november", "december"
            ]
            
            for i, month_name in enumerate(month_names):
                if i < len(data):
                    monthly_history[month_name] = float(data[i])
            
            consumption_data["monthly_history"] = monthly_history
            
            # Initialize snapshots for all months if not already done
            # This allows us to start tracking immediately
            if not hasattr(self, '_snapshots_initialized') or not self._snapshots_initialized:
                _LOGGER.info("Initializing consumption snapshots from current data")
                for i, month_name in enumerate(month_names):
                    if i < len(data):
                        value = float(data[i])
                        # Only save if there's real consumption data (not just 0.002 default)
                        if value > 0.002:
                            # For months after current month, assume it's from last year
                            # For months before or equal to current month, assume current year
                            if i + 1 > current_month:
                                # Future months in array are from last year
                                snapshot_key = f"{current_year - 1}_{month_name}"
                            else:
                                # Past/current months are from this year
                                snapshot_key = f"{current_year}_{month_name}"
                            
                            self._consumption_snapshots[snapshot_key] = value
                            _LOGGER.debug(f"Initialized snapshot: {snapshot_key} = {value:.2f} kg")
                
                self._snapshots_initialized = True
            
            # Save snapshot of current month for historical comparison
            # This preserves the exact consumption values at the end of each month
            current_month_name = month_names[current_month - 1]
            snapshot_key = f"{current_year}_{current_month_name}"
            current_month_value = float(data[current_month - 1]) if current_month - 1 < len(data) else 0
            
            # Update current month snapshot
            if current_month_value > 0.002:
                self._consumption_snapshots[snapshot_key] = current_month_value
            
            # Store snapshots in consumption data for sensor access
            consumption_data["monthly_snapshots"] = dict(self._consumption_snapshots)
            
            # Calculate year-over-year comparison if we have data from previous year
            last_year = current_year - 1
            last_year_same_month_key = f"{last_year}_{current_month_name}"
            
            if last_year_same_month_key in self._consumption_snapshots:
                last_year_value = self._consumption_snapshots[last_year_same_month_key]
                current_year_value = current_month_value
                
                if last_year_value > 0:
                    difference = current_year_value - last_year_value
                    percentage_change = (difference / last_year_value) * 100
                    
                    consumption_data["year_over_year"] = {
                        "current_month": current_month_name,
                        "current_year_value": round(current_year_value, 2),
                        "last_year_value": round(last_year_value, 2),
                        "difference": round(difference, 2),
                        "percentage_change": round(percentage_change, 1),
                    }
                    
                    _LOGGER.debug(
                        f"Year-over-year comparison for {current_month_name}: "
                        f"{current_year_value:.2f} kg ({current_year}) vs "
                        f"{last_year_value:.2f} kg ({last_year}) = "
                        f"{difference:+.2f} kg ({percentage_change:+.1f}%)"
                    )
            
            consumption_data["monthly_history"] = monthly_history
            
            # Calculate year-to-date from monthly totals
            # Only sum months from January through current month (exclude future months which are from last year)
            year_to_date = 0
            months_included = []
            
            for i in range(current_month):  # 0 to current_month-1 (e.g., 0-10 for November)
                if i < len(data):
                    value = float(data[i])
                    if value > 0.002:  # Exclude default 0.002 values
                        year_to_date += value
                        months_included.append(month_names[i])
            
            _LOGGER.info(
                f"Yearly consumption calculated for {current_year}: {year_to_date:.2f} kg "
                f"(months: {', '.join(months_included)})"
            )
            
            # Try to get yearly data from stove (for reference)
            response = await self.hass.async_add_executor_job(
                raw.run,
                self.stove_ip,
                self.serial,
                self.pin,
                6,  # function_id
                "total_years"  # payload
            )
            
            data = response.parse_payload().split(',')
            data[0] = data[0][12:]  # Remove "total_years" prefix
            
            # Store yearly history (even if zeros, for future reference)
            yearly_history = {}
            base_year = 2013  # Stove started tracking from 2013
            for i in range(len(data)):
                year_label = base_year + i
                yearly_history[str(year_label)] = float(data[i])
            
            consumption_data["yearly_history"] = yearly_history
            
            # Use calculated year-to-date as the primary yearly value
            consumption_data["year"] = year_to_date
            
            # Also store the stove's reported yearly value (if different)
            year_position = current_year % len(data)
            stove_yearly_value = float(data[year_position]) if len(data) > year_position else 0
            consumption_data["year_from_stove"] = stove_yearly_value
            
            self._last_consumption_update = datetime.now()
            return {"consumption": consumption_data}
            
        except Exception as err:
            _LOGGER.error("Error getting consumption data: %s", err)
            return None

    async def _update_device_registry(self):
        """Update the device info in Home Assistant registry."""
        if not (self.firmware_version or self.firmware_build):
            _LOGGER.debug("Firmware info not available yet, skipping device update.")
            return

        # Build firmware version string
        if self.firmware_version and self.firmware_build:
            new_version = f"{self.firmware_version}.{self.firmware_build}"
        elif self.firmware_version:
            new_version = self.firmware_version
        else:
            return

        # Get device registry
        device_registry = dr.async_get(self.hass)

        # Find the device using the SAME identifiers as in device_info
        device_entry = device_registry.async_get_device(
            identifiers={(DOMAIN, f"aduro_{self.coordinator.entry.entry_id}")}
        )

        if device_entry:
            # Only update if version has changed or is not set
            if device_entry.sw_version != new_version:
                _LOGGER.info(
                    "Updating device firmware: %s -> %s",
                    device_entry.sw_version or "Unknown",
                    new_version
                )
                device_registry.async_update_device(
                    device_entry.id,
                    sw_version=new_version
                )
            else:
                _LOGGER.debug("Firmware version unchanged: %s", new_version)
        else:
            _LOGGER.warning(
                "Could not find device with identifiers: %s",
                (DOMAIN, self.entry.entry_id)
            )


    async def async_load_pellet_data(self) -> None:
        """Load pellet tracking data from storage."""
        try:
            data = await self._store.async_load()
            if data:
                self._pellets_consumed = data.get("pellets_consumed", 0.0)
                self._refill_counter = data.get("refill_counter", 0)
                self._consumption_snapshots = data.get("consumption_snapshots", {})
                self._snapshots_initialized = data.get("snapshots_initialized", False)
                
                # Convert last_consumption_day string back to date object
                last_day_str = data.get("last_consumption_day")
                if last_day_str:
                    from datetime import datetime
                    self._last_consumption_day = datetime.fromisoformat(last_day_str).date()
                
                _LOGGER.info(
                    "Loaded pellet data from storage - consumed: %.2f kg, refills: %d, days: %d",
                    self._pellets_consumed,
                    self._refill_counter
                )
            else:
                _LOGGER.debug("No stored pellet data found, starting fresh")
        except Exception as err:
            _LOGGER.warning("Failed to load pellet data from storage: %s", err)

    async def async_save_pellet_data(self) -> None:
        """Save pellet tracking data to storage."""
        try:
            data = {
                "pellets_consumed": self._pellets_consumed,
                "refill_counter": self._refill_counter,
                "consumption_snapshots": self._consumption_snapshots,
                "snapshots_initialized": getattr(self, '_snapshots_initialized', False),
                "last_consumption_day": self._last_consumption_day.isoformat() if self._last_consumption_day else None,
            }
            await self._store.async_save(data)
            _LOGGER.debug("Saved pellet data to storage")
        except Exception as err:
            _LOGGER.error("Failed to save pellet data to storage: %s", err)
            
    # -------------------------------------------------------------------------
    # Pellet management methods
    # -------------------------------------------------------------------------

    def refill_pellets(self) -> None:
        """Reset pellet consumption after refilling."""
        from datetime import date
        
        # Get current daily consumption to use as new baseline
        if self.data and "consumption" in self.data:
            today_consumption = self.data["consumption"].get("day", 0)
            self._consumption_at_refill = today_consumption
            _LOGGER.info(
                "Pellets refilled, baseline set to current daily consumption: %.2f kg",
                today_consumption
            )
        else:
            self._consumption_at_refill = 0.0
        
        # Reset all tracking
        self._pellets_consumed = 0.0
        self._last_consumption_day = date.today()
        self._refill_counter += 1
        self._low_pellet_notification_sent = False
        self._shutdown_notification_sent = False
        
        _LOGGER.info(
            "Pellets refilled - counter: %d, capacity: %.1f kg, date: %s",
            self._refill_counter,
            self._pellet_capacity,
            self._last_consumption_day
        )

        asyncio.create_task(self.async_save_pellet_data())

    def reset_refill_counter(self) -> None:
        """Reset refill counter after cleaning."""
        self._refill_counter = 0
        _LOGGER.info("Refill counter reset")

        asyncio.create_task(self.async_save_pellet_data())

    def set_pellet_capacity(self, capacity: float) -> None:
        """Set pellet capacity."""
        self._pellet_capacity = capacity
        _LOGGER.info("Pellet capacity set to: %s kg", capacity)

    def set_notification_level(self, level: float) -> None:
        """Set notification level (percentage)."""
        self._notification_level = level
        _LOGGER.info("Notification level set to: %s%%", level)

    def set_shutdown_level(self, level: float) -> None:
        """Set auto-shutdown level (percentage)."""
        self._shutdown_level = level
        _LOGGER.info("Shutdown level set to: %s%%", level)

    def set_auto_shutdown_enabled(self, enabled: bool) -> None:
        """Enable or disable automatic shutdown at low pellet level."""
        self._auto_shutdown_enabled = enabled
        _LOGGER.info("Auto-shutdown %s", "enabled" if enabled else "disabled")

    def set_auto_resume_after_wood(self, enabled: bool) -> None:
        """Enable or disable automatic resume after wood mode."""
        old_value = self._auto_resume_after_wood
        self._auto_resume_after_wood = enabled
        
        # If disabling while in wood mode, send stop command to cancel pending resume
        if old_value and not enabled and self._was_in_wood_mode:
            _LOGGER.info("Auto-resume disabled during wood mode - sending stop command to cancel pending resume")
            # Schedule the stop command
            asyncio.create_task(self.async_stop_stove())
        
        _LOGGER.info("Auto-resume after wood mode %s", "enabled" if enabled else "disabled")
    
    # -------------------------------------------------------------------------
    # Temperature alert methods
    # -------------------------------------------------------------------------

    def set_high_smoke_temp_threshold(self, temperature: float) -> None:
        """Set high smoke temperature threshold."""
        self._high_smoke_temp_threshold = temperature
        _LOGGER.info("High smoke temp threshold set to: %s°C", temperature)

    def set_high_smoke_duration_threshold(self, duration: int) -> None:
        """Set high smoke temperature duration threshold."""
        self._high_smoke_duration_threshold = duration
        _LOGGER.info("High smoke duration threshold set to: %s seconds", duration)

    def set_low_wood_temp_threshold(self, temperature: float) -> None:
        """Set low wood mode temperature threshold."""
        self._low_wood_temp_threshold = temperature
        _LOGGER.info("Low wood temp threshold set to: %s°C", temperature)

    def set_low_wood_duration_threshold(self, duration: int) -> None:
        """Set low wood mode temperature duration threshold."""
        self._low_wood_duration_threshold = duration
        _LOGGER.info("Low wood duration threshold set to: %s seconds", duration)

    def update_pellet_consumption(self, amount: float) -> None:
        """Update pellet consumption manually."""
        self._pellets_consumed = amount
        _LOGGER.debug("Pellet consumption updated to: %s kg", amount)

    # -------------------------------------------------------------------------
    # Control methods
    # -------------------------------------------------------------------------

    async def async_start_stove(self) -> bool:
        """Start the stove."""
        _LOGGER.info("Attempting to start stove")
        result = await self._async_send_command("misc.start", 1)
        if result:
            self._change_in_progress = True
            self._mode_change_started = datetime.now()
            _LOGGER.info("Start command sent successfully")
        else:
            _LOGGER.error("Failed to send start command to stove")
        return result

    async def async_stop_stove(self) -> bool:
        """Stop the stove."""
        _LOGGER.info("Attempting to stop stove")
        result = await self._async_send_command("misc.stop", 1)
        if result:
            self._change_in_progress = True
            self._mode_change_started = datetime.now()
            _LOGGER.info("Stop command sent successfully")
        else:
            _LOGGER.error("Failed to send stop command to stove")
        return result

    async def _async_resume_pellet_operation(self) -> bool:
        """Internal method to command the stove to auto-resume pellet operation after wood mode."""
        _LOGGER.info(
            "Commanding stove to auto-resume pellet operation - Mode: %s, Heatlevel: %s, Temperature: %s",
            #self._pre_wood_mode_operation_mode,
            #self._pre_wood_mode_heatlevel,
            #self._pre_wood_mode_temperature
        )
        
        # Send start command - this puts stove in waiting state during wood mode
        result = await self.async_start_stove()
        
        if not result:
            _LOGGER.error("Failed to send auto-resume start command")
            return False
        
        _LOGGER.info("Auto-resume start command sent successfully - stove will resume when suitable")
        
        # Wait a moment then restore the operation mode and settings
        await asyncio.sleep(3)
        
        # Restore previous operation mode and settings
        if self._pre_wood_mode_operation_mode == 0 and self._pre_wood_mode_heatlevel is not None:
            _LOGGER.info("Setting heatlevel mode with level: %s", self._pre_wood_mode_heatlevel)
            await self.async_set_heatlevel(self._pre_wood_mode_heatlevel)
        elif self._pre_wood_mode_operation_mode == 1 and self._pre_wood_mode_temperature is not None:
            _LOGGER.info("Setting temperature mode with temp: %s", self._pre_wood_mode_temperature)
            await self.async_set_temperature(self._pre_wood_mode_temperature)
        else:
            _LOGGER.warning("No previous settings to restore, using defaults")
        
        return True

    async def async_resume_after_wood_mode(self) -> bool:
        """Resume pellet operation after wood mode (state 9 or 14)."""
        if not self.data or "operating" not in self.data:
            _LOGGER.error("No data available to resume after wood mode")
            return False
        
        current_state = self.data["operating"].get("state")
        
        # Check if stove is in wood mode (state 9 or 14)
        if current_state not in ["9", "14"]:
            _LOGGER.warning(
                "Cannot resume - stove not in wood mode (current state: %s)",
                current_state
            )
            return False
        
        _LOGGER.info("Manual resume requested from wood mode (state: %s)", current_state)
        return await self._async_resume_pellet_operation()

    async def async_set_heatlevel(self, heatlevel: int) -> bool:
        """Set the heat level (1-3)."""
        if heatlevel not in [1, 2, 3]:
            _LOGGER.error("Invalid heatlevel: %s (must be 1, 2, or 3)", heatlevel)
            return False
        
        _LOGGER.info("Setting heatlevel to: %s (power: %s%%)", heatlevel, POWER_HEAT_LEVEL_MAP[heatlevel])
        
        # Set targets
        self._target_heatlevel = heatlevel
        self._target_operation_mode = 0
        self._change_in_progress = True
        self._mode_change_started = datetime.now()
        self._resend_attempt = 0
        
        # STEP 1: Set mode FIRST
        _LOGGER.debug("Step 1: Setting operation mode to heatlevel (0)")
        mode_result = await self._async_send_command("regulation.operation_mode", 0)
        if not mode_result:
            _LOGGER.error("Failed to set operation mode")
            self._change_in_progress = False
            self._target_heatlevel = None
            self._target_operation_mode = None
            return False
        
        # Wait for mode change
        await asyncio.sleep(3)
        
        # STEP 2: Set heatlevel value
        _LOGGER.debug("Step 2: Setting heatlevel power to: %s%%", POWER_HEAT_LEVEL_MAP[heatlevel])
        fixed_power = POWER_HEAT_LEVEL_MAP[heatlevel]
        result = await self._async_send_command("regulation.fixed_power", fixed_power)
        
        if result:
            _LOGGER.info("Heatlevel commands sent, waiting for stove confirmation")
        else:
            _LOGGER.error("Failed to set heatlevel")
            self._change_in_progress = False
            self._target_heatlevel = None
            self._target_operation_mode = None
        
        return result

    async def async_set_temperature(self, temperature: float) -> bool:
        """Set the target temperature."""
        _LOGGER.info("Setting temperature to: %s°C", temperature)
        
        # Set targets
        self._target_temperature = temperature
        self._target_operation_mode = 1
        self._change_in_progress = True
        self._mode_change_started = datetime.now()
        self._resend_attempt = 0
        
        # STEP 1: Set mode FIRST
        _LOGGER.debug("Step 1: Setting operation mode to temperature (1)")
        mode_result = await self._async_send_command("regulation.operation_mode", 1)
        if not mode_result:
            _LOGGER.error("Failed to set operation mode")
            self._change_in_progress = False
            self._target_temperature = None
            self._target_operation_mode = None
            return False
        
        # Wait for mode change
        await asyncio.sleep(3)
        
        # STEP 2: Set temperature value
        _LOGGER.debug("Step 2: Setting temperature to: %s°C", temperature)
        result = await self._async_send_command("boiler.temp", temperature)
        
        if result:
            _LOGGER.info("Temperature commands sent, waiting for stove confirmation")
        else:
            _LOGGER.error("Failed to set temperature")
            self._change_in_progress = False
            self._target_temperature = None
            self._target_operation_mode = None
        
        return result

    async def async_set_operation_mode(self, mode: int) -> bool:
        """Set the operation mode (0=heatlevel, 1=temperature, 2=wood)."""
        if mode not in [0, 1, 2]:
            _LOGGER.error("Invalid operation mode: %s (must be 0, 1, or 2)", mode)
            return False
        
        mode_names = {0: "heatlevel", 1: "temperature", 2: "wood"}
        _LOGGER.info("Setting operation mode to: %s (%s)", mode, mode_names[mode])
        
        self._target_operation_mode = mode
        self._change_in_progress = True
        self._mode_change_started = datetime.now()
        self._resend_attempt = 0
        
        result = await self._async_send_command("regulation.operation_mode", mode)
        
        if result:
            _LOGGER.info("Operation mode set successfully")
        else:
            _LOGGER.error("Failed to set operation mode to %s", mode_names[mode])
        
        return result

    async def async_toggle_mode(self) -> bool:
        """Toggle between heatlevel and temperature modes."""
        if not self.data or "status" not in self.data:
            _LOGGER.error("No data available to toggle mode")
            return False
        
        current_mode = self.data["status"].get("operation_mode", 0)
        
        # Toggle between mode 0 (heatlevel) and mode 1 (temperature)
        new_mode = 1 if current_mode == 0 else 0
        mode_names = {0: "heatlevel", 1: "temperature"}
        
        _LOGGER.info("Toggling mode from %s to %s", mode_names.get(current_mode, current_mode), mode_names[new_mode])
        
        self._toggle_heat_target = True
        self._change_in_progress = True
        self._mode_change_started = datetime.now()
        self._resend_attempt = 0
        self._target_operation_mode = new_mode
        
        result = await self._async_send_command("regulation.operation_mode", new_mode)
        
        if not result:
            _LOGGER.error("Failed to toggle mode")
            return False
        
        # If switching to heatlevel mode, ensure we have a target heatlevel
        if new_mode == 0:
            if self.data and "operating" in self.data:
                current_heatlevel = self.data["operating"].get("heatlevel", 2)
                self._target_heatlevel = current_heatlevel
                _LOGGER.debug("Target heatlevel set to: %s", current_heatlevel)
        
        # If switching to temperature mode, ensure we have a target temperature
        if new_mode == 1:
            if self.data and "operating" in self.data:
                current_temp = self.data["operating"].get("boiler_ref", 20)
                self._target_temperature = current_temp
                _LOGGER.debug("Target temperature set to: %s°C", current_temp)
        
        _LOGGER.info("Mode toggle successful")
        return result

    async def async_force_auger(self) -> bool:
        """Force the auger to run."""
        _LOGGER.info("Forcing auger to run")
        result = await self._async_send_command("auger.forced_run", 1)
        if result:
            _LOGGER.info("Auger forced successfully")
        else:
            _LOGGER.error("Failed to force auger")
        return result

    async def async_set_custom(self, path: str, value: Any) -> bool:
        """Set a custom parameter."""
        _LOGGER.info("Setting custom parameter: %s = %s", path, value)
        result = await self._async_send_command(path, value)
        if result:
            _LOGGER.info("Custom parameter set successfully")
        else:
            _LOGGER.error("Failed to set custom parameter: %s", path)
        return result

    async def _async_send_command(
        self, path: str, value: Any, retries: int = 3
    ) -> bool:
        """Send a command to the stove with retry logic."""
        for attempt in range(retries):
            try:
                response = await self.hass.async_add_executor_job(
                    set.run,
                    self.stove_ip,
                    self.serial,
                    self.pin,
                    path,
                    value
                )
                
                data = response.parse_payload()
                
                if data == "":
                    _LOGGER.info("Command sent successfully: %s = %s", path, value)
                    # Enable fast polling to catch the change
                    self.trigger_fast_polling()
                    # Request immediate update
                    await self.async_request_refresh()
                    return True
                else:
                    _LOGGER.warning(
                        "Command response not empty: %s = %s, response: %s",
                        path, value, data
                    )
                    
            except Exception as err:
                _LOGGER.warning(
                    "Command attempt %d/%d failed: %s",
                    attempt + 1, retries, err
                )
                
                if attempt < retries - 1:
                    await asyncio.sleep(1)
                    # Try to rediscover on failure
                    await self._async_discover_stove()
        
        _LOGGER.error("Command failed after %d attempts: %s = %s", retries, path, value)
        return False


    async def _check_temperature_alerts(self, data: dict[str, Any]) -> None:
        """Check for temperature alert conditions."""
        if "operating" not in data:
            return
        
        smoke_temp = data["operating"].get("smoke_temp", 0)
        current_state = data["operating"].get("state")
        is_in_wood_mode = current_state in ["9"]
        
        # Initialize alerts dict if not present
        if "alerts" not in data:
            data["alerts"] = {}
        
        # =========================================================================
        # HIGH SMOKE TEMPERATURE ALERT
        # =========================================================================
        
        if smoke_temp >= self._high_smoke_temp_threshold:
            if self._high_smoke_temp_start_time is None:
                self._high_smoke_temp_start_time = datetime.now()
                _LOGGER.info(
                    "High smoke temperature detected: %.1f°C (threshold: %.1f°C)",
                    smoke_temp,
                    self._high_smoke_temp_threshold
                )
            
            # Check if threshold duration has been exceeded
            try:
                elapsed = (datetime.now() - self._high_smoke_temp_start_time).total_seconds()
                if elapsed >= self._high_smoke_duration_threshold:
                    if not self._high_smoke_alert_sent:
                        _LOGGER.warning(
                            "HIGH SMOKE TEMPERATURE ALERT: %.1f°C for %d seconds (threshold: %.1f°C for %d seconds)",
                            smoke_temp,
                            int(elapsed),
                            self._high_smoke_temp_threshold,
                            self._high_smoke_duration_threshold
                        )
                        self._high_smoke_alert_active = True
                        self._high_smoke_alert_sent = True
                        data["alerts"]["high_smoke_temp_triggered"] = True
                    else:
                        self._high_smoke_alert_active = True
            except (TypeError, AttributeError) as err:
                _LOGGER.debug("Error calculating high smoke temp duration: %s", err)
                self._high_smoke_temp_start_time = datetime.now()
        else:
            # Temperature dropped below threshold
            if self._high_smoke_temp_start_time is not None:
                _LOGGER.debug("Smoke temperature returned to normal: %.1f°C", smoke_temp)
            self._high_smoke_temp_start_time = None
            self._high_smoke_alert_active = False
            # Reset alert flag only when temp drops significantly below threshold (hysteresis)
            if smoke_temp < (self._high_smoke_temp_threshold - 20):
                if self._high_smoke_alert_sent:
                    _LOGGER.info("High smoke temperature alert cleared (temp: %.1f°C)", smoke_temp)
                self._high_smoke_alert_sent = False
        
        # =========================================================================
        # LOW WOOD MODE TEMPERATURE ALERT
        # =========================================================================
        
        if is_in_wood_mode:
            if smoke_temp <= self._low_wood_temp_threshold:
                if self._low_wood_temp_start_time is None:
                    self._low_wood_temp_start_time = datetime.now()
                    _LOGGER.info(
                        "Low wood mode temperature detected: %.1f°C (threshold: %.1f°C)",
                        smoke_temp,
                        self._low_wood_temp_threshold
                    )
                
                # Check if threshold duration has been exceeded
                try:
                    elapsed = (datetime.now() - self._low_wood_temp_start_time).total_seconds()
                    if elapsed >= self._low_wood_duration_threshold:
                        if not self._low_wood_alert_sent:
                            _LOGGER.warning(
                                "LOW WOOD MODE TEMPERATURE ALERT: %.1f°C for %d seconds (threshold: %.1f°C for %d seconds)",
                                smoke_temp,
                                int(elapsed),
                                self._low_wood_temp_threshold,
                                self._low_wood_duration_threshold
                            )
                            self._low_wood_alert_active = True
                            self._low_wood_alert_sent = True
                            data["alerts"]["low_wood_temp_triggered"] = True
                        else:
                            self._low_wood_alert_active = True
                except (TypeError, AttributeError) as err:
                    _LOGGER.debug("Error calculating low wood temp duration: %s", err)
                    self._low_wood_temp_start_time = datetime.now()
            else:
                # Temperature rose above threshold
                if self._low_wood_temp_start_time is not None:
                    _LOGGER.debug("Wood mode temperature returned to normal: %.1f°C", smoke_temp)
                self._low_wood_temp_start_time = None
                self._low_wood_alert_active = False
                # Reset alert flag only when temp rises significantly above threshold (hysteresis)
                if smoke_temp > (self._low_wood_temp_threshold + 10):
                    if self._low_wood_alert_sent:
                        _LOGGER.info("Low wood temperature alert cleared (temp: %.1f°C)", smoke_temp)
                    self._low_wood_alert_sent = False
        else:
            # Not in wood mode - reset tracking
            if self._low_wood_temp_start_time is not None:
                _LOGGER.debug("Exited wood mode, resetting low temp alert tracking")
            self._low_wood_temp_start_time = None
            self._low_wood_alert_active = False
            # Keep alert flag until temp rises or manually acknowledged
        
        # =========================================================================
        # BUILD ALERT DATA FOR SENSORS
        # =========================================================================
        
        # Calculate time information for high smoke temp
        high_smoke_time_info = None
        if self._high_smoke_temp_start_time is not None:
            try:
                elapsed = (datetime.now() - self._high_smoke_temp_start_time).total_seconds()
                if elapsed < self._high_smoke_duration_threshold:
                    high_smoke_time_info = {
                        "state": "building",
                        "elapsed": int(elapsed),
                        "remaining": int(self._high_smoke_duration_threshold - elapsed),
                    }
                else:
                    high_smoke_time_info = {
                        "state": "exceeded",
                        "elapsed": int(elapsed),
                        "exceeded_by": int(elapsed - self._high_smoke_duration_threshold),
                    }
            except (TypeError, AttributeError):
                pass
        
        # Calculate time information for low wood temp
        low_wood_time_info = None
        if self._low_wood_temp_start_time is not None:
            try:
                elapsed = (datetime.now() - self._low_wood_temp_start_time).total_seconds()
                if elapsed < self._low_wood_duration_threshold:
                    low_wood_time_info = {
                        "state": "building",
                        "elapsed": int(elapsed),
                        "remaining": int(self._low_wood_duration_threshold - elapsed),
                    }
                else:
                    low_wood_time_info = {
                        "state": "exceeded",
                        "elapsed": int(elapsed),
                        "exceeded_by": int(elapsed - self._low_wood_duration_threshold),
                    }
            except (TypeError, AttributeError):
                pass
        
        # Store alert data
        data["alerts"]["high_smoke_temp_alert"] = {
            "active": self._high_smoke_alert_active,
            "current_temp": smoke_temp,
            "threshold_temp": self._high_smoke_temp_threshold,
            "threshold_duration": self._high_smoke_duration_threshold,
            "time_info": high_smoke_time_info,
        }
        
        data["alerts"]["low_wood_temp_alert"] = {
            "active": self._low_wood_alert_active,
            "current_temp": smoke_temp,
            "threshold_temp": self._low_wood_temp_threshold,
            "threshold_duration": self._low_wood_duration_threshold,
            "in_wood_mode": is_in_wood_mode,
            "time_info": low_wood_time_info,
        }
