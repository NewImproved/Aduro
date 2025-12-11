"""Sensor platform for Aduro Hybrid Stove integration."""
from __future__ import annotations

from datetime import datetime
import logging
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfMass,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import translation as trans_helper

from .const import (
    DOMAIN,
    HEAT_LEVEL_DISPLAY,
    STATE_NAMES,
    SUBSTATE_NAMES,
)
from .coordinator import AduroCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Aduro sensor entities."""
    coordinator: AduroCoordinator = hass.data[DOMAIN][entry.entry_id]

    sensors = [
        # Status sensors
        AduroStateSensor(coordinator, entry),
        AduroSubstateSensor(coordinator, entry),
        AduroMainStatusSensor(coordinator, entry),
        AduroSubStatusSensor(coordinator, entry),
        
        # Temperature sensors
        AduroBoilerTempSensor(coordinator, entry),
        AduroBoilerRefSensor(coordinator, entry),
        AduroSmokeTempSensor(coordinator, entry),
        AduroShaftTempSensor(coordinator, entry),
        
        # Power sensors
        AduroPowerKwSensor(coordinator, entry),

        # Carbon Monoxide sensors
        AduroCarbonMonoxideSensor(coordinator, entry),
        AduroCarbonMonoxideYellowSensor(coordinator, entry),
        AduroCarbonMonoxideRedSensor(coordinator, entry),
        
        # Operation sensors
        AduroOperationModeSensor(coordinator, entry),
        
        # Pellet sensors
        AduroPelletAmountSensor(coordinator, entry),
        AduroPelletPercentageSensor(coordinator, entry),
        AduroPelletConsumedSensor(coordinator, entry),
        AduroPelletConsumptionTotalSensor(coordinator, entry),
        AduroPelletRefillCounterSensor(coordinator, entry),
        
        # Consumption sensors
        AduroConsumptionDaySensor(coordinator, entry),
        AduroConsumptionYesterdaySensor(coordinator, entry),
        AduroConsumptionMonthSensor(coordinator, entry),
        AduroConsumptionYearSensor(coordinator, entry),
        AduroMonthlyHistorySensor(coordinator, entry),
        AduroYearlyHistorySensor(coordinator, entry),
        AduroYearOverYearSensor(coordinator, entry),
        
        # Network sensors
        AduroStoveIPSensor(coordinator, entry),
        AduroRouterSSIDSensor(coordinator, entry),
        AduroStoveRSSISensor(coordinator, entry),
        AduroStoveMacSensor(coordinator, entry),
        AduroFirmwareVersionSensor(coordinator, entry),
        
        # Runtime sensors
        AduroOperatingTimeStoveSensor(coordinator, entry),
        AduroOperatingTimeAugerSensor(coordinator, entry),
        AduroOperatingTimeIgnitionSensor(coordinator, entry),
        
        # Calculated/status sensors
        AduroModeTransitionSensor(coordinator, entry),
        AduroChangeInProgressSensor(coordinator, entry),
        AduroDisplayFormatSensor(coordinator, entry),
        AduroDisplayTargetSensor(coordinator, entry),
        AduroAppChangeDetectedSensor(coordinator, entry),

        # Temperature alert sensors
        AduroHighSmokeTempAlertSensor(coordinator, entry),
        AduroLowWoodTempAlertSensor(coordinator, entry),
    ]

    async_add_entities(sensors)


class AduroSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for Aduro sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AduroCoordinator,
        entry: ConfigEntry,
        sensor_type: str,
        translation_key: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)  # Only pass coordinator to CoordinatorEntity
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{sensor_type}"
        self._attr_translation_key = translation_key
        self._sensor_type = sensor_type
        self._entity_id_suffix = sensor_type
        self._last_valid_value = None

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        
        # Force the entity_id to be in English
        registry = er.async_get(self.hass)
        
        # Construct the desired English entity_id
        desired_entity_id = f"sensor.{DOMAIN}_{self.coordinator.stove_model.lower()}_{self._entity_id_suffix}"
        
        # Get the current entity from registry
        current_entry = registry.async_get(self.entity_id)
        
        # If entity_id doesn't match what we want, update it
        if current_entry and self.entity_id != desired_entity_id:
            _LOGGER.debug(f"Setting entity_id to {desired_entity_id}")
            registry.async_update_entity(self.entity_id, new_entity_id=desired_entity_id)

    def combined_firmware_version(self) -> str | None:
        """Return combined firmware version string."""
        version = self.coordinator.firmware_version
        build = self.coordinator.firmware_build

        _LOGGER.debug(
            "Getting firmware version - version: %s, build: %s",
            version,
            build
        )

        if version and build:
            return f"{version}.{build}"
        elif version:
            return version
        return None


    @property
    def device_info(self):
        """Return device information."""
        # Always get the latest firmware version from coordinator
        sw_version = self.combined_firmware_version()
        
        # Base device data - always include these
        device_data = {
            "identifiers": {(DOMAIN, f"aduro_{self.coordinator.entry.entry_id}")},
            "name": f"Aduro {self.coordinator.stove_model}",
            "manufacturer": "Aduro",
            "model": f"Hybrid {self.coordinator.stove_model}",
        }
        
        # ALWAYS include sw_version, even if None initially
        # This ensures the device registry entry has the field
        device_data["sw_version"] = sw_version
        
        return device_data
        
    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        # Only unavailable if coordinator failed to update (connection lost)
        if not self.coordinator.last_update_success:
            return False
        
        # Check if stove IP is available (indicates connectivity)
        if not self.coordinator.stove_ip:
            return False
        
        return True

    def _get_cached_value(self, current_value, default=None):
        """Return current value or last cached value if current is None."""
        if current_value is not None:
            self._last_valid_value = current_value
            return current_value
        
        # Return last valid value if we have one, otherwise default
        return self._last_valid_value if self._last_valid_value is not None else default


# =============================================================================
# Status Sensors
# =============================================================================

class AduroStateSensor(AduroSensorBase):
    """Sensor for stove state."""

    # Map heatlevel numbers to Roman numerals
    HEATLEVEL_ROMAN = {
        1: "I",
        2: "II",
        3: "III",
    }

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "state", "state")
        self._attr_icon = "mdi:state-machine"
        # DON'T use device_class ENUM when you want to return translated strings
        # self._attr_device_class = SensorDeviceClass.ENUM
        # self._attr_options = [...]
        self._translations = {}
        self._translations_loaded = False

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        await self._load_translations()

    async def _load_translations(self) -> None:
        """Load translations for the current language."""
        try:
            language = self.hass.config.language
            self._translations = await trans_helper.async_get_translations(
                self.hass,
                language,
                "entity",
                {DOMAIN},
            )
            self._translations_loaded = True
            _LOGGER.debug("Loaded translations for language: %s", language)
        except Exception as err:
            _LOGGER.warning("Failed to load translations: %s", err)
            self._translations_loaded = False

    def _get_translated_state(self, translation_key: str, heatlevel: int = 1) -> str:
        """Get translated state string with formatting."""
        # Convert heatlevel to Roman numeral
        heatlevel_roman = self.HEATLEVEL_ROMAN.get(heatlevel, "I")
        
        # Build the full translation key
        full_key = f"component.{DOMAIN}.entity.sensor.state_disp.state.{translation_key}"
        
        # Try to get translation
        if self._translations_loaded and full_key in self._translations:
            template = self._translations[full_key]
            try:
                # Format with Roman numeral heatlevel
                return template.format(heatlevel=heatlevel_roman)
            except (KeyError, ValueError):
                return template
        
        # Fallback to English with Roman numerals
        fallback_translations = {
            "state_operating": f"Power {heatlevel_roman}",
            "state_stopped": "Stopped",
            "state_off": "Off",
            "state_operating_iii": "Power III",
            "state_stopped_draft": "Dropshaft hot",
            "state_stopped_smoke_sensor": "Bad smoke sensor",
            "state_stopped_dropshaft": "Bad dropshaft sensor",
            "state_stopped_burner_yellow": "Check burner yellow",
            "state_stopped_auger": "bad external auger output",
            "state_stopped_timer": "Stopped by timer",
            "state_operating_air_damper": "Air damper closed",
            "state_stopped_co_sensor": "Co sensor defect",
            "state_stopped_no_fan": "No power consumption for fan",
        }
        
        return fallback_translations.get(translation_key, translation_key)

    @property
    def native_value(self) -> str | None:
        """Return the translated and formatted state."""
        if not self.coordinator.data or "operating" not in self.coordinator.data:
            return None
        
        state = self.coordinator.data["operating"].get("state")
        heatlevel = self.coordinator.data["operating"].get("heatlevel", 1)
        
        # Get translation key from const
        translation_key = STATE_NAMES.get(state, "state_unknown")
        
        # Return translated and formatted string with Roman numerals
        return self._get_translated_state(translation_key, heatlevel)
    
    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data or "operating" not in self.coordinator.data:
            return {}
        
        heatlevel = self.coordinator.data["operating"].get("heatlevel", 1)
        
        return {
            "heatlevel": heatlevel,
            "heatlevel_roman": self.HEATLEVEL_ROMAN.get(heatlevel, "I"),
            "raw_state": self.coordinator.data["operating"].get("state"),
        }


class AduroSubstateSensor(AduroSensorBase):
    """Sensor for stove substate."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "substate", "substate")
        self._attr_icon = "mdi:state-machine"
        self._attr_device_class = SensorDeviceClass.ENUM
        self._attr_options = [
            "substate_waiting",
            "substate_ignition_1",
            "substate_ignition_2",
            "substate_normal",
            "substate_temp_reached",
            "substate_wood_burning",
            "substate_dropshaft_hot",
            "substate_failed_ignition",
            "substate_by_button",
            "substate_wood_burning_question",
            "substate_no_fuel",
            "substate_door_open",
            "substate_heating_up",
            "substate_check_burn_cup",
        ]

    @property
    def native_value(self) -> str | None:
        """Return the substate translation key."""
        if self.coordinator.data and "operating" in self.coordinator.data:
            state = self.coordinator.data["operating"].get("state", "")
            substate = self.coordinator.data["operating"].get("substate", "")
            
            # Check for combined state_substate first
            combined_key = f"{state}_{substate}"
            if combined_key in SUBSTATE_NAMES:
                return SUBSTATE_NAMES[combined_key]
            # Fall back to state only
            return SUBSTATE_NAMES.get(state, "substate_unknown")
        return None


