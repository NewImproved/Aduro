"""Number platform with debouncing for Aduro Hybrid Stove integration."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfMass, UnitOfTemperature, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import entity_registry as er

from .const import (
    DOMAIN,
    HEAT_LEVEL_MIN,
    HEAT_LEVEL_MAX,
    HEAT_LEVEL_STEP,
    TEMP_MIN,
    TEMP_MAX,
    TEMP_STEP,
    PELLET_CAPACITY_MIN,
    PELLET_CAPACITY_MAX,
    PELLET_CAPACITY_STEP,
    NOTIFICATION_LEVEL_MIN,
    NOTIFICATION_LEVEL_MAX,
    NOTIFICATION_LEVEL_STEP,
    SHUTDOWN_LEVEL_MIN,
    SHUTDOWN_LEVEL_MAX,
    SHUTDOWN_LEVEL_STEP,
)
from .coordinator import AduroCoordinator

_LOGGER = logging.getLogger(__name__)

# Debounce delay in seconds - wait this long after last change before sending
DEBOUNCE_DELAY = 0.7


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Aduro number entities."""
    coordinator: AduroCoordinator = hass.data[DOMAIN][entry.entry_id]

    numbers = [
        AduroHeatlevelNumber(coordinator, entry),
        AduroTemperatureNumber(coordinator, entry),
        AduroPelletCapacityNumber(coordinator, entry),
        AduroNotificationLevelNumber(coordinator, entry),
        AduroShutdownLevelNumber(coordinator, entry),
        AduroHighSmokeTempThresholdNumber(coordinator, entry),
        AduroHighSmokeDurationThresholdNumber(coordinator, entry),
        AduroLowWoodTempThresholdNumber(coordinator, entry),
        AduroLowWoodDurationThresholdNumber(coordinator, entry),
    ]

    async_add_entities(numbers)


class AduroNumberBase(CoordinatorEntity, NumberEntity):
    """Base class for Aduro number entities."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AduroCoordinator,
        entry: ConfigEntry,
        number_type: str,
        translation_key: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{number_type}"
        self._attr_translation_key = translation_key
        self._number_type = number_type
        self._entity_id_suffix = number_type
        
        # Debouncing support
        self._pending_value: float | None = None
        self._debounce_task: asyncio.Task | None = None

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        
        # Force the entity_id to be in English
        registry = er.async_get(self.hass)
        
        # Construct the desired English entity_id
        desired_entity_id = f"number.{DOMAIN}_{self.coordinator.stove_model.lower()}_{self._entity_id_suffix}"
        
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
        sw_version = self.combined_firmware_version()
        
        device_data = {
            "identifiers": {(DOMAIN, f"aduro_{self.coordinator.entry.entry_id}")},
            "name": f"Aduro {self.coordinator.stove_model}",
            "manufacturer": "Aduro",
            "model": f"Hybrid {self.coordinator.stove_model}",
        }
        
        device_data["sw_version"] = sw_version
        
        return device_data
        
    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        if not self.coordinator.last_update_success:
            return False
        
        if not self.coordinator.stove_ip:
            return False
        
        return True

    async def _debounced_set_value(self, value: float, delay: float = DEBOUNCE_DELAY) -> None:
        """Set value with debouncing - waits for user to stop changing."""
        # Cancel any existing debounce task
        if self._debounce_task and not self._debounce_task.done():
            self._debounce_task.cancel()
            _LOGGER.debug("%s: Cancelled previous debounce task", self._attr_translation_key)
        
        # Store the pending value
        self._pending_value = value
        
        # Immediately update the UI to show the new value
        self.async_write_ha_state()
        
        # Create new debounce task
        async def _send_after_delay():
            try:
                await asyncio.sleep(delay)
                _LOGGER.info(
                    "%s: Debounce complete, sending value: %s",
                    self._attr_translation_key,
                    self._pending_value
                )
                await self._actually_set_value(self._pending_value)
                self._pending_value = None
            except asyncio.CancelledError:
                _LOGGER.debug("%s: Debounce task cancelled", self._attr_translation_key)
                raise
        
        self._debounce_task = asyncio.create_task(_send_after_delay())

    async def _actually_set_value(self, value: float) -> None:
        """Actually send the value to the device - override in subclasses."""
        raise NotImplementedError

        
class AduroHeatlevelNumber(AduroNumberBase):
    """Number entity for heat level control."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, entry, "heatlevel", "heatlevel")
        self._attr_icon = "mdi:fire"
        self._attr_mode = NumberMode.SLIDER
        self._attr_native_min_value = HEAT_LEVEL_MIN
        self._attr_native_max_value = HEAT_LEVEL_MAX
        self._attr_native_step = HEAT_LEVEL_STEP

    @property
    def native_value(self) -> float | None:
        """Return the current heat level."""
        # Show pending value first (immediate UI update)
        if self._pending_value is not None:
            return self._pending_value
        
        # Show target while changing
        if self.coordinator._change_in_progress and self.coordinator._target_heatlevel is not None:
            return self.coordinator._target_heatlevel
        
        # Show actual value from stove
        if self.coordinator.data and "operating" in self.coordinator.data:
            return self.coordinator.data["operating"].get("heatlevel")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data or "operating" not in self.coordinator.data:
            return {}
        
        heatlevel = self.coordinator.data["operating"].get("heatlevel", 1)
        from .const import HEAT_LEVEL_DISPLAY
        
        attrs = {
            "display": HEAT_LEVEL_DISPLAY.get(heatlevel, str(heatlevel)),
            "operation_mode": self.coordinator.data.get("status", {}).get("operation_mode", 0),
        }
        
        # Show if change is pending
        if self._pending_value is not None:
            attrs["pending_change"] = True
            attrs["pending_value"] = self._pending_value
        
        return attrs

    async def async_set_native_value(self, value: float) -> None:
        """Set the heat level with debouncing."""
        heatlevel = int(value)
        _LOGGER.debug("Number: Heat level change requested: %s", heatlevel)
        
        # Use debouncing for slider changes
        await self._debounced_set_value(float(heatlevel))

    async def _actually_set_value(self, value: float) -> None:
        """Actually send the heat level to the stove."""
        heatlevel = int(value)
        _LOGGER.info("Number: Actually setting heat level to %s", heatlevel)
        
        success = await self.coordinator.async_set_heatlevel(heatlevel)
        
        if success:
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Number: Failed to set heat level to %s", heatlevel)


