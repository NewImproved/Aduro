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
        AduroMainStateSensor(coordinator, entry),
        AduroSubstateSensor(coordinator, entry),
        
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
        AduroYearOverYearSensor(coordinator, entry),

        # Pellet depletion prediction
        AduroPelletDepletionSensor(coordinator, entry),
        
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

class AduroMainStateSensor(AduroSensorBase):
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
        
        # Build the full translation key - NOTE: The path is "state.state.{key}" not "state_disp.state.{key}"
        full_key = f"component.{DOMAIN}.entity.sensor.state.state.{translation_key}"
        
        # Try to get translation
        if self._translations_loaded and full_key in self._translations:
            template = self._translations[full_key]
            try:
                # Format with Roman numeral heatlevel
                return template.format(heatlevel_roman=heatlevel_roman)
            except (KeyError, ValueError):
                return template
        
        # Fallback to display names from const.py
        fallback = STATE_NAMES_DISPLAY.get(translation_key.replace("state_", ""), translation_key)
        
        # Format fallback if it contains placeholder
        if "{heatlevel}" in fallback:
            fallback = fallback.format(heatlevel=heatlevel_roman)
        
        return fallback

    @property
    def native_value(self) -> str | None:
        """Return the translated and formatted state."""
        if not self.coordinator.data or "operating" not in self.coordinator.data:
            return None
        
        state = self.coordinator.data["operating"].get("state")
        heatlevel = self.coordinator.data["operating"].get("heatlevel", 1)
        
        # Get translation key from const
        translation_key = STATE_NAMES.get(state, "state_unknown")
        
        # Log warning for unknown states
        if state and translation_key is None:
            _LOGGER.warning(
                "Unknown stove state detected: %s - Please report this to the integration developer",
                state
            )

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
    """Sensor for stove substate with live timer countdown."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "substate", "substate")
        self._attr_icon = "mdi:state-machine"
        self._timer_update_task = None
        self._unsub_timer = None
        self._translations = {}
        self._translations_loaded = False

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        await self._load_translations()
        
        # Use event helpers for timer updates
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
        substate = self.coordinator.data["operating"].get("substate")
        
        # Timer is active during state 2, 4, or 14 (substate 0)
        if state in ["2", "4"]:
            return True
        if state == "14" and substate == "0":
            return True
        return False

    def _get_live_remaining_time(self, state: str, substate: str) -> int | None:
        """Calculate live remaining time for current state."""
        from datetime import datetime
        from .const import TIMER_STARTUP_1, TIMER_STARTUP_2, TIMER_SHUTDOWN
        
        try:
            if state == "2" and self.coordinator._timer_startup_1_started:
                elapsed = (datetime.now() - self.coordinator._timer_startup_1_started).total_seconds()
                return max(0, TIMER_STARTUP_1 - int(elapsed))
            
            elif state == "4" and self.coordinator._timer_startup_2_started:
                elapsed = (datetime.now() - self.coordinator._timer_startup_2_started).total_seconds()
                return max(0, TIMER_STARTUP_2 - int(elapsed))
            
            # Shutdown timer for state 14, substate 0
            elif state == "14" and substate == "0" and self.coordinator._timer_shutdown_started:
                elapsed = (datetime.now() - self.coordinator._timer_shutdown_started).total_seconds()
                return max(0, TIMER_SHUTDOWN - int(elapsed))
        except (TypeError, AttributeError) as err:
            _LOGGER.debug("Error calculating live timer: %s", err)
        
        return None

    def _get_translated_text(self, translation_key: str) -> str:
        """Get translated text for a key."""
        full_key = f"component.{DOMAIN}.entity.sensor.substate.state.{translation_key}"
        
        if self._translations_loaded and full_key in self._translations:
            return self._translations[full_key]
        
        # Fallback to display names from const.py
        return SUBSTATE_NAMES_DISPLAY.get(translation_key.replace("substate_", ""), translation_key)

    @property
    def native_value(self) -> str | None:
        """Return the substate with live timer countdown when applicable."""
        if not self.coordinator.data or "operating" not in self.coordinator.data:
            return None
        
        state = self.coordinator.data["operating"].get("state", "")
        substate = self.coordinator.data["operating"].get("substate", "")
        
        # Check for combined state_substate first
        combined_key = f"{state}_{substate}"
        if combined_key in SUBSTATE_NAMES:
            translation_key = SUBSTATE_NAMES[combined_key]
        else:
            # Fall back to state only
            translation_key = SUBSTATE_NAMES.get(state, "substate_unknown")
        
        # Log warning for unknown states
        if state and translation_key is None:
            _LOGGER.warning(
                "Unknown stove substate detected: state=%s, substate=%s - Please report this to the integration developer",
                state, substate
            )

        # Get translated text
        status_text = self._get_translated_text(translation_key)
        
        # Add LIVE timer info if applicable
        if state in ["2", "4"] or (state == "14" and substate == "0"):
            remaining = self._get_live_remaining_time(state, substate)
            if remaining is not None and remaining > 0:
                minutes = remaining // 60
                seconds = remaining % 60
                return f"{status_text} ({minutes:02d}:{seconds:02d})"
        
        return status_text

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs = {}
        
        if not self.coordinator.data or "operating" not in self.coordinator.data:
            return attrs
        
        state = self.coordinator.data["operating"].get("state", "")
        substate = self.coordinator.data["operating"].get("substate", "")
        
        # Add raw state info
        attrs["raw_state"] = state
        attrs["raw_substate"] = substate
        
        return attrs


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
        self._attr_icon = "mdi:grain"

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
        # Always available if we have consumption data
        return True

    def _get_comparison_data(self) -> dict[str, Any] | None:
        """Calculate year-over-year comparison with same-period logic."""
        from datetime import date
        
        consumption = self.coordinator.data["consumption"]
        snapshots = consumption.get("monthly_snapshots", {})
        
        today = date.today()
        current_year = today.year
        current_month = today.month
        current_day = today.day
        
        month_names = [
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december"
        ]
        current_month_name = month_names[current_month - 1]
        
        # Get current month's consumption (month-to-date)
        current_snapshot_key = f"{current_year}_{current_month_name}"
        current_month_value = snapshots.get(current_snapshot_key, 0)
        
        # Look for last year's same month COMPLETE data
        last_year = current_year - 1
        last_year_snapshot_key = f"{last_year}_{current_month_name}"
        last_year_complete_month = snapshots.get(last_year_snapshot_key)
        
        if last_year_complete_month is not None and last_year_complete_month > 0:
            # We have complete data from last year's same month
            # Calculate what last year would have been at the same day of month
            
            # Get number of days in last year's month
            import calendar
            days_in_last_year_month = calendar.monthrange(last_year, current_month)[1]
            
            # Calculate daily average from last year's complete month
            daily_avg_last_year = last_year_complete_month / days_in_last_year_month
            
            # Estimate what last year was at the same day
            last_year_same_period = daily_avg_last_year * current_day
            
            # Calculate difference and percentage
            difference = current_month_value - last_year_same_period
            
            if last_year_same_period > 0:
                percentage_change = (difference / last_year_same_period) * 100
            else:
                percentage_change = 100.0 if current_month_value > 0 else 0.0
            
            return {
                "current_month": current_month_name,
                "current_year_value": round(current_month_value, 2),
                "last_year_same_period": round(last_year_same_period, 2),
                "last_year_complete_month": round(last_year_complete_month, 2),
                "difference": round(difference, 2),
                "percentage_change": round(percentage_change, 1),
                "comparison_day": current_day,
                "comparison_type": "same_period",
            }
        
        # No historical data available for this month
        return None

    @property
    def native_value(self) -> str | None:
        """Return the percentage change."""
        if not self.coordinator.data or "consumption" not in self.coordinator.data:
            return None
        
        comparison = self._get_comparison_data()
        
        if comparison:
            percentage = comparison.get("percentage_change", 0)
            return f"{percentage:+.1f}%"
        
        # No historical data
        return "No data"

    @property
    def icon(self) -> str:
        """Return icon based on trend."""
        if not self.coordinator.data or "consumption" not in self.coordinator.data:
            return "mdi:chart-line"
        
        comparison = self._get_comparison_data()
        
        if comparison:
            percentage = comparison.get("percentage_change", 0)
            
            if percentage > 10:
                return "mdi:trending-up"
            elif percentage < -10:
                return "mdi:trending-down"
            return "mdi:trending-neutral"
        
        # No historical data
        return "mdi:chart-line"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return year-over-year comparison details."""
        if not self.coordinator.data or "consumption" not in self.coordinator.data:
            return {}
        
        consumption = self.coordinator.data["consumption"]
        comparison = self._get_comparison_data()
        
        if comparison:
            # Include snapshots for reference
            snapshots = consumption.get("monthly_snapshots", {})
            attrs = dict(comparison)
            attrs["all_snapshots"] = snapshots
            return attrs
        
        # No historical data available
        from datetime import date
        month_names = [
            "january", "february", "march", "april", "may", "june",
            "july", "august", "september", "october", "november", "december"
        ]
        current_month_name = month_names[date.today().month - 1]
        current_year = date.today().year
        last_year = current_year - 1
        
        return {
            "current_month": current_month_name,
            "note": f"No data available for {current_month_name} {last_year}",
            "all_snapshots": consumption.get("monthly_snapshots", {}),
        }

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
        self._attr_icon = "mdi:thermometer-alert"

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
        self._attr_icon = "mdi:thermometer-low"

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