class AduroMainStatusSensor(AduroSensorBase):
    """Sensor for main status text."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "status_main", "status_main")
        self._attr_icon = "mdi:information"

    @property
    def native_value(self) -> str | None:
        """Return the main status text."""
        if not self.coordinator.data or "operating" not in self.coordinator.data:
            return None
        
        state = self.coordinator.data["operating"].get("state", "")
        heatlevel = self.coordinator.data["operating"].get("heatlevel", 1)
        
        # Get translation key
        state_key = STATE_NAMES.get(state)
        
        # Log warning for unknown states
        if state and state_key is None:
            _LOGGER.warning(
                "Unknown stove state detected: %s - Please report this to the integration developer",
                state
            )
        
        # For now, use display version as Home Assistant doesn't support 
        # format strings in state translations yet
        if state_key:
            from .const import STATE_NAMES_DISPLAY
            status_template = STATE_NAMES_DISPLAY.get(state, f"Unknown State {state}")
        else:
            from .const import STATE_NAMES_DISPLAY
            status_template = STATE_NAMES_DISPLAY.get(state, f"Unknown State {state}")
        
        # Format with heatlevel if needed
        if "{heatlevel}" in status_template:
            heatlevel_display = HEAT_LEVEL_DISPLAY.get(heatlevel, str(heatlevel))
            return status_template.format(heatlevel=heatlevel_display)
        
        return status_template

    @property
    def icon(self) -> str:
        """Return icon based on operation mode."""
        if not self.coordinator.data or "status" not in self.coordinator.data:
            return "mdi:help-circle"
        
        mode = self.coordinator.data["status"].get("operation_mode", 0)
        if mode == 1:
            return "mdi:thermometer"
        elif mode == 0:
            return "mdi:fire"
        else:
            return "mdi:campfire"


class AduroSubStatusSensor(AduroSensorBase):
    """Sensor for sub status text with live timer countdown."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "status_sub", "status_sub")
        self._attr_icon = "mdi:information-outline"
        self._timer_update_task = None
        self._unsub_timer = None

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        # Use event helpers instead of a background task
        from homeassistant.helpers.event import async_track_time_interval
        from datetime import timedelta
        
        # Update every second when timer is active
        self._unsub_timer = async_track_time_interval(
            self.hass,
            self._timer_tick,
            timedelta(seconds=1)
        )

    async def async_will_remove_from_hass(self) -> None:
        """When entity is being removed from hass."""
        # Cancel the timer
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None
        await super().async_will_remove_from_hass()

    async def _timer_tick(self, now=None):
        """Timer tick callback."""
        try:
            # Only update if timer is active
            if self._should_update_timer():
                self.async_write_ha_state()
        except Exception as err:
            _LOGGER.error("Error in timer tick: %s", err)

    def _should_update_timer(self) -> bool:
        """Check if timer is active and needs updating."""
        if not self.coordinator.data or "operating" not in self.coordinator.data:
            return False
        
        state = self.coordinator.data["operating"].get("state")
        
        # Timer is active during state 2 or 4
        return state in ["2", "4"]

    def _get_live_remaining_time(self, state: str) -> int | None:
        """Calculate live remaining time for current state."""
        from datetime import datetime
        from .const import TIMER_STARTUP_1, TIMER_STARTUP_2
        
        try:
            if state == "2" and self.coordinator._timer_startup_1_started:
                elapsed = (datetime.now() - self.coordinator._timer_startup_1_started).total_seconds()
                return max(0, TIMER_STARTUP_1 - int(elapsed))
            
            elif state == "4" and self.coordinator._timer_startup_2_started:
                elapsed = (datetime.now() - self.coordinator._timer_startup_2_started).total_seconds()
                return max(0, TIMER_STARTUP_2 - int(elapsed))
        except (TypeError, AttributeError) as err:
            _LOGGER.debug("Error calculating live timer: %s", err)
        
        return None

    @property
    def native_value(self) -> str | None:
        """Return the sub status text with live timer countdown."""
        if not self.coordinator.data or "operating" not in self.coordinator.data:
            return None
        
        state = self.coordinator.data["operating"].get("state", "")
        substate = self.coordinator.data["operating"].get("substate", "")
        
        # Check for combined state_substate first
        combined_key = f"{state}_{substate}"
        if combined_key in SUBSTATE_NAMES:
            from .const import SUBSTATE_NAMES_DISPLAY
            status = SUBSTATE_NAMES_DISPLAY.get(combined_key, f"Unknown State {state}/{substate}")
        else:
            # Fall back to state only
            from .const import SUBSTATE_NAMES_DISPLAY
            status = SUBSTATE_NAMES_DISPLAY.get(state, f"Unknown State {state}")
            
            # Log warning for unknown substates
            if state and state not in SUBSTATE_NAMES_DISPLAY:
                _LOGGER.warning(
                    "Unknown stove substate detected: state=%s, substate=%s - Please report this to the integration developer",
                    state, substate
                )
        
        # Add LIVE timer info if applicable
        if state in ["2", "4"]:
            remaining = self._get_live_remaining_time(state)
            if remaining is not None:
                minutes = remaining // 60
                seconds = remaining % 60
                return f"{status} ({minutes:02d}:{seconds:02d})"
        
        return status