class AduroTemperatureNumber(AduroNumberBase):
    """Number entity for temperature control."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, entry, "temperature", "temperature")
        self._attr_icon = "mdi:thermometer"
        self._attr_mode = NumberMode.SLIDER
        self._attr_native_min_value = TEMP_MIN
        self._attr_native_max_value = TEMP_MAX
        self._attr_native_step = TEMP_STEP
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def native_value(self) -> float | None:
        """Return the current target temperature."""
        # Show pending value first (immediate UI update)
        if self._pending_value is not None:
            return self._pending_value
        
        # Show target while changing
        if self.coordinator._change_in_progress and self.coordinator._target_temperature is not None:
            return self.coordinator._target_temperature
        
        # Show actual value from stove
        if self.coordinator.data and "operating" in self.coordinator.data:
            return self.coordinator.data["operating"].get("boiler_ref")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data or "operating" not in self.coordinator.data:
            return {}
        
        attrs = {
            "current_temp": self.coordinator.data["operating"].get("boiler_temp"),
            "operation_mode": self.coordinator.data.get("status", {}).get("operation_mode", 0),
        }
        
        # Show if change is pending
        if self._pending_value is not None:
            attrs["pending_change"] = True
            attrs["pending_value"] = self._pending_value
        
        return attrs

    async def async_set_native_value(self, value: float) -> None:
        """Set the target temperature with debouncing."""
        temperature = float(value)
        _LOGGER.debug("Number: Temperature change requested: %s°C", temperature)
        
        # Use debouncing for slider changes
        await self._debounced_set_value(temperature)

    async def _actually_set_value(self, value: float) -> None:
        """Actually send the temperature to the stove."""
        temperature = float(value)
        _LOGGER.info("Number: Actually setting target temperature to %s°C", temperature)
        
        success = await self.coordinator.async_set_temperature(temperature)
        
        if success:
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Number: Failed to set temperature to %s°C", temperature)


class AduroPelletCapacityNumber(AduroNumberBase):
    """Number entity for pellet capacity configuration."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, entry, "pellet_capacity", "pellet_capacity")
        self._attr_icon = "mdi:grain"
        self._attr_mode = NumberMode.BOX
        self._attr_native_min_value = PELLET_CAPACITY_MIN
        self._attr_native_max_value = PELLET_CAPACITY_MAX
        self._attr_native_step = PELLET_CAPACITY_STEP
        self._attr_native_unit_of_measurement = UnitOfMass.KILOGRAMS

    @property
    def native_value(self) -> float | None:
        """Return the current pellet capacity."""
        if self.coordinator.data and "pellets" in self.coordinator.data:
            return self.coordinator.data["pellets"].get("capacity")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data or "pellets" not in self.coordinator.data:
            return {}
        
        pellets = self.coordinator.data["pellets"]
        
        return {
            "consumed": pellets.get("consumed", 0),
            "remaining": pellets.get("amount", 0),
            "percentage": pellets.get("percentage", 0),
        }

    async def async_set_native_value(self, value: float) -> None:
        """Set the pellet capacity - no debouncing needed for config values."""
        capacity = float(value)
        _LOGGER.info("Number: Setting pellet capacity to %s kg", capacity)
        
        self.coordinator.set_pellet_capacity(capacity)
        await self.coordinator.async_request_refresh()

    async def _actually_set_value(self, value: float) -> None:
        """Not used - capacity changes are immediate."""
        pass