# =============================================================================
# Pellet Depletion Prediction Sensor
# =============================================================================

class AduroPelletDepletionSensor(AduroSensorBase):
    """Sensor for pellet depletion prediction."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "pellet_depletion", "pellet_depletion")
        self._attr_icon = "mdi:clock-alert-outline"

    @property
    def native_value(self) -> str | None:
        """Return the datetime when pellets will be depleted."""
        prediction = self.coordinator.predict_pellet_depletion()
        
        if not prediction:
            return "N/A"
        
        status = prediction.get("status")
        
        if status == "insufficient_data":
            return "Insufficient data"
        elif status == "empty":
            return "Empty"
        elif status == "ok":
            depletion_dt = prediction.get("depletion_datetime")
            if depletion_dt:
                # Format as "2026-01-17 23:30"
                return depletion_dt.strftime("%Y-%m-%d %H:%M")
            return "Unknown"
        
        return "N/A"

    @property
    def icon(self) -> str:
        """Return icon based on prediction status."""
        prediction = self.coordinator.predict_pellet_depletion()
        
        if not prediction:
            return "mdi:help-circle-outline"
        
        status = prediction.get("status")
        
        if status == "empty":
            return "mdi:alert-circle"
        elif status == "insufficient_data":
            return "mdi:database-off-outline"
        elif status == "ok":
            confidence = prediction.get("confidence", "medium")
            if confidence == "high":
                return "mdi:clock-check-outline"
            elif confidence == "low":
                return "mdi:clock-alert-outline"
            else:
                return "mdi:clock-outline"
        
        return "mdi:clock-outline"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        # Always show learning status, even when stove is off
        learning_status = self.coordinator._get_learning_status()
        
        attrs = {
            "learning_heatlevel_1_hours": learning_status.get("heatlevel_1_hours", 0),
            "learning_heatlevel_2_hours": learning_status.get("heatlevel_2_hours", 0),
            "learning_heatlevel_3_hours": learning_status.get("heatlevel_3_hours", 0),
            "learning_waiting_periods": learning_status.get("waiting_periods_observed", 0),
            "learning_recent_data": learning_status.get("recent_data", False),
            "learning_sufficient_data": learning_status.get("sufficient_data", False),
            "learning_total_heating_obs": learning_status.get("total_heating_observations", 0),
            "learning_total_cooling_obs": learning_status.get("total_cooling_observations", 0),
        }

        # Add learning consumption tracker info
        attrs["learning_consumption_total"] = round(self.coordinator._learning_consumption_total, 2)
        if learning_status.get("total_heating_observations", 0) > 0:
            attrs["learning_avg_consumption_per_obs"] = round(
                self.coordinator._learning_consumption_total / learning_status.get("total_heating_observations", 1),
                2
            )
        
        # Add startup observation info
        startup_obs = self.coordinator._learning_data.get("startup_observations", {})
        attrs["learning_startup_count"] = startup_obs.get("count", 0)
        attrs["learning_startup_avg_consumption"] = round(startup_obs.get("avg_consumption", 0), 3)
        attrs["learning_startup_avg_duration"] = round(startup_obs.get("avg_duration", 0) / 60, 1)  # Convert to minutes
        
        # External temperature info (always show if configured)
        if self.coordinator._external_temp_sensor:
            attrs["external_temp_sensor"] = self.coordinator._external_temp_sensor
            external_temp = self.coordinator._get_external_temperature()
            if external_temp is not None:
                attrs["external_temp_value"] = round(external_temp, 1)
        
        # Get prediction data
        prediction = self.coordinator.predict_pellet_depletion()
        
        if not prediction:
            attrs["status"] = "not_available"
            attrs["message"] = "Stove is off or in wood mode"
            return attrs
        
        status = prediction.get("status")
        attrs["status"] = status
        
        if status == "insufficient_data":
            attrs.update({
                "message": "Collecting data. Need 5+ hours per heat level and 5+ waiting periods.",
            })
            return attrs
        
        if status == "empty":
            attrs.update({
                "depletion_datetime": prediction.get("depletion_datetime").isoformat() if prediction.get("depletion_datetime") else None,
                "message": "Pellets depleted",
            })
            return attrs
        
        if status == "ok":
            attrs.update({
                "time_remaining_seconds": prediction.get("time_remaining_seconds"),
                "time_remaining_hours": round(prediction.get("time_remaining_seconds", 0) / 3600, 1),
                #"depletion_datetime": prediction.get("depletion_datetime").isoformat() if prediction.get("depletion_datetime") else None,
                "time_remaining_formatted": prediction.get("time_remaining_formatted")  if prediction.get("time_remaining_formatted") else None,
                "confidence": prediction.get("confidence", "unknown"),
                "mode": prediction.get("mode", "unknown"),
            })
            
            # Mode-specific attributes
            if prediction.get("mode") == "heatlevel":
                attrs.update({
                    "current_heatlevel": prediction.get("current_heatlevel"),
                    "consumption_rate_kg_per_hour": prediction.get("consumption_rate"),
                })
            elif prediction.get("mode") == "temperature":
                attrs.update({
                    "cycles_remaining": prediction.get("cycles_remaining"),
                    "current_phase": prediction.get("current_phase"),
                    "shutdown_delta": prediction.get("shutdown_delta"),
                    "restart_delta": prediction.get("restart_delta"),
                })

                # Add shutdown/restart observation counts
                shutdown_data = self.coordinator._learning_data["shutdown_restart_deltas"]["shutdown"]
                restart_data = self.coordinator._learning_data["shutdown_restart_deltas"]["restart"]
                attrs["learning_shutdown_count"] = shutdown_data.get("count", 0)
                attrs["learning_restart_count"] = restart_data.get("count", 0)
        
        return attrs