# =============================================================================
# Temperature Sensors
# =============================================================================

class AduroBoilerTempSensor(AduroSensorBase):
    """Sensor for boiler/room temperature."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "boiler_temp", "boiler_temp")
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> float | None:
        """Return the temperature."""
        if self.coordinator.data and "operating" in self.coordinator.data:
            return self.coordinator.data["operating"].get("boiler_temp")
        return None


class AduroBoilerRefSensor(AduroSensorBase):
    """Sensor for boiler reference temperature."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "boiler_ref", "boiler_ref")
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> float | None:
        """Return the reference temperature."""
        if self.coordinator.data and "operating" in self.coordinator.data:
            return self.coordinator.data["operating"].get("boiler_ref")
        return None


class AduroSmokeTempSensor(AduroSensorBase):
    """Sensor for smoke temperature."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "smoke_temp", "smoke_temp")
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> float | None:
        """Return the smoke temperature."""
        if self.coordinator.data and "operating" in self.coordinator.data:
            return self.coordinator.data["operating"].get("smoke_temp")
        return None


class AduroShaftTempSensor(AduroSensorBase):
    """Sensor for shaft temperature."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "shaft_temp", "shaft_temp")
        self._attr_device_class = SensorDeviceClass.TEMPERATURE
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> float | None:
        """Return the shaft temperature."""
        if self.coordinator.data and "operating" in self.coordinator.data:
            return self.coordinator.data["operating"].get("shaft_temp")
        return None