class AduroNotificationLevelNumber(AduroNumberBase):
    """Number entity for low pellet notification level."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, entry, "notification_level", "notification_level")
        self._attr_icon = "mdi:bell-alert"
        self._attr_mode = NumberMode.BOX
        self._attr_native_min_value = NOTIFICATION_LEVEL_MIN
        self._attr_native_max_value = NOTIFICATION_LEVEL_MAX
        self._attr_native_step = NOTIFICATION_LEVEL_STEP
        self._attr_native_unit_of_measurement = PERCENTAGE

    @property
    def native_value(self) -> float | None:
        """Return the current notification level."""
        if self.coordinator.data and "pellets" in self.coordinator.data:
            return self.coordinator.data["pellets"].get("notification_level")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data or "pellets" not in self.coordinator.data:
            return {}
        
        pellets = self.coordinator.data["pellets"]
        current_percentage = pellets.get("percentage", 0)
        notification_level = pellets.get("notification_level", 10)
        
        return {
            "current_percentage": current_percentage,
            "alert_active": current_percentage <= notification_level,
            "low_pellet_alert": pellets.get("low_pellet_alert", False),
        }

    async def async_set_native_value(self, value: float) -> None:
        """Set the notification level - no debouncing needed for config values."""
        level = float(value)
        _LOGGER.info("Number: Setting notification level to %s%%", level)
        
        self.coordinator.set_notification_level(level)
        await self.coordinator.async_request_refresh()

    async def _actually_set_value(self, value: float) -> None:
        """Not used - notification level changes are immediate."""
        pass


class AduroShutdownLevelNumber(AduroNumberBase):
    """Number entity for auto-shutdown pellet level."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, entry, "shutdown_level", "shutdown_level")
        self._attr_icon = "mdi:power-off"
        self._attr_mode = NumberMode.BOX
        self._attr_native_min_value = SHUTDOWN_LEVEL_MIN
        self._attr_native_max_value = SHUTDOWN_LEVEL_MAX
        self._attr_native_step = SHUTDOWN_LEVEL_STEP
        self._attr_native_unit_of_measurement = PERCENTAGE

    @property
    def native_value(self) -> float | None:
        """Return the current shutdown level."""
        if self.coordinator.data and "pellets" in self.coordinator.data:
            return self.coordinator.data["pellets"].get("shutdown_level")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data or "pellets" not in self.coordinator.data:
            return {}
        
        pellets = self.coordinator.data["pellets"]
        current_percentage = pellets.get("percentage", 0)
        shutdown_level = pellets.get("shutdown_level", 5)
        
        return {
            "current_percentage": current_percentage,
            "auto_shutdown_enabled": pellets.get("auto_shutdown_enabled", False),
            "alert_active": current_percentage <= shutdown_level,
            "shutdown_alert": pellets.get("shutdown_alert", False),
        }

    async def async_set_native_value(self, value: float) -> None:
        """Set the shutdown level - no debouncing needed for config values."""
        level = float(value)
        _LOGGER.info("Number: Setting shutdown level to %s%%", level)
        
        self.coordinator.set_shutdown_level(level)
        await self.coordinator.async_request_refresh()

    async def _actually_set_value(self, value: float) -> None:
        """Not used - shutdown level changes are immediate."""
        pass

