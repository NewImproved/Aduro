"""Coordinator for Aduro Hybrid Stove integration."""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, date
import datetime as dt_module
import logging
from typing import Any
import math

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
    CONF_EXTERNAL_TEMP_SENSOR,
    CONF_WEATHER_FORECAST_SENSOR,
    DEFAULT_SCAN_INTERVAL,
    UPDATE_INTERVAL_FAST,
    UPDATE_INTERVAL_NORMAL,
    UPDATE_COUNT_AFTER_COMMAND,
    POWER_HEAT_LEVEL_MAP,
    HEAT_LEVEL_POWER_MAP,
    TIMER_STARTUP_1,
    TIMER_STARTUP_2,
    TIMER_SHUTDOWN,
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
        self._pellets_consumed = 0.0  # kg - accumulated since last refill
        self._pellets_consumed_total = 0.0  # kg - accumulated since last cleaning
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

        # Auto-resume tracking
        self._auto_resume_sent = False  # Prevents multiple resume commands

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

        # Pellet depletion prediction tracking
        self._last_prediction_time = None
        self._last_prediction_log = None
        self._prediction_change_threshold_seconds = 1800  # 30 minutes

        # Learning system for pellet depletion prediction
        self._learning_data = {
            "heating_observations": {},  # (heatlevel, temp_delta, outdoor) -> heating_rate only
            "cooling_observations": {},
            "consumption_observations": {  # NEW: heatlevel -> consumption_rate
                1: {
                    "count": 0,
                    "total_consumption_rate": 0.0,
                    "avg_consumption_rate": 0.35,  # Default kg/h
                },
                2: {
                    "count": 0,
                    "total_consumption_rate": 0.0,
                    "avg_consumption_rate": 0.75,  # Default kg/h
                },
                3: {
                    "count": 0,
                    "total_consumption_rate": 0.0,
                    "avg_consumption_rate": 1.2,  # Default kg/h
                },
            },
            "startup_observations": {
                "count": 0,
                "total_consumption": 0.0,
                "avg_consumption": 0.15,  # Default: 150g per startup
                "avg_duration": 360,      # Default: 6 minutes
            },
            "shutdown_restart_deltas": {
                "shutdown": {
                    "count": 0,
                    "total_delta": 0.0,
                    "avg_delta": 1.1,  # Default: target + 1.1°C
                },
                "restart": {
                    "count": 0,
                    "total_delta": 0.0,
                    "avg_delta": 0.6,  # Default: target - 0.6°C
                }
            }
        }
        
        # Learning consumption tracker (separate from pellet refill counter)
        self._learning_consumption_total = 0.0  # Total kg consumed during all learning sessions
        self._last_consumption_day_for_learning = None  # Last known consumption_day value

        # Current session tracking for learning
        self._current_heating_session = None  # Tracks current stable heating period
        self._current_cooling_session = None  # Tracks current cooling/waiting period
        self._current_startup_session = None  # Tracks startup consumption (states 2→4→32→5)
        self._last_learning_state = None
        self._last_learning_heatlevel = None
        self._last_learning_room_temp = None
        self._last_learning_timestamp = None
        
        # External temperature sensor configuration
        self._external_temp_sensor = entry.data.get(CONF_EXTERNAL_TEMP_SENSOR)
        self._external_temp_value = None

        # Weather forecast sensor configuration
        self._weather_forecast_sensor = entry.data.get(CONF_WEATHER_FORECAST_SENSOR)

        # Weather forecast cache
        self._forecast_data: list[dict[str, Any]] = []
        self._forecast_last_updated: datetime | None = None
        self._forecast_update_interval = timedelta(hours=1)

        # Timer tracking
        self._timer_startup_1_started: datetime | None = None
        self._timer_startup_2_started: datetime | None = None
        self._timer_shutdown_started: datetime | None = None
        
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

    async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
        """Set up Aduro from a config entry."""
        coordinator = AduroCoordinator(hass, entry)
        
        # Load saved pellet data (including switch states)
        await coordinator.async_load_pellet_data()
        
        # Pre-populate coordinator.data with loaded settings so switches can read them immediately
        coordinator.data = {
            "pellets": {
                "capacity": coordinator._pellet_capacity,
                "consumed": coordinator._pellets_consumed,
                "consumed_total": coordinator._pellets_consumed_total,
                "amount": max(0, coordinator._pellet_capacity - coordinator._pellets_consumed),
                "percentage": ((max(0, coordinator._pellet_capacity - coordinator._pellets_consumed) / coordinator._pellet_capacity * 100) if coordinator._pellet_capacity > 0 else 0),
                "notification_level": coordinator._notification_level,
                "shutdown_level": coordinator._shutdown_level,
                "auto_shutdown_enabled": coordinator._auto_shutdown_enabled,
            }
        }
        
        # Initial data fetch
        await coordinator.async_config_entry_first_refresh()
        
        hass.data.setdefault(DOMAIN, {})
        hass.data[DOMAIN][entry.entry_id] = coordinator


    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the stove."""
        try:
            _LOGGER.debug("Starting data update cycle")
            
            # Discover stove IP if not known or too old
            if self.stove_ip is None or self._should_rediscover():
                _LOGGER.debug("Attempting stove discovery")
                await self._async_discover_stove()
            
            # Update weather forecast if needed (once per hour)
            await self._async_update_forecast_cache()
            
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

            # Track state changes for learning
            _LOGGER.debug("Tracking learning state changes")
            self._track_learning_state_changes(data)

            # Update learning consumption tracker
            self._update_learning_consumption_tracker(data)

            # Add calculated/derived data
            _LOGGER.debug("Adding calculated data")
            self._add_calculated_data(data)
            
            # Manage polling interval
            self._manage_polling_interval()

            if not hasattr(self, '_last_pellet_save'):
                self._last_pellet_save = datetime.now()

            if (datetime.now() - self._last_pellet_save) > timedelta(minutes=15):
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
        current_substate = data["operating"].get("substate")
        current_heatlevel = data["operating"].get("heatlevel")
        current_operation_mode = data["status"].get("operation_mode")
        current_temperature_ref = data["operating"].get("boiler_ref")
        smoke_temp = data["operating"].get("smoke_temp", 0)
        
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
        
        # Entering wood mode - ONLY save settings, don't resume yet
        if is_in_wood_mode and not self._was_in_wood_mode:
            _LOGGER.info("Entering wood mode (state: %s), saving pellet mode settings", current_state)
            self._pre_wood_mode_operation_mode = current_operation_mode
            self._pre_wood_mode_heatlevel = current_heatlevel
            self._pre_wood_mode_temperature = current_temperature_ref
            self._was_in_wood_mode = True
            self._auto_resume_sent = False  # Reset flag when entering wood mode
            
            # Log that we'll monitor for auto-resume
            if self._auto_resume_after_wood and current_operation_mode == 0:
                _LOGGER.info(
                    "Auto-resume enabled (heat level mode) - will monitor smoke temp to resume when fire is dying (threshold: 110°C)"
                )
        
        # WHILE in wood mode - check if we should auto-resume (fire is dying)
        elif is_in_wood_mode and self._was_in_wood_mode:
            # Only auto-resume in heat level mode (temperature mode does it automatically)
            if (self._auto_resume_after_wood and 
                self._pre_wood_mode_operation_mode == 0 and 
                smoke_temp <= 110 and
                not self._auto_resume_sent):  # Only if we haven't sent it yet
                
                _LOGGER.info(
                    "Fire is dying (smoke temp: %.1f°C <= 110°C), sending auto-resume command",
                    smoke_temp
                )
                success = await self._async_resume_pellet_operation()
                if success:
                    data["auto_resume_commanded"] = True
                    self._auto_resume_sent = True  # Prevent re-triggering
                else:
                    _LOGGER.error("Failed to send auto-resume command")
        
        # Exiting wood mode - clear flags
        if not is_in_wood_mode and self._was_in_wood_mode:
            _LOGGER.info("Exiting wood mode, was in state: %s", self._previous_state)
            self._was_in_wood_mode = False
            self._auto_resume_sent = False  # Reset for next wood mode session

        # Start timers based on state
        if current_state == "2" and self._previous_state != "2":
            self._timer_startup_1_started = datetime.now()
            _LOGGER.debug("Started startup timer 1")
        
        if current_state == "4" and self._previous_state != "4":
            self._timer_startup_2_started = datetime.now()
            _LOGGER.debug("Started startup timer 2")

        if (current_state == "14" and current_substate == "0" and 
            self._previous_state in ("5", "32")):
            self._timer_shutdown_started = datetime.now()
            _LOGGER.debug("Started shutdown timer")
        
        if current_state != "14" and self._timer_shutdown_started is not None:
            self._timer_shutdown_started = None
            _LOGGER.debug("Cleared shutdown timer - state changed away from 14")

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
        
        # Only check for external changes when NOT in progress
        if not self._change_in_progress:
            # Always check for changes and update targets, but only flag as "app_change" when not in progress
            if current_operation_mode == 0:  # Heatlevel mode
                if (self._previous_heatlevel is not None and 
                    current_heatlevel != self._previous_heatlevel):
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
                    app_change_detected = True
                    _LOGGER.info("External temperature change detected: %s -> %s", 
                            self._previous_temperature, current_temperature_ref)
                    # Always update our target to match current value
                    self._target_temperature = current_temperature_ref
            
            # Detect operation mode changes
            if (self._previous_operation_mode is not None and 
                current_operation_mode != self._previous_operation_mode):
                app_change_detected = True
                _LOGGER.info("External operation mode change detected: %s -> %s",
                        self._previous_operation_mode, current_operation_mode)
                self._target_operation_mode = current_operation_mode
        else:
            # When change is in progress, don't flag as app change but DO log it
            _LOGGER.debug("Change in progress, not flagging value changes as external")
        
        # Auto turn on when stove starts
        if (self._previous_state is not None and 
            current_state in STARTUP_STATES and 
            self._previous_state not in STARTUP_STATES):
            _LOGGER.info("Stove started, state: %s", current_state)
            data["auto_start_detected"] = True

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

        _LOGGER.debug(
            "Change in progress - Target HL: %s, Target Temp: %s, Target Mode: %s",
            self._target_heatlevel,
            self._target_temperature,
            self._target_operation_mode
        )
        
        if "operating" not in data or "status" not in data:
            return
        
        current_state = data["operating"].get("state")
        current_heatlevel = data["operating"].get("heatlevel")
        current_temperature_ref = data["operating"].get("boiler_ref")
        current_operation_mode = data["status"].get("operation_mode")
        
        
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
        
        # Shutdown timer
        if self._timer_shutdown_started:
            try:
                elapsed = (datetime.now() - self._timer_shutdown_started).total_seconds()
                remaining = max(0, TIMER_SHUTDOWN - int(elapsed))
                timers["shutdown_remaining"] = remaining
                
                if remaining == 0:
                    self._timer_shutdown_started = None
            except (TypeError, AttributeError) as err:
                _LOGGER.debug("Error calculating shutdown timer: %s", err)
                timers["shutdown_remaining"] = 0
                self._timer_shutdown_started = None
        else:
            timers["shutdown_remaining"] = 0
            
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
            # Update baseline to new (reset) value, don't change counters
            self._last_consumption_day_value = current_day_consumption
            
        # Handle normal consumption increase
        elif consumption_change > 0:
            # Add the increment to BOTH counters
            self._pellets_consumed += consumption_change
            self._pellets_consumed_total += consumption_change
            self._last_consumption_day_value = current_day_consumption
            
            _LOGGER.debug(
                "Consumption increment: +%.2f kg (since refill: %.2f kg, since cleaning: %.2f kg, today: %.2f kg)",
                consumption_change,
                self._pellets_consumed,
                self._pellets_consumed_total,
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
            "consumed_total": self._pellets_consumed_total,  # NEW: Total since cleaning
            "amount": amount_remaining,
            "percentage": percentage_remaining,
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
        
        if self._target_operation_mode is not None and not mode_match:
            # We're actively changing between heatlevel/temperature/wood modes
            mode_transition = "mode_changing"
        elif self._toggle_heat_target:
            # Special case: toggle between modes is starting
            mode_transition = "mode_toggling"
        elif current_operation_mode == 0 and self._target_heatlevel is not None and not heatlevel_match:
            # In heatlevel mode, adjusting the level
            mode_transition = "heatlevel_adjusting"
        elif current_operation_mode == 1 and self._target_temperature is not None and not temp_match:
            # In temperature mode, adjusting the temperature
            mode_transition = "temperature_adjusting"
        else:
            # No changes in progress
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
        
        data["calculated"] = {
            "heatlevel_match": heatlevel_match,
            "temperature_match": temp_match,
            "operation_mode_match": mode_match,
            "change_in_progress": self._change_in_progress,  # This is the key value for AduroChangeInProgressSensor
            "toggle_heat_target": self._toggle_heat_target,
            "mode_transition": mode_transition,  # This is the key value for AduroModeTransitionSensor
            "display_target": display_target,
            "display_target_type": display_target_type,
            "current_temperature": current_temperature,
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
                self._pellets_consumed_total = data.get("pellets_consumed_total", 0.0)
                self._consumption_snapshots = data.get("consumption_snapshots", {})
                self._snapshots_initialized = data.get("snapshots_initialized", False)
                
                # Load user preferences (switches)
                self._auto_resume_after_wood = data.get("auto_resume_after_wood", False)
                self._auto_shutdown_enabled = data.get("auto_shutdown_enabled", False)
                
                # Load user settings (numbers)
                self._pellet_capacity = data.get("pellet_capacity", 9.5)
                self._notification_level = data.get("notification_level", 10)
                self._shutdown_level = data.get("shutdown_level", 5)
                self._high_smoke_temp_threshold = data.get("high_smoke_temp_threshold", 370.0)
                self._high_smoke_duration_threshold = data.get("high_smoke_duration_threshold", 30)
                self._low_wood_temp_threshold = data.get("low_wood_temp_threshold", 175.0)
                self._low_wood_duration_threshold = data.get("low_wood_duration_threshold", 300)

                # Load learning data (convert string keys back to tuples)
                _LOGGER.info("=== Starting to load learning data ===")
                
                loaded_learning_data = data.get("learning_data", {
                    "heating_observations": {},
                    "cooling_observations": {},
                    "startup_observations": {
                        "count": 0,
                        "total_consumption": 0.0,
                        "avg_consumption": 0.15,
                        "avg_duration": 360,
                    },
                    "shutdown_restart_deltas": {}
                })
                
                
                _LOGGER.info("Found %d heating observations in file", 
                           len(loaded_learning_data.get("heating_observations", {})))
                _LOGGER.info("Found %d cooling observations in file", 
                           len(loaded_learning_data.get("cooling_observations", {})))
                
                # Convert heating observations string keys back to tuples
                heating_obs = {}
                for key_str, value in loaded_learning_data.get("heating_observations", {}).items():
                    _LOGGER.debug("Processing heating obs key: %s", key_str)
                    try:
                        # Parse string like "(1, 2.0, -4)" back to tuple (1, 2.0, -4)
                        key_tuple = eval(key_str)
                        _LOGGER.debug("Parsed key to tuple: %s", key_tuple)
                        
                        if isinstance(key_tuple, tuple):
                            # Convert last_updated string back to datetime object
                            if "last_updated" in value and isinstance(value["last_updated"], str):
                                try:
                                    value["last_updated"] = dt_module.datetime.fromisoformat(value["last_updated"])
                                    _LOGGER.debug("Converted last_updated to datetime")
                                except (ValueError, TypeError) as e:
                                    _LOGGER.warning("Failed to parse datetime: %s", e)
                                    value["last_updated"] = dt_module.datetime.now()
                            heating_obs[key_tuple] = value
                            _LOGGER.debug("Successfully added heating obs: count=%d", value.get("count", 0))
                        else:
                            _LOGGER.warning("Key is not a tuple: %s (type: %s)", key_tuple, type(key_tuple))
                    except Exception as err:
                        _LOGGER.error("Failed to parse heating observation key '%s': %s", key_str, err, exc_info=True)
                
                # Convert cooling observations string keys back to tuples
                cooling_obs = {}
                for key_str, value in loaded_learning_data.get("cooling_observations", {}).items():
                    try:
                        key_tuple = eval(key_str)
                        if isinstance(key_tuple, tuple):
                            # Convert last_updated string back to datetime object
                            if "last_updated" in value and isinstance(value["last_updated"], str):
                                try:
                                    value["last_updated"] = dt_module.datetime.fromisoformat(value["last_updated"])
                                except (ValueError, TypeError):
                                    value["last_updated"] = dt_module.datetime.now()
                            cooling_obs[key_tuple] = value
                    except Exception as err:
                        _LOGGER.error("Failed to parse cooling observation key '%s': %s", key_str, err, exc_info=True)

                # Handle shutdown_restart_deltas
                loaded_deltas = loaded_learning_data.get("shutdown_restart_deltas", {})
                
                # Check if there is saved data
                if "shutdown" in loaded_deltas:
                    # New format - use as-is
                    shutdown_restart_deltas = loaded_deltas
                    _LOGGER.debug("Loaded shutdown_restart_deltas")
                else:
                    # No data - use defaults
                    shutdown_restart_deltas = {
                        "shutdown": {
                            "count": 0,
                            "total_delta": 0.0,
                            "avg_delta": 1.1,
                        },
                        "restart": {
                            "count": 0,
                            "total_delta": 0.0,
                            "avg_delta": 0.6,
                        }
                    }
                    _LOGGER.debug("No shutdown_restart_deltas found, using defaults")
                
                # Load consumption observations
                loaded_consumption = loaded_learning_data.get("consumption_observations", {})
                
                # Ensure all heatlevels exist with proper structure
                # Note: JSON saves integer keys as strings, so check both
                consumption_obs = {}
                for hl in [1, 2, 3]:
                    # Try both integer and string keys
                    loaded_obs = loaded_consumption.get(hl) or loaded_consumption.get(str(hl))
                    
                    if loaded_obs and isinstance(loaded_obs, dict):
                        # Use loaded data (convert to integer key)
                        consumption_obs[hl] = loaded_obs
                    else:
                        # Initialize with defaults
                        consumption_obs[hl] = {
                            "count": 0,
                            "total_consumption_rate": 0.0,
                            "avg_consumption_rate": {1: 0.35, 2: 0.75, 3: 1.2}[hl],
                        }
                
                self._learning_data = {
                    "heating_observations": heating_obs,
                    "cooling_observations": cooling_obs,
                    "consumption_observations": consumption_obs,
                    "startup_observations": loaded_learning_data.get("startup_observations", {
                        "count": 0,
                        "total_consumption_rate": 0.0,
                        "avg_consumption": 0.15,
                        "avg_duration": 360,
                    }),
                    "shutdown_restart_deltas": shutdown_restart_deltas
                }
                
                _LOGGER.info(
                    "=== Loaded learning data: %d heating obs, %d cooling obs, consumption HL1=%d HL2=%d HL3=%d ===",
                    len(self._learning_data["heating_observations"]),
                    len(self._learning_data["cooling_observations"]),
                    consumption_obs[1]["count"],
                    consumption_obs[2]["count"],
                    consumption_obs[3]["count"]
                )

                _LOGGER.info(
                    "Loaded startup observations: count=%d, avg_consumption=%.3f kg, avg_duration=%d sec",
                    self._learning_data["startup_observations"]["count"],
                    self._learning_data["startup_observations"]["avg_consumption"],
                    self._learning_data["startup_observations"]["avg_duration"]
                )

                _LOGGER.info(
                    "Loaded shutdown/restart deltas: shutdown (count=%d, avg=%.2f°C), restart (count=%d, avg=%.2f°C)",
                    self._learning_data["shutdown_restart_deltas"]["shutdown"]["count"],
                    self._learning_data["shutdown_restart_deltas"]["shutdown"]["avg_delta"],
                    self._learning_data["shutdown_restart_deltas"]["restart"]["count"],
                    self._learning_data["shutdown_restart_deltas"]["restart"]["avg_delta"]
                )
                
                # Log consumption observations
                for hl in [1, 2, 3]:
                    cons_obs = self._learning_data["consumption_observations"].get(hl, {})
                    _LOGGER.info(
                        "Loaded consumption HL%d: count=%d, avg=%.3f kg/h",
                        hl,
                        cons_obs.get("count", 0),
                        cons_obs.get("avg_consumption_rate", 0)
                    )

                # Load external temperature sensor config
                self._external_temp_sensor = data.get("external_temp_sensor")

                # Load weather forecast sensor config
                self._weather_forecast_sensor = data.get("weather_forecast_sensor")

                # Load learning consumption tracker
                self._learning_consumption_total = data.get("learning_consumption_total", 0.0)
                self._last_consumption_day_for_learning = data.get("last_consumption_day_for_learning")

                _LOGGER.info(
                    "Loaded learning data: %d heating observations, %d cooling observations",
                    len(self._learning_data.get("heating_observations", {})),
                    len(self._learning_data.get("cooling_observations", {}))
                )

                _LOGGER.info(
                    "Loaded learning consumption tracker: %.3f kg total",
                    self._learning_consumption_total
                )

                # Debug: Log first few observations
                for key, obs in list(self._learning_data["heating_observations"].items())[:3]:
                    _LOGGER.info("Sample heating obs: key=%s, count=%d, heating_rate=%.2f", 
                                key, obs.get("count", 0), obs.get("avg_heating_rate", 0))

                # Convert last_consumption_day string back to date object
                last_day_str = data.get("last_consumption_day")
                if last_day_str:
                    from datetime import datetime
                    self._last_consumption_day = datetime.fromisoformat(last_day_str).date()
                
                _LOGGER.info(
                    "Loaded pellet data from storage - consumed: %.2f kg, total consumed: %.2f kg, "
                    "auto_resume: %s, auto_shutdown: %s, capacity: %.1f kg, "
                    "notification_level: %.0f%%, shutdown_level: %.0f%%",
                    self._pellets_consumed,
                    self._pellets_consumed_total,
                    self._auto_resume_after_wood,
                    self._auto_shutdown_enabled,
                    self._pellet_capacity,
                    self._notification_level,
                    self._shutdown_level
                )
            else:
                _LOGGER.debug("No stored pellet data found, starting fresh")
        except Exception as err:
            _LOGGER.warning("Failed to load pellet data from storage: %s", err)

    def _get_temp_delta_bucket(self, temp_delta: float) -> float:
        """Get temperature delta bucket (0.5°C increments)."""
        return round(temp_delta * 2) / 2  # Rounds to nearest 0.5
    
    def _get_outdoor_temp_bucket(self, outdoor_temp: float) -> int:
        """Get outdoor temperature bucket (2°C increments)."""
        return int(math.floor(outdoor_temp / 2) * 2)  # Rounds down to nearest 2
    
    def _get_external_temperature(self) -> float | None:
        """Get current external temperature from configured sensor."""
        if not self._external_temp_sensor:
            return None
        
        try:
            state = self.hass.states.get(self._external_temp_sensor)
            if state and state.state not in ('unknown', 'unavailable'):
                return float(state.state)
        except (ValueError, TypeError) as err:
            _LOGGER.debug("Failed to get external temperature: %s", err)
        
        return None

    def _get_forecast_temp_at_time(
        self, 
        forecast_data: list[dict], 
        target_time: datetime
    ) -> float | None:
        """
        Get forecasted temperature at a specific time.
        Uses the closest forecast entry within 1 hour.
        """
        if not forecast_data:
            return None
        
        # Find closest forecast entry
        closest = min(
            forecast_data, 
            key=lambda x: abs((x["datetime"] - target_time).total_seconds())
        )
        
        # Only use if within 1.5 hours (tolerance for hourly data)
        time_diff = abs((closest["datetime"] - target_time).total_seconds())
        if time_diff <= 5400:  # 1.5 hours in seconds
            return closest["temperature"]
        
        return None

    async def _async_update_forecast_cache(self) -> None:
            """Update the weather forecast cache if needed (once per hour)."""
            if not self._weather_forecast_sensor:
                return
            
            # Check if we need to update
            now = datetime.now()
            if (self._forecast_last_updated is not None and 
                (now - self._forecast_last_updated) < self._forecast_update_interval):
                # Cache is still fresh
                return
            
            _LOGGER.debug("Updating weather forecast cache from %s", self._weather_forecast_sensor)
            
            try:
                # Call the weather.get_forecasts service
                response = await self.hass.services.async_call(
                    "weather",
                    "get_forecasts",
                    {
                        "entity_id": self._weather_forecast_sensor,
                        "type": "hourly",
                    },
                    blocking=True,
                    return_response=True,
                )
                
                # Response format: {entity_id: {"forecast": [...]}}
                if not response or self._weather_forecast_sensor not in response:
                    _LOGGER.warning("No forecast data in response from %s", self._weather_forecast_sensor)
                    return
                
                forecast_data = response[self._weather_forecast_sensor]
                forecast = forecast_data.get("forecast", [])
                
                if not forecast:
                    _LOGGER.warning("Empty forecast from %s", self._weather_forecast_sensor)
                    return
                
                # Normalize forecast data
                normalized = []
                
                for i, entry in enumerate(forecast):
                    if "datetime" not in entry or "temperature" not in entry:
                        continue
                    
                    dt = entry["datetime"]
                    if isinstance(dt, str):
                        try:
                            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
                        except ValueError:
                            _LOGGER.debug("Could not parse datetime: %s", dt)
                            continue
                    
                    temp = entry.get("temperature")
                    if temp is None:
                        continue
                    
                    # Add to normalized list
                    normalized.append({
                        "datetime": dt.replace(tzinfo=None),
                        "temperature": temp,
                    })
                
                if normalized:
                    self._forecast_data = normalized
                    self._forecast_last_updated = now
                    
                    _LOGGER.info(
                        "Updated weather forecast cache: %d hourly entries from %s to %s",
                        len(normalized),
                        normalized[0]["datetime"].strftime("%Y-%m-%d %H:%M"),
                        normalized[-1]["datetime"].strftime("%Y-%m-%d %H:%M")
                    )
                else:
                    _LOGGER.warning("No valid forecast entries parsed from %s", self._weather_forecast_sensor)
                
            except Exception as err:
                _LOGGER.warning("Failed to update forecast cache from %s: %s", self._weather_forecast_sensor, err)

    def _record_heating_observation(
        self,
        heatlevel: int,
        duration_seconds: int,
        start_room_temp: float,
        end_room_temp: float,
        target_temp: float,
        consumption_kg: float,
    ) -> None:
        """Record a heating observation for learning."""
        temp_delta_start = target_temp - start_room_temp
        temp_delta_avg = target_temp - ((start_room_temp + end_room_temp) / 2)
        
        # Calculate rates
        duration_hours = duration_seconds / 3600
        heating_rate = (end_room_temp - start_room_temp) / duration_hours if duration_hours > 0 else 0
        consumption_rate = consumption_kg / duration_hours if duration_hours > 0 else 0
        
        # Get buckets
        temp_delta_bucket = self._get_temp_delta_bucket(temp_delta_avg)
        outdoor_temp = self._get_external_temperature()
        outdoor_bucket = self._get_outdoor_temp_bucket(outdoor_temp) if outdoor_temp is not None else None
        
        # === HEATING RATE OBSERVATION (keeps outdoor temp dependency) ===
        key = (heatlevel, temp_delta_bucket, outdoor_bucket)
        
        # Update or create observation
        if key not in self._learning_data["heating_observations"]:
            self._learning_data["heating_observations"][key] = {
                "count": 0,
                "total_heating_rate": 0.0,
                "avg_heating_rate": 0.0,
                "last_updated": datetime.now(),
            }
        
        obs = self._learning_data["heating_observations"][key]
        
        # Update running average for heating rate only
        obs["total_heating_rate"] += heating_rate
        obs["avg_heating_rate"] = obs["total_heating_rate"] / (obs["count"] + 1)
        obs["count"] += 1
        obs["last_updated"] = datetime.now()
        
        _LOGGER.info(
            "Recorded heating observation: HL=%d, temp_delta=%.1f°C, outdoor=%s°C, "
            "heating_rate=%.2f°C/h (count=%d)",
            heatlevel, temp_delta_bucket, outdoor_bucket, heating_rate, obs["count"]
        )
        
        # === CONSUMPTION RATE OBSERVATION (NO outdoor temp dependency) ===
        if heatlevel not in self._learning_data["consumption_observations"]:
            self._learning_data["consumption_observations"][heatlevel] = {
                "count": 0,
                "total_consumption_rate": 0.0,
                "avg_consumption_rate": {1: 0.35, 2: 0.75, 3: 1.2}.get(heatlevel, 0.75),
            }
        
        cons_obs = self._learning_data["consumption_observations"][heatlevel]
        
        # Update running average for consumption rate
        cons_obs["total_consumption_rate"] += consumption_rate
        cons_obs["avg_consumption_rate"] = cons_obs["total_consumption_rate"] / (cons_obs["count"] + 1)
        cons_obs["count"] += 1
        
        _LOGGER.info(
            "Recorded consumption observation: HL=%d, consumption_rate=%.3f kg/h (count=%d, avg=%.3f kg/h)",
            heatlevel, consumption_rate, cons_obs["count"], cons_obs["avg_consumption_rate"]
        )

        # Trigger immediate save
        asyncio.create_task(self.async_save_pellet_data())

    def _record_cooling_observation(
        self,
        duration_seconds: int,
        start_room_temp: float,
        end_room_temp: float,
        target_temp: float,
    ) -> None:
        """Record a cooling observation for learning."""
        duration_hours = duration_seconds / 3600
        cooling_rate = (start_room_temp - end_room_temp) / duration_hours if duration_hours > 0 else 0
        
        # Get outdoor bucket
        outdoor_temp = self._get_external_temperature()
        outdoor_bucket = self._get_outdoor_temp_bucket(outdoor_temp) if outdoor_temp is not None else None
        
        # Create key (outdoor temp and start temp)
        start_temp_bucket = int(math.floor(start_room_temp / 2) * 2)
        key = (outdoor_bucket, start_temp_bucket)
        
        # Update or create observation
        if key not in self._learning_data["cooling_observations"]:
            self._learning_data["cooling_observations"][key] = {
                "count": 0,
                "total_cooling_rate": 0.0,
                "avg_cooling_rate": 0.0,
                "last_updated": datetime.now(),
            }
        
        obs = self._learning_data["cooling_observations"][key]
        
        # Update running average
        obs["total_cooling_rate"] += cooling_rate
        obs["avg_cooling_rate"] = obs["total_cooling_rate"] / (obs["count"] + 1)
        obs["count"] += 1
        obs["last_updated"] = datetime.now()
        
        _LOGGER.info(
            "Recorded cooling observation: start_temp=%.1f°C, outdoor=%s°C, "
            "cooling_rate=%.2f°C/h (count=%d)",
            start_room_temp, outdoor_bucket, cooling_rate, obs["count"]
        )

        # Trigger immediate save
        asyncio.create_task(self.async_save_pellet_data())
    
    def _record_startup_observation(
        self,
        duration_seconds: int,
        consumption_kg: float,
    ) -> None:
        """Record a startup observation for learning."""
        startup = self._learning_data["startup_observations"]
        
        # Update running average
        startup["total_consumption"] += consumption_kg
        startup["avg_consumption"] = startup["total_consumption"] / (startup["count"] + 1)
        # Duration doesn't need total tracking, just update average
        startup["avg_duration"] = (
            (startup["avg_duration"] * startup["count"] + duration_seconds) / (startup["count"] + 1)
        )
        startup["count"] += 1
        
        _LOGGER.info(
            "Recorded startup observation: consumption=%.3f kg, duration=%d sec (count=%d, avg=%.3f kg)",
            consumption_kg,
            duration_seconds,
            startup["count"],
            startup["avg_consumption"]
        )
        
        # Trigger save
        asyncio.create_task(self.async_save_pellet_data())

    def _track_learning_state_changes(self, data: dict[str, Any]) -> None:
        """Track state changes for learning system."""
        if "operating" not in data or "status" not in data:
            return
        
        current_state = data["operating"].get("state")
        current_heatlevel = data["operating"].get("heatlevel")
        current_room_temp = data["operating"].get("boiler_temp")
        current_target_temp = data["operating"].get("boiler_ref")
        current_operation_mode = data["status"].get("operation_mode")
        current_time = datetime.now()
        
        # Track heating in both heat level mode (0) and temperature mode (1)
        # Track cooling only in temperature mode (1) when stove enters waiting
        if current_operation_mode not in [0, 1]:
            self._current_heating_session = None
            self._current_cooling_session = None
            self._last_learning_state = None
            return
        
        # Burning states
        is_actively_burning = current_state in ["5", "32"]  # Stable operation
        is_starting_up = current_state in ["2", "4"]        # Ignition/startup
        is_burning = is_actively_burning or is_starting_up  # Any burning state
        
        # Waiting/off state
        is_waiting = current_state == "6"

        # Startup tracking
        is_in_startup = current_state in ["2", "4", "32"]  # Startup sequence
        reached_stable = current_state == "5"  # Startup complete
        
        # === STARTUP SESSION TRACKING ===
        if is_in_startup:
            if self._current_startup_session is None:
                # Start new startup session
                self._current_startup_session = {
                    "start_time": current_time,
                    "start_learning_consumption": self._learning_consumption_total,
                }
                _LOGGER.info("Startup session started (state: %s)", current_state)
        
        # Startup complete - reached stable operation
        elif reached_stable and self._current_startup_session is not None:
            session = self._current_startup_session
            duration = (current_time - session["start_time"]).total_seconds()
            consumption = self._learning_consumption_total - session["start_learning_consumption"]
            
            # Only record if reasonable (duration > 60s, consumption > 0)
            if duration > 60 and consumption > 0:
                self._record_startup_observation(
                    duration_seconds=int(duration),
                    consumption_kg=consumption,
                )
                _LOGGER.info(
                    "Startup completed - duration: %.1f min, consumption: %.3f kg",
                    duration / 60,
                    consumption
                )
            else:
                _LOGGER.warning(
                    "Startup session invalid (duration: %.1fs, consumption: %.3f kg), not recording",
                    duration,
                    consumption
                )
            
            self._current_startup_session = None
        
        # Clear startup session if stove stops without completing startup
        elif not is_in_startup and not reached_stable and self._current_startup_session is not None:
            _LOGGER.debug("Startup session interrupted (state: %s)", current_state)
            self._current_startup_session = None

        # === HEATING SESSION TRACKING ===
        # Only track heating during stable operation, not startup
        if is_actively_burning:
            # Check if this is a new session or continuation
            if self._current_heating_session is None:
                # Start new heating session
                self._current_heating_session = {
                    "heatlevel": current_heatlevel,
                    "start_time": current_time,
                    "start_room_temp": current_room_temp,
                    "start_learning_consumption": self._learning_consumption_total,  # Use learning tracker
                    "target_temp": current_target_temp,
                    "stable_start_time": current_time,
                }
                _LOGGER.debug("Started new heating session at HL%d", current_heatlevel)
            
            # Check if heatlevel changed
            elif self._current_heating_session["heatlevel"] != current_heatlevel:
                # Record the previous stable period if it was >15 minutes
                session = self._current_heating_session
                stable_duration = (current_time - session["stable_start_time"]).total_seconds()
                
                if stable_duration >= 900:  # 15 minutes
                    # Record observation for the previous level
                    consumption_change = self._learning_consumption_total - session["start_learning_consumption"]
                    
                    self._record_heating_observation(
                        heatlevel=session["heatlevel"],
                        duration_seconds=int(stable_duration),
                        start_room_temp=session["start_room_temp"],
                        end_room_temp=current_room_temp,
                        target_temp=session["target_temp"],
                        consumption_kg=consumption_change,
                    )
                
                # Update session for new level
                self._current_heating_session = {
                    "heatlevel": current_heatlevel,
                    "start_time": current_time,
                    "start_room_temp": current_room_temp,
                    "start_learning_consumption": self._learning_consumption_total,
                    "target_temp": current_target_temp,
                    "stable_start_time": current_time,
                }
                _LOGGER.debug("Heat level changed to HL%d, started new stable period", current_heatlevel)
            
            # Check if we should record a periodic snapshot (every 30 minutes at same level)
            else:
                session = self._current_heating_session
                stable_duration = (current_time - session["stable_start_time"]).total_seconds()
                
                # Record every 30 minutes during stable operation
                if stable_duration >= 1800:  # 30 minutes
                    consumption_change = self._learning_consumption_total - session["start_learning_consumption"]
                    
                    self._record_heating_observation(
                        heatlevel=session["heatlevel"],
                        duration_seconds=int(stable_duration),
                        start_room_temp=session["start_room_temp"],
                        end_room_temp=current_room_temp,
                        target_temp=session["target_temp"],
                        consumption_kg=consumption_change,
                    )
                    
                    # Reset the stable period tracking but keep session alive
                    self._current_heating_session["stable_start_time"] = current_time
                    self._current_heating_session["start_room_temp"] = current_room_temp
                    self._current_heating_session["start_learning_consumption"] = self._learning_consumption_total
                    
                    _LOGGER.debug("Recorded periodic snapshot for HL%d after %.1f minutes", 
                                session["heatlevel"], stable_duration / 60)
            
            # Close any cooling session (only relevant in temperature mode)
            if self._current_cooling_session is not None and current_operation_mode == 1:
                # Cooling period ended, record it
                session = self._current_cooling_session
                duration = (current_time - session["start_time"]).total_seconds()
                
                # Check if this was a manual start (app/HA change) or automatic restart
                app_change = data.get("app_change_detected", False)
                
                _LOGGER.info(
                    "Cooling session ending - duration: %.1f min, start_temp: %.1f°C, end_temp: %.1f°C, target: %.1f°C, app_change: %s",
                    duration / 60,
                    session["start_room_temp"],
                    current_room_temp,
                    session["target_temp"],
                    app_change
                )
                
                if duration >= 1800:  # 30 minutes minimum
                    self._record_cooling_observation(
                        duration_seconds=int(duration),
                        start_room_temp=session["start_room_temp"],
                        end_room_temp=current_room_temp,
                        target_temp=session["target_temp"],
                    )
                    
                    # Only record restart delta if this was AUTOMATIC (no user intervention)
                    # Check:
                    # 1. Still in temperature mode (user didn't switch to heat level)
                    # 2. Target temp didn't change (user didn't adjust target during waiting)
                    # 3. No external app change detected
                    target_unchanged = session["target_temp"] == current_target_temp
                    mode_unchanged = session.get("operation_mode") == current_operation_mode == 1
                    
                    if target_unchanged and mode_unchanged and not app_change:
                        # Record restart delta (how far below target when restarted)
                        restart_delta = session["target_temp"] - current_room_temp
                        
                        # Record using running average
                        restart_data = self._learning_data["shutdown_restart_deltas"]["restart"]
                        restart_data["total_delta"] += restart_delta
                        restart_data["avg_delta"] = restart_data["total_delta"] / (restart_data["count"] + 1)
                        restart_data["count"] += 1
                        
                        _LOGGER.info(
                            "Recording AUTOMATIC restart delta: %.2f°C (avg=%.2f°C, count=%d)",
                            restart_delta,
                            restart_data["avg_delta"],
                            restart_data["count"]
                        )
                        
                        # Trigger save
                        asyncio.create_task(self.async_save_pellet_data())
                    else:
                        reasons = []
                        if not target_unchanged:
                            reasons.append(f"target changed from {session['target_temp']}°C to {current_target_temp}°C")
                        if not mode_unchanged:
                            reasons.append(f"mode changed")
                        if app_change:
                            reasons.append("app change detected")
                        
                        _LOGGER.info("Restart was INTERRUPTED (%s), not recording restart delta", ", ".join(reasons))
                else:
                    _LOGGER.warning("Cooling session too short (%.1f min), not recording", duration / 60)
                
                self._current_cooling_session = None
        
        # === COOLING SESSION TRACKING ===
        # Only track cooling/waiting in temperature mode
        elif is_waiting and current_operation_mode == 1:
            if self._current_cooling_session is None:
                # Start new cooling session
                self._current_cooling_session = {
                    "start_time": current_time,
                    "start_room_temp": current_room_temp,
                    "target_temp": current_target_temp,
                    "operation_mode": current_operation_mode,  # Track mode at start
                }
                
                # Record shutdown delta if we just stopped (only if not interrupted)
                if self._current_heating_session is not None:
                    shutdown_delta = current_room_temp - current_target_temp
                    
                    # Check if shutdown was natural (not interrupted by user)
                    heating_session_target = self._current_heating_session.get("target_temp")
                    heating_session_mode = current_operation_mode  # Should be 1 for temp mode
                    
                    # Only record if:
                    # - Still in temperature mode
                    # - Target temp didn't change during the session
                    if (heating_session_mode == 1 and 
                        heating_session_target == current_target_temp):
                        
                        # Record using running average
                        shutdown_data = self._learning_data["shutdown_restart_deltas"]["shutdown"]
                        shutdown_data["total_delta"] += shutdown_delta
                        shutdown_data["avg_delta"] = shutdown_data["total_delta"] / (shutdown_data["count"] + 1)
                        shutdown_data["count"] += 1
                        
                        _LOGGER.info(
                            "Stove entered waiting (AUTOMATIC), shutdown_delta=%.2f°C (avg=%.2f°C, count=%d)",
                            shutdown_delta,
                            shutdown_data["avg_delta"],
                            shutdown_data["count"]
                        )
                        
                        # Trigger save
                        asyncio.create_task(self.async_save_pellet_data())
                    else:
                        _LOGGER.info("Stove entered waiting (USER INTERRUPTED), not recording shutdown_delta")
                
                _LOGGER.debug("Started cooling/waiting session")
            
            # Close any heating session
            if self._current_heating_session is not None:
                # Heating period ended, record it if stable >15 min
                session = self._current_heating_session
                stable_duration = (current_time - session["stable_start_time"]).total_seconds()
                
                if stable_duration >= 900:  # 15 minutes
                    consumption_change = self._learning_consumption_total - session["start_learning_consumption"]
                    
                    self._record_heating_observation(
                        heatlevel=session["heatlevel"],
                        duration_seconds=int(stable_duration),
                        start_room_temp=session["start_room_temp"],
                        end_room_temp=current_room_temp,
                        target_temp=session["target_temp"],
                        consumption_kg=consumption_change,
                    )
                
                self._current_heating_session = None

        # === END OF OPERATION - RECORD FINAL SESSION ===
        # If stove stops (not burning, not waiting), record any active session
        if not is_burning and not is_waiting:
            if self._current_heating_session is not None:
                session = self._current_heating_session
                stable_duration = (current_time - session["stable_start_time"]).total_seconds()
                
                if stable_duration >= 900:  # 15 minutes
                    consumption_change = self._learning_consumption_total - session["start_learning_consumption"]
                    
                    self._record_heating_observation(
                        heatlevel=session["heatlevel"],
                        duration_seconds=int(stable_duration),
                        start_room_temp=session["start_room_temp"],
                        end_room_temp=current_room_temp,
                        target_temp=session["target_temp"],
                        consumption_kg=consumption_change,
                    )
                    
                    _LOGGER.debug("Recorded final heating session before stop")
                
                self._current_heating_session = None
            
            if self._current_cooling_session is not None and current_operation_mode == 1:
                session = self._current_cooling_session
                duration = (current_time - session["start_time"]).total_seconds()
                
                if duration >= 1800:  # 30 minutes
                    self._record_cooling_observation(
                        duration_seconds=int(duration),
                        start_room_temp=session["start_room_temp"],
                        end_room_temp=current_room_temp,
                        target_temp=session["target_temp"],
                    )
                    
                    _LOGGER.debug("Recorded final cooling session before stop")
                
                self._current_cooling_session = None
        
        # Update last known state
        self._last_learning_state = current_state
        self._last_learning_heatlevel = current_heatlevel
        self._last_learning_room_temp = current_room_temp
        self._last_learning_timestamp = current_time

    def _update_learning_consumption_tracker(self, data: dict[str, Any]) -> None:
            """Update the learning consumption tracker with increments from consumption_day."""
            if "consumption" not in data:
                return
            
            current_consumption_day = data["consumption"].get("day", 0)
            
            # Initialize on first run
            if self._last_consumption_day_for_learning is None:
                self._last_consumption_day_for_learning = current_consumption_day
                _LOGGER.debug("Initialized learning consumption tracker baseline: %.3f kg", current_consumption_day)
                return
            
            # Calculate increment
            increment = current_consumption_day - self._last_consumption_day_for_learning
            
            # Handle midnight reset (increment becomes negative)
            if increment < 0:
                # Midnight reset happened - use current value as increment
                increment = current_consumption_day
                _LOGGER.debug("Midnight reset detected in learning tracker - increment: %.3f kg", increment)
            
            # Only add positive increments
            if increment > 0:
                self._learning_consumption_total += increment
                _LOGGER.debug(
                    "Learning consumption updated: +%.3f kg (total: %.3f kg)",
                    increment,
                    self._learning_consumption_total
                )
            
            # Update last known value
            self._last_consumption_day_for_learning = current_consumption_day

    def _get_heating_rate(
        self,
        heatlevel: int,
        temp_delta: float,
        outdoor_temp: float | None,
    ) -> float:
        """
        Get heating rate for given conditions (ONLY heating rate, not consumption).
        Returns: heating_rate_celsius_per_hour
        """
        # Default heating rates if no learned data
        defaults = {
            1: 0.3,
            2: 0.6,
            3: 1.0,
        }
        
        # Get buckets
        temp_delta_bucket = self._get_temp_delta_bucket(temp_delta)
        outdoor_bucket = self._get_outdoor_temp_bucket(outdoor_temp) if outdoor_temp is not None else None
        
        # Try exact match first
        key = (heatlevel, temp_delta_bucket, outdoor_bucket)
        obs = self._learning_data["heating_observations"].get(key)
        
        if obs and obs["count"] >= 1:
            return obs["avg_heating_rate"]
        
        # Fallback: same heatlevel and temp_delta, any outdoor temp
        if outdoor_bucket is not None:
            matches = [
                obs for k, obs in self._learning_data["heating_observations"].items()
                if k[0] == heatlevel and k[1] == temp_delta_bucket and obs["count"] >= 1
            ]
            if matches:
                return sum(o["avg_heating_rate"] for o in matches) / len(matches)
        
        # Fallback: same heatlevel and outdoor, any temp_delta
        if outdoor_bucket is not None:
            matches = [
                obs for k, obs in self._learning_data["heating_observations"].items()
                if k[0] == heatlevel and k[2] == outdoor_bucket and obs["count"] >= 1
            ]
            if matches:
                return sum(o["avg_heating_rate"] for o in matches) / len(matches)
        
        # Fallback: same heatlevel only
        matches = [
            obs for k, obs in self._learning_data["heating_observations"].items()
            if k[0] == heatlevel and obs["count"] >= 1
        ]
        if matches:
            return sum(o["avg_heating_rate"] for o in matches) / len(matches)
        
        # No learned data - use defaults
        return defaults.get(heatlevel, 0.6)
    
    def _get_cooling_rate(
        self,
        start_room_temp: float,
        outdoor_temp: float | None,
    ) -> float:
        """
        Get cooling rate for given conditions.
        Returns: cooling_rate_celsius_per_hour
        """
        default_cooling_rate = 0.3
        
        # Get buckets
        start_temp_bucket = int(math.floor(start_room_temp / 2) * 2)
        outdoor_bucket = self._get_outdoor_temp_bucket(outdoor_temp) if outdoor_temp is not None else None
        
        # Try exact match
        key = (outdoor_bucket, start_temp_bucket)
        obs = self._learning_data["cooling_observations"].get(key)
        
        if obs and obs["count"] >= 1:
            return obs["avg_cooling_rate"]
        
        # Fallback: same outdoor temp, any start temp
        if outdoor_bucket is not None:
            matches = [
                obs for k, obs in self._learning_data["cooling_observations"].items()
                if k[0] == outdoor_bucket and obs["count"] >= 1
            ]
            if matches:
                return sum(o["avg_cooling_rate"] for o in matches) / len(matches)
        
        # Fallback: any outdoor, same start temp
        matches = [
            obs for k, obs in self._learning_data["cooling_observations"].items()
            if k[1] == start_temp_bucket and obs["count"] >= 1
        ]
        if matches:
            return sum(o["avg_cooling_rate"] for o in matches) / len(matches)
        
        # Fallback: average all cooling observations
        all_obs = [obs for obs in self._learning_data["cooling_observations"].values() if obs["count"] >= 1]
        if all_obs:
            return sum(o["avg_cooling_rate"] for o in all_obs) / len(all_obs)
        
        # No learned data
        return default_cooling_rate
    
    def _get_consumption_rate(self, heatlevel: int) -> float:
        """
        Get consumption rate for given heatlevel (NO outdoor temp dependency).
        Returns: consumption_rate_kg_per_hour
        """
        obs = self._learning_data.get("consumption_observations", {}).get(heatlevel)
        
        if obs and obs["count"] >= 1:
            return obs["avg_consumption_rate"]
        
        # Defaults if no learned data
        defaults = {1: 0.35, 2: 0.75, 3: 1.2}
        return defaults.get(heatlevel, 0.75)

    def _get_learning_status(self) -> dict[str, Any]:
        """Get status of learning data collection."""
        # Calculate hours of observation per heat level from consumption observations
        heatlevel_hours = {1: 0.0, 2: 0.0, 3: 0.0}
        
        for heatlevel in [1, 2, 3]:
            cons_obs = self._learning_data.get("consumption_observations", {}).get(heatlevel, {})
            # Estimate hours from count (assuming average 30 min per observation)
            heatlevel_hours[heatlevel] = cons_obs.get("count", 0) * 0.5
        
        # Count waiting periods
        waiting_periods = sum(
            obs["count"] for obs in self._learning_data["cooling_observations"].values()
        )
        
        # Check if data is recent (within 60 days)
        recent_data = False
        now = datetime.now()
        
        for obs in self._learning_data["heating_observations"].values():
            if (now - obs["last_updated"]).days <= 60:
                recent_data = True
                break
        
        if not recent_data:
            for obs in self._learning_data["cooling_observations"].values():
                if (now - obs["last_updated"]).days <= 60:
                    recent_data = True
                    break
        
        # Determine sufficiency
        sufficient_data = (
            heatlevel_hours[1] >= 10 and
            heatlevel_hours[2] >= 10 and
            heatlevel_hours[3] >= 10 and
            waiting_periods >= 5 and
            recent_data
        )
        
        return {
            "heatlevel_1_hours": round(heatlevel_hours[1], 1),
            "heatlevel_2_hours": round(heatlevel_hours[2], 1),
            "heatlevel_3_hours": round(heatlevel_hours[3], 1),
            "waiting_periods_observed": waiting_periods,
            "recent_data": recent_data,
            "sufficient_data": sufficient_data,
            "total_heating_observations": len(self._learning_data["heating_observations"]),
            "total_cooling_observations": len(self._learning_data["cooling_observations"]),
            "total_consumption_observations": sum(
                1 for obs in self._learning_data["consumption_observations"].values() if obs["count"] > 0
            ),
        }
    
    def _calculate_confidence_level(
        self,
        learning_status: dict[str, Any],
        operation_mode: int,
        cycles_predicted: int,
    ) -> str:
        """Calculate confidence level for prediction."""
        # High accuracy criteria
        if (learning_status["sufficient_data"] and
            learning_status["recent_data"] and
            operation_mode == 0 and  # Heat level mode
            cycles_predicted < 3):
            return "high"
        
        # Low accuracy criteria
        if (not learning_status["sufficient_data"] or
            cycles_predicted >= 8 or
            (self._external_temp_sensor and self._get_external_temperature() is None)):
            return "low"
        
        # Medium accuracy (everything else)
        return "medium"

    def predict_pellet_depletion(self) -> dict[str, Any] | None:
        """
        Predict when pellets will run out.
        Returns dict with prediction data or None if insufficient data/not applicable.
        """
        if not self.data or "operating" not in self.data or "status" not in self.data:
            return None
        
        current_state = self.data["operating"].get("state")
        current_operation_mode = self.data["status"].get("operation_mode")
        
        # Check if in wood mode - return N/A
        if current_operation_mode == 2:
            return {
                "status": "wood_mode",
                "message": "N/A - In wood mode",
            }
        
        # Determine if stove is actually running
        is_running = current_state in ["2", "4", "5", "6", "32"]
        
        # Get current conditions
        pellets_remaining = self.data.get("pellets", {}).get("amount", 0)
        
        if pellets_remaining <= 0:
            return {
                "time_remaining_seconds": 0,
                "time_remaining_formatted": "0h 0m",
                "depletion_datetime": datetime.now(),
                "confidence": "high",
                "status": "empty",
                "prediction_mode": "actual" if is_running else "hypothetical",
            }
        
        # Use current settings even when stove is off
        current_room_temp = self.data["operating"].get("boiler_temp", 20)
        target_temp = self.data["operating"].get("boiler_ref", 20)
        current_heatlevel = self.data["operating"].get("heatlevel", 2)
        outdoor_temp = self._get_external_temperature()
        
        # Get learned deltas
        shutdown_delta = self._learning_data["shutdown_restart_deltas"]["shutdown"]["avg_delta"]
        restart_delta = self._learning_data["shutdown_restart_deltas"]["restart"]["avg_delta"]
        
        # Get learning status
        learning_status = self._get_learning_status()
        
        # Check if we have minimum data
        if not learning_status["sufficient_data"]:
            return {
                "status": "insufficient_data",
                "learning_status": learning_status,
                "prediction_mode": "actual" if is_running else "hypothetical",
            }
        
        # Use cached weather forecast data (updated hourly in _async_update_data)
        forecast_data = self._forecast_data
        forecast_available = len(forecast_data) > 0
        
        # Validate minimum forecast horizon (24 hours)
        forecast_horizon_hours = 0
        if forecast_available:
            now = datetime.now()
            max_forecast_time = max(f["datetime"] for f in forecast_data)
            forecast_horizon_hours = (max_forecast_time - now).total_seconds() / 3600
            
            if forecast_horizon_hours < 24:
                _LOGGER.warning(
                    "Weather forecast horizon too short: %.1fh (recommended: 24h+)",
                    forecast_horizon_hours
                )
                # Still use it, but warn user
        
        _LOGGER.debug(
            "Forecast status: available=%s, horizon=%.1fh, entries=%d",
            forecast_available,
            forecast_horizon_hours,
            len(forecast_data)
        )
        
        # === HEAT LEVEL MODE (Simple) ===
        if current_operation_mode == 0:
            # Get consumption rate for current heat level (no outdoor temp dependency)
            consumption_rate = self._get_consumption_rate(current_heatlevel)
            
            if consumption_rate <= 0:
                return {
                    "status": "insufficient_data", 
                    "learning_status": learning_status,
                    "prediction_mode": "actual" if is_running else "hypothetical",
                }
            
            # Account for current state - if in startup, that consumption is already happening
            pellets_for_calculation = pellets_remaining
            startup_consumption = self._learning_data["startup_observations"]["avg_consumption"]
            
            # If stove is OFF or just started, account for startup consumption
            if current_state not in ["5", "32"]:
                # Will need startup before steady-state operation
                pellets_for_calculation -= startup_consumption
                if pellets_for_calculation <= 0:
                    # Not enough pellets to complete startup
                    return {
                        "time_remaining_seconds": 0,
                        "time_remaining_formatted": "0h 0m",
                        "depletion_datetime": datetime.now(),
                        "confidence": "high",
                        "status": "empty",
                        "prediction_mode": "actual" if is_running else "hypothetical",
                    }
            
            # Simple calculation
            time_remaining_hours = pellets_for_calculation / consumption_rate
            time_remaining_seconds = int(time_remaining_hours * 3600)
            
            depletion_datetime = datetime.now() + timedelta(seconds=time_remaining_seconds)
            
            confidence = self._calculate_confidence_level(
                learning_status=learning_status,
                operation_mode=0,
                cycles_predicted=0,
            )
            
            result = {
                "time_remaining_seconds": time_remaining_seconds,
                "time_remaining_formatted": self._format_time_remaining(time_remaining_seconds),
                "depletion_datetime": depletion_datetime,
                "confidence": confidence,
                "status": "ok",
                "mode": "heatlevel",
                "current_heatlevel": current_heatlevel,
                "consumption_rate": round(consumption_rate, 2),
                "learning_status": learning_status,
                "prediction_mode": "actual" if is_running else "hypothetical",
                "forecast_used": forecast_available,
                "forecast_horizon_hours": round(forecast_horizon_hours, 1) if forecast_available else 0,
            }
            
            # Check if prediction changed significantly and log details
            current_time = result["time_remaining_seconds"]
            
            if self._last_prediction_time is not None:
                time_change = abs(current_time - self._last_prediction_time)
                
                if time_change >= self._prediction_change_threshold_seconds:
                    _LOGGER.debug("Prediction changed significantly: %ds change", time_change)
                    _LOGGER.debug("PREVIOUS PREDICTION:\n%s", self._last_prediction_log or "No previous log")
                    _LOGGER.debug("NEW PREDICTION:\n%s", self._build_prediction_log(result, None))
            
            # Store current prediction for next comparison
            self._last_prediction_time = current_time
            self._last_prediction_log = self._build_prediction_log(result, None)
            
            return result
        
        # === TEMPERATURE MODE (Complex with cycles) ===
        total_time_seconds = 0
        cycles_count = 0
        pellets_left = pellets_remaining
        simulation_log = []  # Track each phase for logging
        sim_room_temp = current_room_temp
        sim_state = "burning" if is_running else "waiting"
        sim_heatlevel = current_heatlevel
        time_at_current_level = 0
        
        # Track if we're already at level 1 for shutdown check
        time_at_level_1 = 0
        if current_heatlevel == 1 and is_running and current_state in ["5", "32"]:
            # Assume we've been at level 1 for at least 10 minutes (conservative)
            time_at_level_1 = 10 * 60
        
        max_iterations = 100  # Safety limit
        iteration = 0
        startup_consumption = self._learning_data["startup_observations"]["avg_consumption"]
        startup_duration = self._learning_data["startup_observations"]["avg_duration"]
        
        while pellets_left > 0 and iteration < max_iterations:
            iteration += 1
            
            # === BURNING PHASE ===
            if sim_state == "burning":
                cycles_count += 1
                
                # Account for startup consumption at beginning of each cycle
                pellets_left -= startup_consumption
                total_time_seconds += startup_duration
                
                # Log startup phase
                simulation_log.append({
                    "type": "startup",
                    "duration_seconds": startup_duration,
                    "consumption_kg": startup_consumption,
                })
                
                if pellets_left <= 0:
                    # Ran out during startup
                    break
                
                # Simulate burning until next event
                while pellets_left > 0:
                    temp_delta = target_temp - sim_room_temp
                    
                    # === GET OUTDOOR TEMP FOR CURRENT SIMULATION TIME ===
                    future_time = datetime.now() + timedelta(seconds=total_time_seconds)
                    
                    if forecast_available:
                        forecast_temp = self._get_forecast_temp_at_time(forecast_data, future_time)
                        
                        # Fallback to current temp if forecast doesn't cover this time
                        if forecast_temp is not None:
                            outdoor_temp = forecast_temp
                        else:
                            outdoor_temp = self._get_external_temperature()
                            if outdoor_temp is None:
                                outdoor_temp = 0  # Final fallback
                    else:
                        # No forecast - use current external temp
                        outdoor_temp = self._get_external_temperature()
                        if outdoor_temp is None:
                            outdoor_temp = 0  # Final fallback
                    
                    # Get heating rate (with current outdoor temp)
                    heating_rate = self._get_heating_rate(
                        heatlevel=sim_heatlevel,
                        temp_delta=temp_delta,
                        outdoor_temp=outdoor_temp,
                    )
                    
                    # Get consumption rate (NO outdoor temp dependency)
                    consumption_rate = self._get_consumption_rate(sim_heatlevel)
                    
                    if consumption_rate <= 0:
                        # Can't predict without consumption data
                        return {
                            "status": "insufficient_data", 
                            "learning_status": learning_status,
                            "prediction_mode": "actual" if is_running else "hypothetical",
                            "forecast_used": forecast_available,
                            "forecast_horizon_hours": round(forecast_horizon_hours, 1) if forecast_available else 0,
                        }
                    
                    # Calculate time to next event
                    
                    # Event 1: Check if level change needed after 10 minutes
                    if time_at_current_level >= 10 * 60:
                        # Predict temp after 10 minutes at current level
                        temp_in_10min = sim_room_temp + (heating_rate * 10 / 60)
                        temp_delta_in_10min = target_temp - temp_in_10min
                        
                        if temp_delta_in_10min > 0.5 and sim_heatlevel < 3:
                            # Need to increase level
                            time_to_event = 10 * 60
                            next_event = "increase_level"
                        elif temp_delta_in_10min < -0.5 and sim_heatlevel > 1:
                            # Need to decrease level
                            time_to_event = 10 * 60
                            next_event = "decrease_level"
                        else:
                            # No level change, check for shutdown
                            next_event = None
                    else:
                        # Must wait until 10 minutes at current level
                        time_to_event = (10 * 60) - time_at_current_level
                        next_event = "level_change_check"
                    
                    # Event 2: Shutdown temperature reached (only at level 1 after 10 min)
                    if heating_rate > 0.05:  # Room is heating
                        shutdown_temp = target_temp + shutdown_delta
                        temp_to_gain = shutdown_temp - sim_room_temp
                        
                        if temp_to_gain > 0:
                            time_to_shutdown_seconds = (temp_to_gain / heating_rate) * 3600
                            
                            # Only valid if at level 1 for 10+ minutes
                            if sim_heatlevel == 1 and time_at_level_1 >= 10 * 60:
                                if next_event is None or time_to_shutdown_seconds < time_to_event:
                                    time_to_event = time_to_shutdown_seconds
                                    next_event = "shutdown"
                    else:
                        # Not heating (or cooling) - continuous burn, no shutdown
                        # Check if continuous burn condition
                        if heating_rate <= 0.05 and next_event is None:
                            # Will never reach shutdown - burns continuously
                            time_to_empty_seconds = (pellets_left / consumption_rate) * 3600
                            time_to_event = time_to_empty_seconds
                            next_event = "pellets_empty"
                    
                    # Event 3: Pellets run out
                    time_to_empty_seconds = (pellets_left / consumption_rate) * 3600
                    
                    if next_event is None or time_to_empty_seconds < time_to_event:
                        time_to_event = time_to_empty_seconds
                        next_event = "pellets_empty"
                    
                    # This ensures we recalculate with new forecast temps
                    max_step_size = 3600  # 1 hour in seconds
                    
                    if time_to_event > max_step_size and next_event not in ["pellets_empty", "increase_level", "decrease_level", "level_change_check"]:
                        # Take a 1-hour step, then recalculate
                        actual_step = max_step_size
                        step_event = "temp_update"
                    else:
                        # Step is short enough or is a definitive event
                        actual_step = time_to_event
                        step_event = next_event
                    
                    actual_step = max(0, actual_step)
                    
                    # Update state for this step
                    start_temp_for_log = sim_room_temp
                    sim_room_temp += (heating_rate * actual_step / 3600)
                    pellets_consumed = consumption_rate * (actual_step / 3600)
                    pellets_left -= pellets_consumed
                    pellets_left = max(0, pellets_left)
                    
                    total_time_seconds += actual_step
                    time_at_current_level += actual_step
                    
                    # Log this heating step
                    simulation_log.append({
                        "type": "heating",
                        "heatlevel": sim_heatlevel,
                        "duration_seconds": actual_step,
                        "start_temp": start_temp_for_log,
                        "end_temp": sim_room_temp,
                        "outdoor_temp": outdoor_temp,
                        "heating_rate": heating_rate,
                        "consumption_rate": consumption_rate,
                        "pellets_used": pellets_consumed,
                        "pellets_remaining": pellets_left,
                        "reason": step_event,
                    })
                    
                    if sim_heatlevel == 1:
                        time_at_level_1 += actual_step
                    
                    # Handle event
                    if step_event == "pellets_empty" or pellets_left <= 0:
                        # Done!
                        break
                    
                    elif step_event == "temp_update":
                        # Just a temperature update step, continue loop to recalculate
                        continue
                    
                    elif step_event == "increase_level":
                        old_level = sim_heatlevel
                        sim_heatlevel = min(3, sim_heatlevel + 1)
                        simulation_log.append({
                            "type": "level_change",
                            "old_level": old_level,
                            "new_level": sim_heatlevel,
                        })
                        time_at_current_level = 0
                        if sim_heatlevel == 1:
                            time_at_level_1 = 0
                        continue
                    
                    elif step_event == "decrease_level":
                        old_level = sim_heatlevel
                        sim_heatlevel = max(1, sim_heatlevel - 1)
                        simulation_log.append({
                            "type": "level_change",
                            "old_level": old_level,
                            "new_level": sim_heatlevel,
                        })
                        time_at_current_level = 0
                        if sim_heatlevel == 1:
                            time_at_level_1 = 0
                        continue
                    
                    elif step_event == "level_change_check":
                        # Just reached 10 minutes, check again
                        continue
                    
                    elif step_event == "shutdown":
                        # Enter waiting period
                        sim_state = "waiting"
                        sim_heatlevel = 1  # Will restart at level 1
                        time_at_current_level = 0
                        time_at_level_1 = 0
                        break
                
                # If pellets empty, exit main loop
                if pellets_left <= 0:
                    break
            
            # === WAITING PHASE ===
            if sim_state == "waiting":
                # Calculate target restart temperature
                restart_temp = target_temp - restart_delta
                
                # Simulate cooling in steps until restart temperature reached
                while sim_room_temp > restart_temp and pellets_left > 0:
                    # === GET OUTDOOR TEMP FOR CURRENT SIMULATION TIME ===
                    future_time = datetime.now() + timedelta(seconds=total_time_seconds)
                    
                    if forecast_available:
                        forecast_temp = self._get_forecast_temp_at_time(forecast_data, future_time)
                        
                        if forecast_temp is not None:
                            outdoor_temp = forecast_temp
                        else:
                            outdoor_temp = self._get_external_temperature()
                            if outdoor_temp is None:
                                outdoor_temp = 0
                    else:
                        outdoor_temp = self._get_external_temperature()
                        if outdoor_temp is None:
                            outdoor_temp = 0
                    
                    # Get cooling rate (with current outdoor temp)
                    cooling_rate = self._get_cooling_rate(
                        start_room_temp=sim_room_temp,
                        outdoor_temp=outdoor_temp,
                    )
                    
                    # Calculate time to reach restart temp at current cooling rate
                    temp_to_lose = sim_room_temp - restart_temp
                    
                    if temp_to_lose > 0 and cooling_rate > 0:
                        time_to_restart = (temp_to_lose / cooling_rate) * 3600
                    else:
                        # Can't cool or already at restart temp
                        break
                    
                    # Limit step size to 1 hour for temperature updates
                    max_step_size = 3600  # 1 hour in seconds
                    
                    if time_to_restart > max_step_size:
                        # Take a 1-hour step, then recalculate with new outdoor temp
                        actual_step = max_step_size
                        temp_decrease = cooling_rate * (actual_step / 3600)
                    else:
                        # Will reach restart temp within the hour
                        actual_step = time_to_restart
                        temp_decrease = temp_to_lose
                    
                    # Update state
                    start_temp_for_log = sim_room_temp
                    sim_room_temp -= temp_decrease
                    total_time_seconds += actual_step
                    
                    # Log cooling step
                    simulation_log.append({
                        "type": "waiting",
                        "duration_seconds": actual_step,
                        "start_temp": start_temp_for_log,
                        "end_temp": sim_room_temp,
                        "outdoor_temp": outdoor_temp,
                        "cooling_rate": cooling_rate,
                        "restart_temp": restart_temp,
                    })
                    
                    # Check if we've reached restart temperature
                    if sim_room_temp <= restart_temp:
                        sim_room_temp = restart_temp  # Don't overshoot
                        break
                
                # After waiting, restart at level 1
                sim_state = "burning"
                sim_heatlevel = 1
                time_at_current_level = 0
                time_at_level_1 = 0
        
        # Format results
        depletion_datetime = datetime.now() + timedelta(seconds=total_time_seconds)
        
        confidence = self._calculate_confidence_level(
            learning_status=learning_status,
            operation_mode=1,
            cycles_predicted=cycles_count,
        )
        
        result = {
            "time_remaining_seconds": int(total_time_seconds),
            "time_remaining_formatted": self._format_time_remaining(int(total_time_seconds)),
            "depletion_datetime": depletion_datetime,
            "confidence": confidence,
            "status": "ok",
            "mode": "temperature",
            "cycles_remaining": cycles_count,
            "current_phase": "burning" if current_state in ["2", "4", "5", "32"] else "waiting" if current_state == "6" else "off",
            "learning_status": learning_status,
            "shutdown_delta": round(shutdown_delta, 1),
            "restart_delta": round(restart_delta, 1),
            "prediction_mode": "actual" if is_running else "hypothetical",
            "forecast_used": forecast_available,
            "forecast_horizon_hours": round(forecast_horizon_hours, 1) if forecast_available else 0,
        }
        
        # Check if prediction changed significantly and log details
        current_time = result["time_remaining_seconds"]
        
        if self._last_prediction_time is not None:
            time_change = abs(current_time - self._last_prediction_time)
            
            if time_change >= self._prediction_change_threshold_seconds:
                _LOGGER.debug("Prediction changed significantly: %ds change", time_change)
                _LOGGER.debug("PREVIOUS PREDICTION:\n%s", self._last_prediction_log or "No previous log")
                _LOGGER.debug("NEW PREDICTION:\n%s", self._build_prediction_log(result, simulation_log))
        
        # Store current prediction for next comparison
        self._last_prediction_time = current_time
        self._last_prediction_log = self._build_prediction_log(result, simulation_log)
        
        return result
    
    def _format_time_remaining(self, seconds: int) -> str:
        """Format time remaining as 'Xh Ym' or 'Xd Yh' if >24 hours."""
        if seconds <= 0:
            return "0h 0m"
        
        days = seconds // 86400
        hours = (seconds % 86400) // 3600
        minutes = (seconds % 3600) // 60
        
        if days > 0:
            return f"{days}d {hours}h"
        else:
            return f"{hours}h {minutes}m"

    def _build_prediction_log(
            self,
            prediction: dict[str, Any],
            simulation_log: list[dict[str, Any]] | None = None
        ) -> str:
            """Build detailed log of prediction calculation."""
            lines = []
            lines.append("=" * 80)
            lines.append("PELLET DEPLETION PREDICTION DETAILS")
            lines.append("=" * 80)
            
            # Basic info
            status = prediction.get("status")
            lines.append(f"Status: {status}")
            lines.append(f"Prediction Mode: {prediction.get('prediction_mode', 'unknown')}")
            lines.append(f"Confidence: {prediction.get('confidence', 'unknown')}")
            
            if status == "ok":
                lines.append(f"Time Remaining: {prediction.get('time_remaining_formatted')} ({prediction.get('time_remaining_seconds')}s)")
                lines.append(f"Depletion DateTime: {prediction.get('depletion_datetime')}")
                lines.append(f"Mode: {prediction.get('mode')}")
                
                # Weather info
                lines.append(f"Forecast Used: {prediction.get('forecast_used', False)}")
                if prediction.get('forecast_used'):
                    lines.append(f"Forecast Horizon: {prediction.get('forecast_horizon_hours', 0)}h")
            
            # Current conditions
            if self.data and "operating" in self.data:
                lines.append("")
                lines.append("CURRENT CONDITIONS:")
                lines.append(f"  Room Temperature: {self.data['operating'].get('boiler_temp')}°C")
                lines.append(f"  Target Temperature: {self.data['operating'].get('boiler_ref')}°C")
                lines.append(f"  Heat Level: {self.data['operating'].get('heatlevel')}")
                lines.append(f"  State: {self.data['operating'].get('state')}")
                
            external_temp = self._get_external_temperature()
            if external_temp is not None:
                lines.append(f"  External Temperature: {external_temp}°C")
            
            # Pellet info
            if self.data and "pellets" in self.data:
                lines.append("")
                lines.append("PELLET STATUS:")
                lines.append(f"  Remaining: {self.data['pellets'].get('amount')} kg ({self.data['pellets'].get('percentage')}%)")
            
            # Simulation details (if available)
            if simulation_log:
                lines.append("")
                lines.append("SIMULATION PHASES:")
                lines.append("-" * 80)
                
                for phase in simulation_log:
                    phase_type = phase.get("type")
                    duration_min = phase.get("duration_seconds", 0) / 60
                    
                    if phase_type == "startup":
                        lines.append(f"  STARTUP: {duration_min:.1f} min")
                        lines.append(f"    Consumption: {phase.get('consumption_kg', 0):.3f} kg")
                        
                    elif phase_type == "heating":
                        lines.append(f"  HEATING (HL{phase.get('heatlevel')}): {duration_min:.1f} min")
                        lines.append(f"    Temp: {phase.get('start_temp'):.1f}°C → {phase.get('end_temp'):.1f}°C")
                        lines.append(f"    Outdoor Temp: {phase.get('outdoor_temp')}°C")
                        lines.append(f"    Heating Rate: {phase.get('heating_rate'):.2f}°C/h")
                        lines.append(f"    Consumption Rate: {phase.get('consumption_rate'):.2f} kg/h")
                        lines.append(f"    Pellets Used: {phase.get('pellets_used'):.3f} kg")
                        lines.append(f"    Pellets Remaining: {phase.get('pellets_remaining'):.3f} kg")
                        if phase.get('reason'):
                            lines.append(f"    Ended: {phase.get('reason')}")
                        
                    elif phase_type == "waiting":
                        lines.append(f"  WAITING: {duration_min:.1f} min")
                        lines.append(f"    Temp: {phase.get('start_temp'):.1f}°C → {phase.get('end_temp'):.1f}°C")
                        lines.append(f"    Outdoor Temp: {phase.get('outdoor_temp')}°C")
                        lines.append(f"    Cooling Rate: {phase.get('cooling_rate'):.2f}°C/h")
                        lines.append(f"    Target Restart: {phase.get('restart_temp'):.1f}°C")
                        
                    elif phase_type == "level_change":
                        lines.append(f"  LEVEL CHANGE: HL{phase.get('old_level')} → HL{phase.get('new_level')}")
                        
                    lines.append("")
            
            lines.append("=" * 80)
            return "\n".join(lines)

    async def async_save_pellet_data(self) -> None:
        """Save pellet tracking data to storage."""
        try:
            data = {
                "pellets_consumed": self._pellets_consumed,
                "pellets_consumed_total": self._pellets_consumed_total,
                "consumption_snapshots": self._consumption_snapshots,
                "snapshots_initialized": getattr(self, '_snapshots_initialized', False),
                "last_consumption_day": self._last_consumption_day.isoformat() if self._last_consumption_day else None,
                # Save user preferences (switches)
                "auto_resume_after_wood": self._auto_resume_after_wood,
                "auto_shutdown_enabled": self._auto_shutdown_enabled,
                # Save user settings (numbers)
                "pellet_capacity": self._pellet_capacity,
                "notification_level": self._notification_level,
                "shutdown_level": self._shutdown_level,
                "high_smoke_temp_threshold": self._high_smoke_temp_threshold,
                "high_smoke_duration_threshold": self._high_smoke_duration_threshold,
                "low_wood_temp_threshold": self._low_wood_temp_threshold,
                "low_wood_duration_threshold": self._low_wood_duration_threshold,
                # Save learning data (convert tuple keys to strings and datetime to isoformat for JSON compatibility)
                "learning_data": {
                    "heating_observations": {
                        str(k): {
                            **v,
                            "last_updated": v["last_updated"].isoformat() if isinstance(v.get("last_updated"), datetime) else str(v.get("last_updated", ""))
                        } for k, v in self._learning_data["heating_observations"].items()
                    },
                    "cooling_observations": {
                        str(k): {
                            **v,
                            "last_updated": v["last_updated"].isoformat() if isinstance(v.get("last_updated"), datetime) else str(v.get("last_updated", ""))
                        } for k, v in self._learning_data["cooling_observations"].items()
                    },
                    "consumption_observations": self._learning_data["consumption_observations"],
                    "startup_observations": self._learning_data["startup_observations"],
                    "shutdown_restart_deltas": self._learning_data["shutdown_restart_deltas"],
                },
                "external_temp_sensor": self._external_temp_sensor,
                "weather_forecast_sensor": self._weather_forecast_sensor,

                # Save learning consumption tracker
                "learning_consumption_total": self._learning_consumption_total,
                "last_consumption_day_for_learning": self._last_consumption_day_for_learning,

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
        
        # Reset only the per-refill counter, NOT the total counter
        old_consumed = self._pellets_consumed
        self._pellets_consumed = 0.0
        self._last_consumption_day = date.today()
        self._low_pellet_notification_sent = False
        self._shutdown_notification_sent = False
        
        _LOGGER.info(
            "Pellets refilled - reset consumed from %.2f to 0.0 kg, capacity: %.1f kg, total consumed since cleaning: %.2f kg",
            old_consumed,
            self._pellet_capacity,
            self._pellets_consumed_total
        )

        asyncio.create_task(self.async_save_pellet_data())

    def reset_refill_counter(self) -> None:
        """Reset total consumption counter after cleaning."""
        old_total = self._pellets_consumed_total
        self._pellets_consumed_total = 0.0
        _LOGGER.info(
            "Stove cleaned - total consumption counter reset from %.2f to 0.0 kg",
            old_total
        )

        asyncio.create_task(self.async_save_pellet_data())

    def set_pellet_capacity(self, capacity: float) -> None:
        """Set pellet capacity."""
        self._pellet_capacity = capacity
        _LOGGER.info("Pellet capacity set to: %s kg", capacity)
        asyncio.create_task(self.async_save_pellet_data())

    def set_notification_level(self, level: float) -> None:
        """Set notification level (percentage)."""
        self._notification_level = level
        _LOGGER.info("Notification level set to: %s%%", level)
        asyncio.create_task(self.async_save_pellet_data())

    def set_shutdown_level(self, level: float) -> None:
        """Set auto-shutdown level (percentage)."""
        self._shutdown_level = level
        _LOGGER.info("Shutdown level set to: %s%%", level)
        asyncio.create_task(self.async_save_pellet_data())

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
        asyncio.create_task(self.async_save_pellet_data())

    def set_high_smoke_duration_threshold(self, duration: int) -> None:
        """Set high smoke temperature duration threshold."""
        self._high_smoke_duration_threshold = duration
        _LOGGER.info("High smoke duration threshold set to: %s seconds", duration)
        asyncio.create_task(self.async_save_pellet_data())

    def set_low_wood_temp_threshold(self, temperature: float) -> None:
        """Set low wood mode temperature threshold."""
        self._low_wood_temp_threshold = temperature
        _LOGGER.info("Low wood temp threshold set to: %s°C", temperature)
        asyncio.create_task(self.async_save_pellet_data())

    def set_low_wood_duration_threshold(self, duration: int) -> None:
        """Set low wood mode temperature duration threshold."""
        self._low_wood_duration_threshold = duration
        _LOGGER.info("Low wood duration threshold set to: %s seconds", duration)
        asyncio.create_task(self.async_save_pellet_data())

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
        """Resume pellet operation after wood mode (state 9)."""
        if not self.data or "operating" not in self.data:
            _LOGGER.error("No data available to resume after wood mode")
            return False
        
        current_state = self.data["operating"].get("state")
        
        # Check if stove is in wood mode (state 9)
        if current_state not in ["9"]:
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
        
        # CRITICAL FIX: Set all targets BEFORE sending the command
        self._toggle_heat_target = True
        self._change_in_progress = True
        self._mode_change_started = datetime.now()
        self._resend_attempt = 0
        self._target_operation_mode = new_mode
        
        # Set appropriate targets based on new mode BEFORE sending command
        if new_mode == 0:  # Switching to heatlevel mode
            if self.data and "operating" in self.data:
                current_heatlevel = self.data["operating"].get("heatlevel", 2)
                self._target_heatlevel = current_heatlevel
                _LOGGER.debug("Target heatlevel set to: %s", current_heatlevel)
        elif new_mode == 1:  # Switching to temperature mode
            if self.data and "operating" in self.data:
                current_temp = self.data["operating"].get("boiler_ref", 20)
                self._target_temperature = current_temp
                _LOGGER.debug("Target temperature set to: %s°C", current_temp)
        
        # Now send the command
        result = await self._async_send_command("regulation.operation_mode", new_mode)
        
        if not result:
            _LOGGER.error("Failed to toggle mode")
            # Clear the flags if command failed
            self._change_in_progress = False
            self._toggle_heat_target = False
            self._mode_change_started = None
            self._target_operation_mode = None
            self._target_heatlevel = None
            self._target_temperature = None
            return False
        
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