# =============================================================================
# Power Sensors
# =============================================================================

class AduroPowerKwSensor(AduroSensorBase):
    """Sensor for power in kW."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "power_kw", "power_kw")
        self._attr_device_class = SensorDeviceClass.POWER
        self._attr_native_unit_of_measurement = UnitOfPower.KILO_WATT
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> float | None:
        """Return the power in kW."""
        if self.coordinator.data and "operating" in self.coordinator.data:
            return self.coordinator.data["operating"].get("power_kw")
        return None


# =============================================================================
# Carbon Monoxide Sensors
# =============================================================================

class AduroCarbonMonoxideSensor(AduroSensorBase):
    """Sensor for carbon monoxide level."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "carbon_monoxide", "carbon_monoxide")
        self._attr_native_unit_of_measurement = "ppm"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:molecule-co"

    @property
    def native_value(self) -> float | None:
        """Return the carbon monoxide level in ppm (multiplied by 10)."""
        if self.coordinator.data and "operating" in self.coordinator.data:
            co_value = round(self.coordinator.data["operating"].get("carbon_monoxide"), 0)
            if co_value is not None:
                return int(round(co_value * 10, 0))
        return None


class AduroCarbonMonoxideYellowSensor(AduroSensorBase):
    """Sensor for carbon monoxide yellow threshold."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "carbon_monoxide_yellow", "carbon_monoxide_yellow")
        self._attr_native_unit_of_measurement = "ppm"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:molecule-co"

    @property
    def native_value(self) -> float | None:
        """Return the carbon monoxide yellow threshold in ppm."""
        if self.coordinator.data and "operating" in self.coordinator.data:
            return int(round(self.coordinator.data["operating"].get("carbon_monoxide_yellow"), 0))
        return None


class AduroCarbonMonoxideRedSensor(AduroSensorBase):
    """Sensor for carbon monoxide red threshold."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "carbon_monoxide_red", "carbon_monoxide_red")
        self._attr_native_unit_of_measurement = "ppm"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:molecule-co"

    @property
    def native_value(self) -> float | None:
        """Return the carbon monoxide red threshold in ppm."""
        if self.coordinator.data and "operating" in self.coordinator.data:
            return int(round(self.coordinator.data["operating"].get("carbon_monoxide_red"), 0))
        return None


# =============================================================================
# Operation Sensors
# =============================================================================

class AduroOperationModeSensor(AduroSensorBase):
    """Sensor for operation mode."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "operation_mode", "operation_mode")
        self._attr_state_class = SensorStateClass.MEASUREMENT

    @property
    def native_value(self) -> int | None:
        """Return the operation mode."""
        if self.coordinator.data and "status" in self.coordinator.data:
            return self.coordinator.data["status"].get("operation_mode")
        return None

    @property
    def icon(self) -> str:
        """Return icon based on operation mode."""
        mode = self.native_value
        if mode == 1:
            return "mdi:thermometer"
        elif mode == 0:
            return "mdi:fire"
        elif mode == 2:
            return "mdi:campfire"
        return "mdi:help-circle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        mode = self.native_value
        mode_names = {0: "Heat Level", 1: "Temperature", 2: "Wood"}
        return {
            "mode_name": mode_names.get(mode, "Unknown"),
        }


# =============================================================================
# Pellet Sensors
# =============================================================================

class AduroPelletAmountSensor(AduroSensorBase):
    """Sensor for pellet amount remaining."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "pellet_amount", "pellet_amount")
        self._attr_device_class = SensorDeviceClass.WEIGHT
        self._attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:grain"

    @property
    def native_value(self) -> float | None:
        """Return the pellet amount."""
        if self.coordinator.data and "pellets" in self.coordinator.data:
            return round(self.coordinator.data["pellets"].get("amount", 0), 1)
        return None


class AduroPelletPercentageSensor(AduroSensorBase):
    """Sensor for pellet percentage remaining."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "pellet_percentage", "pellet_percentage")
        self._attr_native_unit_of_measurement = PERCENTAGE
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_icon = "mdi:percent"

    @property
    def native_value(self) -> float | None:
        """Return the pellet percentage."""
        if self.coordinator.data and "pellets" in self.coordinator.data:
            return round(self.coordinator.data["pellets"].get("percentage", 0), 0)
        return None


class AduroPelletConsumedSensor(AduroSensorBase):
    """Sensor for consumed pellets."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "pellet_consumed", "pellet_consumed")
        self._attr_device_class = SensorDeviceClass.WEIGHT
        self._attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_icon = "mdi:grain"

    @property
    def native_value(self) -> float | None:
        """Return the consumed pellets."""
        if self.coordinator.data and "pellets" in self.coordinator.data:
            return round(self.coordinator.data["pellets"].get("consumed", 0), 1)
        return None