class AduroHighSmokeTempThresholdNumber(AduroNumberBase):
    """Number entity for high smoke temperature threshold."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, entry, "high_smoke_temp_threshold", "high_smoke_temp_threshold")
        self._attr_icon = "mdi:thermometer-alert"
        self._attr_mode = NumberMode.BOX
        from .const import HIGH_SMOKE_TEMP_MIN, HIGH_SMOKE_TEMP_MAX, HIGH_SMOKE_TEMP_STEP
        self._attr_native_min_value = HIGH_SMOKE_TEMP_MIN
        self._attr_native_max_value = HIGH_SMOKE_TEMP_MAX
        self._attr_native_step = HIGH_SMOKE_TEMP_STEP
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def native_value(self) -> float | None:
        """Return the current threshold."""
        return self.coordinator._high_smoke_temp_threshold

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs = {}
        if self.coordinator.data and "operating" in self.coordinator.data:
            current_temp = self.coordinator.data["operating"].get("smoke_temp", 0)
            attrs["current_smoke_temp"] = current_temp
            attrs["threshold_exceeded"] = current_temp >= self.coordinator._high_smoke_temp_threshold
        
        if self.coordinator.data and "alerts" in self.coordinator.data:
            alert_info = self.coordinator.data["alerts"].get("high_smoke_temp_alert", {})
            attrs["alert_active"] = alert_info.get("active", False)
            if alert_info.get("time_info"):
                attrs["time_info"] = alert_info["time_info"]
        
        return attrs

    async def async_set_native_value(self, value: float) -> None:
        """Set the threshold temperature."""
        temperature = float(value)
        _LOGGER.info("Number: Setting high smoke temp threshold to %s°C", temperature)
        
        self.coordinator.set_high_smoke_temp_threshold(temperature)
        await self.coordinator.async_request_refresh()

    async def _actually_set_value(self, value: float) -> None:
        """Not used - threshold changes are immediate."""
        pass


class AduroHighSmokeDurationThresholdNumber(AduroNumberBase):
    """Number entity for high smoke temperature duration threshold."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, entry, "high_smoke_duration_threshold", "high_smoke_duration_threshold")
        self._attr_icon = "mdi:timer-alert-outline"
        self._attr_mode = NumberMode.BOX
        from .const import HIGH_SMOKE_DURATION_MIN, HIGH_SMOKE_DURATION_MAX, HIGH_SMOKE_DURATION_STEP
        self._attr_native_min_value = HIGH_SMOKE_DURATION_MIN
        self._attr_native_max_value = HIGH_SMOKE_DURATION_MAX
        self._attr_native_step = HIGH_SMOKE_DURATION_STEP
        self._attr_native_unit_of_measurement = UnitOfTime.SECONDS

    @property
    def native_value(self) -> float | None:
        """Return the current duration threshold."""
        return float(self.coordinator._high_smoke_duration_threshold)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs = {
            "duration_minutes": self.coordinator._high_smoke_duration_threshold / 60,
        }
        
        if self.coordinator.data and "alerts" in self.coordinator.data:
            alert_info = self.coordinator.data["alerts"].get("high_smoke_temp_alert", {})
            attrs["alert_active"] = alert_info.get("active", False)
            if alert_info.get("time_info"):
                time_info = alert_info["time_info"]
                attrs["time_info"] = time_info
                if time_info["state"] == "building":
                    attrs["time_remaining_minutes"] = round(time_info["remaining"] / 60, 1)
                elif time_info["state"] == "exceeded":
                    attrs["time_exceeded_minutes"] = round(time_info["exceeded_by"] / 60, 1)
        
        return attrs

    async def async_set_native_value(self, value: float) -> None:
        """Set the duration threshold."""
        duration = int(value)
        _LOGGER.info("Number: Setting high smoke duration threshold to %s seconds", duration)
        
        self.coordinator.set_high_smoke_duration_threshold(duration)
        await self.coordinator.async_request_refresh()

    async def _actually_set_value(self, value: float) -> None:
        """Not used - threshold changes are immediate."""
        pass


