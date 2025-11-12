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
    ]

    async_add_entities(sensors)


class AduroSensorBase(CoordinatorEntity, SensorEntity):
    """Base class for Aduro sensors."""

    def __init__(
        self,
        coordinator: AduroCoordinator,
        entry: ConfigEntry,
        sensor_type: str,
        name: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entry = entry
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{entry.entry_id}_{sensor_type}"
        self._attr_name = name
        self._sensor_type = sensor_type
        self._last_valid_value = None

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

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "state", "State")
        self._attr_icon = "mdi:state-machine"

    @property
    def native_value(self) -> str | None:
        """Return the state."""
        if self.coordinator.data and "operating" in self.coordinator.data:
            return self.coordinator.data["operating"].get("state")
        return None


class AduroSubstateSensor(AduroSensorBase):
    """Sensor for stove substate."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "substate", "Substate")
        self._attr_icon = "mdi:state-machine"

    @property
    def native_value(self) -> str | None:
        """Return the substate."""
        if self.coordinator.data and "operating" in self.coordinator.data:
            return self.coordinator.data["operating"].get("substate")
        return None


class AduroMainStatusSensor(AduroSensorBase):
    """Sensor for main status text."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "status_main", "Status Main")
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
        
        # If we have a translation key, try to get translated text
        # Otherwise fall back to display version
        if state_key:
            # For now, use display version
            # TODO: Implement proper translation lookup when HA adds support
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
    """Sensor for sub status text."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "status_sub", "Status Sub")
        self._attr_icon = "mdi:information-outline"

    @property
    def native_value(self) -> str | None:
        """Return the sub status text."""
        if not self.coordinator.data or "operating" not in self.coordinator.data:
            return None
        
        state = self.coordinator.data["operating"].get("state", "")
        substate = self.coordinator.data["operating"].get("substate", "")
        
        # Check for combined state_substate first
        combined_key = f"{state}_{substate}"
        if combined_key in SUBSTATE_NAMES:
            # Get translation key
            # For now use display version
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
        
        # Add timer info if applicable
        if state == "2" and "timers" in self.coordinator.data:
            remaining = self.coordinator.data["timers"].get("startup_1_remaining", 0)
            minutes = remaining // 60
            seconds = remaining % 60
            return f"{status} ({minutes:02d}:{seconds:02d})"
        elif state == "4" and "timers" in self.coordinator.data:
            remaining = self.coordinator.data["timers"].get("startup_2_remaining", 0)
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
        super().__init__(coordinator, entry, "boiler_temp", "Boiler Temperature")
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
        super().__init__(coordinator, entry, "boiler_ref", "Boiler Reference")
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
        super().__init__(coordinator, entry, "smoke_temp", "Smoke Temperature")
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
        super().__init__(coordinator, entry, "shaft_temp", "Shaft Temperature")
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
        super().__init__(coordinator, entry, "power_kw", "Power")
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
# Operation Sensors
# =============================================================================

class AduroOperationModeSensor(AduroSensorBase):
    """Sensor for operation mode."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "operation_mode", "Operation Mode")

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
        super().__init__(coordinator, entry, "pellet_amount", "Pellet Amount")
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
        super().__init__(coordinator, entry, "pellet_percentage", "Pellet Percentage")
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
        super().__init__(coordinator, entry, "pellet_consumed", "Pellet Consumed")
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
        super().__init__(coordinator, entry, "consumption_total", "Consumption Total")
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
    """Sensor for pellet refill counter."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "refill_counter", "Refill Counter")
        self._attr_state_class = SensorStateClass.TOTAL
        self._attr_icon = "mdi:counter"

    @property
    def native_value(self) -> int | None:
        """Return the refill counter."""
        if self.coordinator.data and "pellets" in self.coordinator.data:
            return self.coordinator.data["pellets"].get("refill_counter", 0)
        return None


# =============================================================================
# Consumption Sensors
# =============================================================================

class AduroConsumptionDaySensor(AduroSensorBase):
    """Sensor for today's consumption."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "consumption_day", "Consumption Today")
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
        super().__init__(coordinator, entry, "consumption_yesterday", "Consumption Yesterday")
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
        super().__init__(coordinator, entry, "consumption_month", "Consumption This Month")
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
        super().__init__(coordinator, entry, "consumption_year", "Consumption This Year")
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


# =============================================================================
# Network Sensors
# =============================================================================

class AduroStoveIPSensor(AduroSensorBase):
    """Sensor for stove IP address."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "stove_ip", "Stove IP")
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
        super().__init__(coordinator, entry, "router_ssid", "Router SSID")
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
        super().__init__(coordinator, entry, "stove_rssi", "WiFi Signal")
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
        super().__init__(coordinator, entry, "stove_mac", "Stove MAC")
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
        super().__init__(coordinator, entry, "firmware_version", "Firmware Version")
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
        super().__init__(coordinator, entry, "operating_time_stove", "Operating Time Stove")
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
        super().__init__(coordinator, entry, "operating_time_auger", "Operating Time Auger")
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
        super().__init__(coordinator, entry, "operating_time_ignition", "Operating Time Ignition")
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
        super().__init__(coordinator, entry, "mode_transition", "Mode Transition")
        self._attr_icon = "mdi:state-machine"

    @property
    def native_value(self) -> str | None:
        """Return the mode transition state."""
        if self.coordinator.data and "calculated" in self.coordinator.data:
            return self.coordinator.data["calculated"].get("mode_transition", "idle")
        return "idle"


class AduroChangeInProgressSensor(AduroSensorBase):
    """Sensor for change in progress status."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "change_in_progress", "Change In Progress")
        self._attr_icon = "mdi:sync"

    @property
    def native_value(self) -> str | None:
        """Return true/false as string."""
        if self.coordinator.data and "calculated" in self.coordinator.data:
            in_progress = self.coordinator.data["calculated"].get("change_in_progress", False)
            return "true" if in_progress else "false"
        return "false"


class AduroDisplayFormatSensor(AduroSensorBase):
    """Sensor for formatted display text."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "display_format", "Display Format")
        self._attr_icon = "mdi:format-text"

    @property
    def native_value(self) -> str | None:
        """Return the formatted display text."""
        if self.coordinator.data and "calculated" in self.coordinator.data:
            return self.coordinator.data["calculated"].get("display_format", "")
        return None


class AduroDisplayTargetSensor(AduroSensorBase):
    """Sensor for display target value."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator, entry, "display_target", "Display Target")

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
        super().__init__(coordinator, entry, "app_change_detected", "App Change Detected")
        self._attr_icon = "mdi:cellphone-arrow-down"

    @property
    def native_value(self) -> str | None:
        """Return true/false as string."""
        if self.coordinator.data:
            detected = self.coordinator.data.get("app_change_detected", False)
            return "true" if detected else "false"
        return "false"