class AduroPelletConsumptionTotalSensor(AduroSensorBase):
    """Sensor for total pellet consumption from stove."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "consumption_total", "consumption_total")
        self._attr_device_class = SensorDeviceClass.WEIGHT
        self._attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_icon = "mdi:grain"

    @property
    def native_value(self) -> float | None:
        """Return the total consumption."""
        if self.coordinator.data and "status" in self.coordinator.data:
            return round(self.coordinator.data["status"].get("consumption_total", 0), 0)
        return None


class AduroPelletRefillCounterSensor(AduroSensorBase):
    """Sensor for total pellet consumption since last cleaning."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "consumption_since_cleaning", "consumption_since_cleaning")
        self._attr_device_class = SensorDeviceClass.WEIGHT
        self._attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_icon = "mdi:counter"

    @property
    def native_value(self) -> float | None:
        """Return the total consumption since last cleaning."""
        if self.coordinator.data and "pellets" in self.coordinator.data:
            return round(self.coordinator.data["pellets"].get("consumed_total", 0), 1)
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data or "pellets" not in self.coordinator.data:
            return {}
        
        pellets = self.coordinator.data["pellets"]
        
        return {
            "consumed_since_refill": round(pellets.get("consumed", 0), 1),
            "consumed_since_cleaning": round(pellets.get("consumed_total", 0), 1),
            "pellet_capacity": pellets.get("capacity", 0),
        }


# =============================================================================
# Consumption Sensors
# =============================================================================

class AduroConsumptionDaySensor(AduroSensorBase):
    """Sensor for today's consumption."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "consumption_day", "consumption_day")
        self._attr_device_class = SensorDeviceClass.WEIGHT
        self._attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_icon = "mdi:grain"

    @property
    def native_value(self) -> float | None:
        """Return today's consumption."""
        current_value = None
        if self.coordinator.data and "consumption" in self.coordinator.data:
            current_value = self.coordinator.data["consumption"].get("day")
        return self._get_cached_value(current_value)


class AduroConsumptionYesterdaySensor(AduroSensorBase):
    """Sensor for yesterday's consumption."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "consumption_yesterday", "consumption_yesterday")
        self._attr_device_class = SensorDeviceClass.WEIGHT
        self._attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:grain"

    @property
    def native_value(self) -> float | None:
        """Return yesterday's consumption."""
        current_value = None
        if self.coordinator.data and "consumption" in self.coordinator.data:
            current_value = self.coordinator.data["consumption"].get("yesterday")
        return self._get_cached_value(current_value)


class AduroConsumptionMonthSensor(AduroSensorBase):
    """Sensor for this month's consumption."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "consumption_month", "consumption_month")
        self._attr_device_class = SensorDeviceClass.WEIGHT
        self._attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_icon = "mdi:grain"

    @property
    def native_value(self) -> float | None:
        """Return this month's consumption."""
        current_value = None
        if self.coordinator.data and "consumption" in self.coordinator.data:
            current_value = self.coordinator.data["consumption"].get("month")
        return self._get_cached_value(current_value)


class AduroConsumptionYearSensor(AduroSensorBase):
    """Sensor for this year's consumption."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "consumption_year", "consumption_year")
        self._attr_device_class = SensorDeviceClass.WEIGHT
        self._attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS
        self._attr_state_class = SensorStateClass.TOTAL_INCREASING
        self._attr_icon = "mdi:grain"

    @property
    def native_value(self) -> float | None:
        """Return this year's consumption."""
        current_value = None
        if self.coordinator.data and "consumption" in self.coordinator.data:
            current_value = self.coordinator.data["consumption"].get("year")
        return self._get_cached_value(current_value)


class AduroMonthlyHistorySensor(AduroSensorBase):
    """Sensor showing monthly consumption history."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "monthly_history", "monthly_history")
        self._attr_icon = "mdi:grain"

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if not super().available:
            return False
        # Check if we have consumption data
        if not self.coordinator.data:
            return False
        if "consumption" not in self.coordinator.data:
            return False
        return True

    @property
    def native_value(self) -> str | None:
        """Return current month's consumption."""
        if not self.coordinator.data or "consumption" not in self.coordinator.data:
            return None
        consumption = self.coordinator.data["consumption"]
        month_value = consumption.get("month", 0)
        return str(round(month_value, 2)) if month_value else "0"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return all monthly data as attributes."""
        if not self.coordinator.data or "consumption" not in self.coordinator.data:
            return {}
        
        consumption = self.coordinator.data["consumption"]
        history = consumption.get("monthly_history", {})
        
        if not history:
            return {}
        
        attrs = dict(history)
        # Add year total
        attrs["year_total"] = round(sum(history.values()), 2)
        
        # Add historical snapshots for comparison
        snapshots = consumption.get("monthly_snapshots", {})
        if snapshots:
            attrs["snapshots"] = snapshots
        
        return attrs
        
class AduroYearlyHistorySensor(AduroSensorBase):
    """Sensor showing yearly consumption history."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "yearly_history", "yearly_history")
        self._attr_icon = "mdi:grain"

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if not super().available:
            return False
        # Check if we have consumption data
        if not self.coordinator.data:
            return False
        if "consumption" not in self.coordinator.data:
            return False
        return True

    @property
    def native_value(self) -> str | None:
        """Return current year's consumption."""
        if not self.coordinator.data or "consumption" not in self.coordinator.data:
            return None
        consumption = self.coordinator.data["consumption"]
        year_value = consumption.get("year", 0)
        return str(round(year_value, 2)) if year_value else "0"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return all yearly data as attributes."""
        if not self.coordinator.data or "consumption" not in self.coordinator.data:
            return {}
        
        consumption = self.coordinator.data["consumption"]
        history = consumption.get("yearly_history", {})
        
        if not history:
            return {}
        
        return history
        

class AduroYearOverYearSensor(AduroSensorBase):
    """Sensor showing year-over-year consumption comparison."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "year_over_year", "year_over_year")
        self._attr_icon = "mdi:grain"
  
    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if not super().available:
            return False
        if not self.coordinator.data or "consumption" not in self.coordinator.data:
            return False
        # Only available if we have year-over-year data
        consumption = self.coordinator.data["consumption"]
        return "year_over_year" in consumption

    @property
    def native_value(self) -> str | None:
        """Return the percentage change."""
        if not self.coordinator.data or "consumption" not in self.coordinator.data:
            return None
        
        consumption = self.coordinator.data["consumption"]
        yoy = consumption.get("year_over_year", {})
        
        if not yoy:
            return None
        
        percentage = yoy.get("percentage_change", 0)
        return f"{percentage:+.1f}%"

    @property
    def icon(self) -> str:
        """Return icon based on trend."""
        if not self.coordinator.data or "consumption" not in self.coordinator.data:
            return "mdi:chart-line"
        
        consumption = self.coordinator.data["consumption"]
        yoy = consumption.get("year_over_year", {})
        percentage = yoy.get("percentage_change", 0)
        
        if percentage > 10:
            return "mdi:trending-up"
        elif percentage < -10:
            return "mdi:trending-down"
        return "mdi:trending-neutral"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return year-over-year comparison details."""
        if not self.coordinator.data or "consumption" not in self.coordinator.data:
            return {}
        
        consumption = self.coordinator.data["consumption"]
        yoy = consumption.get("year_over_year", {})
        
        if not yoy:
            return {}
        
        # Also include all historical snapshots for reference
        snapshots = consumption.get("monthly_snapshots", {})
        attrs = dict(yoy)
        attrs["all_snapshots"] = snapshots
        
        return attrs

# =============================================================================
# Network Sensors
# =============================================================================

class AduroStoveIPSensor(AduroSensorBase):
    """Sensor for stove IP address."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "stove_ip", "stove_ip")
        self._attr_icon = "mdi:ip-network"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        """Return the stove IP."""
        return self.coordinator.stove_ip
        