class AduroLowWoodTempThresholdNumber(AduroNumberBase):
    """Number entity for low wood mode temperature threshold."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, entry, "low_wood_temp_threshold", "low_wood_temp_threshold")
        self._attr_icon = "mdi:thermometer-low"
        self._attr_mode = NumberMode.BOX
        from .const import LOW_WOOD_TEMP_MIN, LOW_WOOD_TEMP_MAX, LOW_WOOD_TEMP_STEP
        self._attr_native_min_value = LOW_WOOD_TEMP_MIN
        self._attr_native_max_value = LOW_WOOD_TEMP_MAX
        self._attr_native_step = LOW_WOOD_TEMP_STEP
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def native_value(self) -> float | None:
        """Return the current threshold."""
        return self.coordinator._low_wood_temp_threshold

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs = {}
        if self.coordinator.data and "operating" in self.coordinator.data:
            current_temp = self.coordinator.data["operating"].get("shaft_temp", 0)
            current_state = self.coordinator.data["operating"].get("state")
            is_in_wood_mode = current_state in ["9", "14"]
            
            attrs["current_shaft_temp"] = current_temp
            attrs["in_wood_mode"] = is_in_wood_mode
            attrs["threshold_exceeded"] = is_in_wood_mode and current_temp <= self.coordinator._low_wood_temp_threshold
        
        if self.coordinator.data and "alerts" in self.coordinator.data:
            alert_info = self.coordinator.data["alerts"].get("low_wood_temp_alert", {})
            attrs["alert_active"] = alert_info.get("active", False)
            if alert_info.get("time_info"):
                attrs["time_info"] = alert_info["time_info"]
        
        return attrs

    async def async_set_native_value(self, value: float) -> None:
        """Set the threshold temperature."""
        temperature = float(value)
        _LOGGER.info("Number: Setting low wood temp threshold to %s°C", temperature)
        
        self.coordinator.set_low_wood_temp_threshold(temperature)
        await self.coordinator.async_request_refresh()

    async def _actually_set_value(self, value: float) -> None:
        """Not used - threshold changes are immediate."""
        pass


class AduroLowWoodDurationThresholdNumber(AduroNumberBase):
    """Number entity for low wood mode temperature duration threshold."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, entry, "low_wood_duration_threshold", "low_wood_duration_threshold")
        self._attr_icon = "mdi:timer-outline"
        self._attr_mode = NumberMode.BOX
        from .const import LOW_WOOD_DURATION_MIN, LOW_WOOD_DURATION_MAX, LOW_WOOD_DURATION_STEP
        self._attr_native_min_value = LOW_WOOD_DURATION_MIN
        self._attr_native_max_value = LOW_WOOD_DURATION_MAX
        self._attr_native_step = LOW_WOOD_DURATION_STEP
        self._attr_native_unit_of_measurement = UnitOfTime.SECONDS

    @property
    def native_value(self) -> float | None:
        """Return the current duration threshold."""
        return float(self.coordinator._low_wood_duration_threshold)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs = {
            "duration_minutes": self.coordinator._low_wood_duration_threshold / 60,
        }
        
        if self.coordinator.data and "alerts" in self.coordinator.data:
            alert_info = self.coordinator.data["alerts"].get("low_wood_temp_alert", {})
            attrs["alert_active"] = alert_info.get("active", False)
            attrs["in_wood_mode"] = alert_info.get("in_wood_mode", False)
            
            if alert_info.get("time_info"):
                time_info = alert_info["time_info"]
                attrs["time_info"] = time_info
                if time_info["state"] == "building":
                    attrs["time_remaining_minutes"] = round(time_info["remaining"] / 60, 1)
                elif time_info["state"] == "exceeded":
                    attrs["time_exceeded_minutes"] = round(time_info["exceeded_by"] / 60, 1)
        
        return attrs

    async def async_set_native_value(self, value: float) -> None:
        """Set the duration threshold."""
        duration = int(value)
        _LOGGER.info("Number: Setting low wood duration threshold to %s seconds", duration)
        
        self.coordinator.set_low_wood_duration_threshold(duration)
        await self.coordinator.async_request_refresh()

    async def _actually_set_value(self, value: float) -> None:
        """Not used - threshold changes are immediate."""
        pass