class AduroRouterSSIDSensor(AduroSensorBase):
    """Sensor for router SSID."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "router_ssid", "router_ssid")
        self._attr_icon = "mdi:wifi"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        """Return the router SSID."""
        current_value = None
        if self.coordinator.data and "network" in self.coordinator.data:
            current_value = self.coordinator.data["network"].get("router_ssid")
        return self._get_cached_value(current_value)


class AduroStoveRSSISensor(AduroSensorBase):
    """Sensor for WiFi signal strength."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "stove_rssi", "stove_rssi")
        self._attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
        self._attr_native_unit_of_measurement = "dBm"
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_entity_category = EntityCategory.DIAGNOSTIC 

    @property
    def native_value(self) -> int | None:
        """Return the WiFi signal strength."""
        current_value = None
        if self.coordinator.data and "network" in self.coordinator.data:
            rssi = self.coordinator.data["network"].get("stove_rssi")
            if rssi:
                try:
                    current_value = int(rssi)
                except (ValueError, TypeError):
                    pass
        return self._get_cached_value(current_value)


class AduroStoveMacSensor(AduroSensorBase):
    """Sensor for stove MAC address."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "stove_mac", "stove_mac")
        self._attr_icon = "mdi:network"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        """Return the stove MAC address."""
        current_value = None
        if self.coordinator.data and "network" in self.coordinator.data:
            current_value = self.coordinator.data["network"].get("stove_mac")
        return self._get_cached_value(current_value)

class AduroFirmwareVersionSensor(AduroSensorBase):
    """Sensor for stove firmware version."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "firmware_version", "firmware_version")
        self._attr_icon = "mdi:chip"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def native_value(self) -> str | None:
        """Return the combined firmware version string."""
        if self.coordinator.firmware_version and self.coordinator.firmware_build:
            return f"{self.coordinator.firmware_version}.{self.coordinator.firmware_build}"
        elif self.coordinator.firmware_version:
            return self.coordinator.firmware_version
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs: dict[str, Any] = {}
        if self.coordinator.firmware_version:
            attrs["firmware_version"] = self.coordinator.firmware_version
        if self.coordinator.firmware_build:
            attrs["firmware_build"] = self.coordinator.firmware_build
        return attrs


# =============================================================================
# Runtime Sensors
# =============================================================================

class AduroOperatingTimeStoveSensor(AduroSensorBase):
    """Sensor for total stove operating time."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "operating_time_stove", "operating_time_stove")
        self._attr_icon = "mdi:clock"

    @property
    def native_value(self) -> str | None:
        """Return the operating time formatted as H:MM:SS or HH:MM:SS or HHH:MM:SS."""
        if self.coordinator.data and "operating" in self.coordinator.data:
            total_seconds = self.coordinator.data["operating"].get("operating_time_stove")
            if total_seconds is not None:
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                seconds = total_seconds % 60
                return f"{hours}:{minutes:02d}:{seconds:02d}"
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if self.coordinator.data and "operating" in self.coordinator.data:
            total_seconds = self.coordinator.data["operating"].get("operating_time_stove")
            if total_seconds is not None:
                return {
                    "total_seconds": total_seconds,
                    "total_hours": round(total_seconds / 3600, 2),
                }
        return {}


class AduroOperatingTimeAugerSensor(AduroSensorBase):
    """Sensor for auger operating time."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "operating_time_auger", "operating_time_auger")
        self._attr_icon = "mdi:clock"

    @property
    def native_value(self) -> str | None:
        """Return the auger operating time formatted as HHH:MM:SS."""
        if self.coordinator.data and "operating" in self.coordinator.data:
            total_seconds = self.coordinator.data["operating"].get("operating_time_auger")
            if total_seconds is not None:
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                seconds = total_seconds % 60
                return f"{hours}:{minutes:02d}:{seconds:02d}"
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if self.coordinator.data and "operating" in self.coordinator.data:
            total_seconds = self.coordinator.data["operating"].get("operating_time_auger")
            if total_seconds is not None:
                return {
                    "total_seconds": total_seconds,
                    "total_hours": round(total_seconds / 3600, 2),
                }
        return {}


class AduroOperatingTimeIgnitionSensor(AduroSensorBase):
    """Sensor for ignition operating time."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "operating_time_ignition", "operating_time_ignition")
        self._attr_icon = "mdi:clock"

    @property
    def native_value(self) -> str | None:
        """Return the ignition operating time formatted as HHH:MM:SS."""
        if self.coordinator.data and "operating" in self.coordinator.data:
            total_seconds = self.coordinator.data["operating"].get("operating_time_ignition")
            if total_seconds is not None:
                hours = total_seconds // 3600
                minutes = (total_seconds % 3600) // 60
                seconds = total_seconds % 60
                return f"{hours}:{minutes:02d}:{seconds:02d}"
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if self.coordinator.data and "operating" in self.coordinator.data:
            total_seconds = self.coordinator.data["operating"].get("operating_time_ignition")
            if total_seconds is not None:
                return {
                    "total_seconds": total_seconds,
                    "total_hours": round(total_seconds / 3600, 2),
                }
        return {}


# =============================================================================
# Calculated/Status Sensors
# =============================================================================


class AduroModeTransitionSensor(AduroSensorBase):
    """Sensor for mode transition state."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "mode_transition", "mode_transition")
        self._attr_icon = "mdi:state-machine"
        self._last_logged_value = None

    @property
    def native_value(self) -> str | None:
        """Return the mode transition state."""
        if self.coordinator.data and "calculated" in self.coordinator.data:
            value = self.coordinator.data["calculated"].get("mode_transition", "idle")
            return value
        return "idle"


class AduroChangeInProgressSensor(AduroSensorBase):
    """Sensor for change in progress status."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "change_in_progress", "change_in_progress")
        self._attr_icon = "mdi:sync"
        self._last_logged_value = None

    @property
    def native_value(self) -> str | None:
        """Return true/false as string."""
        if self.coordinator.data and "calculated" in self.coordinator.data:
            in_progress = self.coordinator.data["calculated"].get("change_in_progress", False)
            value = "true" if in_progress else "false"            
            return value
        return "false"


class AduroDisplayFormatSensor(AduroSensorBase):
    """Sensor for formatted display string."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "display_format", "display_format")
        self._attr_translation_key = "display_format"
        self._translations_loaded = False
        self._translations = {}

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        await self._load_translations()

    async def _load_translations(self) -> None:
        """Load translations for the current language."""
        try:
            language = self.hass.config.language
            self._translations = await trans_helper.async_get_translations(
                self.hass,
                language,
                "entity",
                {DOMAIN},
            )
            self._translations_loaded = True
            _LOGGER.debug("Loaded translations for language: %s", language)
        except Exception as err:
            _LOGGER.warning("Failed to load translations: %s", err)
            self._translations_loaded = False

    def _get_translation(self, key: str) -> str | None:
        """Get translation for a key."""
        full_key = f"component.{DOMAIN}.entity.sensor.display_format.state_attributes.{key}.name"
        return self._translations.get(full_key)

    @property
    def native_value(self) -> str | None:
        """Return the formatted display string."""
        if not self.coordinator.data or "calculated" not in self.coordinator.data:
            return None
        
        calculated = self.coordinator.data["calculated"]
        display_target_type = calculated.get("display_target_type")
        display_target = calculated.get("display_target")
        current_temperature = calculated.get("current_temperature")
        
        # Determine which translation key to use
        if display_target_type == "heatlevel":
            trans_key = "heatlevel_format"
            fallback = f"Heat Level (room temp.): {display_target} ({current_temperature})°C"
        elif display_target_type == "temperature":
            trans_key = "temperature_format"
            fallback = f"Target temp. (room temp.): {display_target} ({current_temperature})°C"
        else:
            trans_key = "wood_mode"
            fallback = "Wood Mode"
        
        # Try to get translated string
        if self._translations_loaded:
            template = self._get_translation(trans_key)
            if template:
                try:
                    # Replace placeholders if present
                    if display_target_type != "wood":
                        return template.format(
                            display_target=display_target,
                            current_temperature=current_temperature
                        )
                    return template
                except (KeyError, ValueError) as err:
                    _LOGGER.debug("Failed to format translation: %s", err)
        
        # Return fallback (English)
        return fallback

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data or "calculated" not in self.coordinator.data:
            return {}
        
        calculated = self.coordinator.data["calculated"]
        
        return {
            "display_target": calculated.get("display_target"),
            "target_type": calculated.get("display_target_type"),
            "current_temperature": calculated.get("current_temperature"),
        }


class AduroDisplayTargetSensor(AduroSensorBase):
    """Sensor for display target value."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "display_target", "display_target")

    @property
    def native_value(self) -> int | float | None:
        """Return the display target."""
        if self.coordinator.data and "calculated" in self.coordinator.data:
            return self.coordinator.data["calculated"].get("display_target")
        return None

    @property
    def icon(self) -> str:
        """Return icon based on target type."""
        if self.coordinator.data and "calculated" in self.coordinator.data:
            target_type = self.coordinator.data["calculated"].get("display_target_type", "")
            if target_type == "temperature":
                return "mdi:thermometer"
            elif target_type == "heatlevel":
                return "mdi:fire"
            elif target_type == "wood":
                return "mdi:campfire"
        return "mdi:help-circle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if self.coordinator.data and "calculated" in self.coordinator.data:
            target_type = self.coordinator.data["calculated"].get("display_target_type", "")
            target_value = self.coordinator.data["calculated"].get("display_target")
            
            attrs = {
                "target_type": target_type,
            }
            
            # Add formatted display for heatlevel
            if target_type == "heatlevel" and target_value:
                attrs["display_text"] = HEAT_LEVEL_DISPLAY.get(int(target_value), str(target_value))
            
            return attrs
        return {}


class AduroAppChangeDetectedSensor(AduroSensorBase):
    """Sensor for app change detection."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "app_change_detected", "app_change_detected")
        self._attr_icon = "mdi:cellphone-arrow-down"

    @property
    def native_value(self) -> str | None:
        """Return true/false as string."""
        if self.coordinator.data:
            detected = self.coordinator.data.get("app_change_detected", False)
            return "true" if detected else "false"
        return "false"

# =============================================================================
# Temperature alert Sensors
# =============================================================================

class AduroHighSmokeTempAlertSensor(AduroSensorBase):
    """Binary sensor for high smoke temperature alert."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "high_smoke_temp_alert", "high_smoke_temp_alert")
        self._attr_icon = "mdi:alert-circle"

    @property
    def native_value(self) -> str:
        """Return alert status as text."""
        if self.coordinator.data and "alerts" in self.coordinator.data:
            alert_info = self.coordinator.data["alerts"].get("high_smoke_temp_alert", {})
            return "Alert" if alert_info.get("active", False) else "OK"
        return "OK"

    @property
    def icon(self) -> str:
        """Return icon based on alert state."""
        if self.coordinator.data and "alerts" in self.coordinator.data:
            alert_info = self.coordinator.data["alerts"].get("high_smoke_temp_alert", {})
            if alert_info.get("active", False):
                return "mdi:alert-circle"
        return "mdi:alert-circle-check-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data or "alerts" not in self.coordinator.data:
            return {}
        
        alert_info = self.coordinator.data["alerts"].get("high_smoke_temp_alert", {})
        
        attrs = {
            "alert_active": alert_info.get("active", False),
            "current_temp": alert_info.get("current_temp", 0),
            "threshold_temp": alert_info.get("threshold_temp", 0),
            "threshold_duration_seconds": alert_info.get("threshold_duration", 0),
            "threshold_duration_minutes": round(alert_info.get("threshold_duration", 0) / 60, 1),
        }
        
        # Add time information if available
        time_info = alert_info.get("time_info")
        if time_info:
            attrs["time_state"] = time_info["state"]
            attrs["elapsed_seconds"] = time_info["elapsed"]
            attrs["elapsed_minutes"] = round(time_info["elapsed"] / 60, 1)
            
            if time_info["state"] == "building":
                attrs["remaining_seconds"] = time_info["remaining"]
                attrs["remaining_minutes"] = round(time_info["remaining"] / 60, 1)
                attrs["progress_percent"] = round(
                    (time_info["elapsed"] / alert_info.get("threshold_duration", 1)) * 100, 1
                )
            elif time_info["state"] == "exceeded":
                attrs["exceeded_by_seconds"] = time_info["exceeded_by"]
                attrs["exceeded_by_minutes"] = round(time_info["exceeded_by"] / 60, 1)
        
        return attrs


class AduroLowWoodTempAlertSensor(AduroSensorBase):
    """Binary sensor for low wood mode temperature alert."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "low_wood_temp_alert", "low_wood_temp_alert")
        self._attr_icon = "mdi:alert-circle"

    @property
    def native_value(self) -> str:
        """Return alert status as text."""
        if self.coordinator.data and "alerts" in self.coordinator.data:
            alert_info = self.coordinator.data["alerts"].get("low_wood_temp_alert", {})
            # Only show alert if in wood mode
            if alert_info.get("in_wood_mode", False) and alert_info.get("active", False):
                return "Alert"
            elif alert_info.get("in_wood_mode", False):
                return "Monitoring"
        return "N/A"

    @property
    def icon(self) -> str:
        """Return icon based on alert state."""
        if self.coordinator.data and "alerts" in self.coordinator.data:
            alert_info = self.coordinator.data["alerts"].get("low_wood_temp_alert", {})
            if alert_info.get("in_wood_mode", False):
                if alert_info.get("active", False):
                    return "mdi:alert-circle"
                return "mdi:thermometer-low"
        return "mdi:help-circle-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data or "alerts" not in self.coordinator.data:
            return {}
        
        alert_info = self.coordinator.data["alerts"].get("low_wood_temp_alert", {})
        
        attrs = {
            "alert_active": alert_info.get("active", False),
            "in_wood_mode": alert_info.get("in_wood_mode", False),
            "current_temp": alert_info.get("current_temp", 0),
            "threshold_temp": alert_info.get("threshold_temp", 0),
            "threshold_duration_seconds": alert_info.get("threshold_duration", 0),
            "threshold_duration_minutes": round(alert_info.get("threshold_duration", 0) / 60, 1),
        }
        
        # Add time information if available
        time_info = alert_info.get("time_info")
        if time_info:
            attrs["time_state"] = time_info["state"]
            attrs["elapsed_seconds"] = time_info["elapsed"]
            attrs["elapsed_minutes"] = round(time_info["elapsed"] / 60, 1)
            
            if time_info["state"] == "building":
                attrs["remaining_seconds"] = time_info["remaining"]
                attrs["remaining_minutes"] = round(time_info["remaining"] / 60, 1)
                attrs["progress_percent"] = round(
                    (time_info["elapsed"] / alert_info.get("threshold_duration", 1)) * 100, 1
                )
            elif time_info["state"] == "exceeded":
                attrs["exceeded_by_seconds"] = time_info["exceeded_by"]
                attrs["exceeded_by_minutes"] = round(time_info["exceeded_by"] / 60, 1)
        
        return attrs
