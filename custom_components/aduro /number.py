"""Number platform for Aduro Hybrid Stove integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE, UnitOfMass, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

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
    ]

    async_add_entities(numbers)


class AduroNumberBase(CoordinatorEntity, NumberEntity):
    """Base class for Aduro number entities."""

    def __init__(
        self,
        coordinator: AduroCoordinator,
        entry: ConfigEntry,
        number_type: str,
        name: str,
    ) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator)
        self._attr_has_entity_name = True
        self._attr_unique_id = f"{entry.entry_id}_{number_type}"
        self._attr_name = name
        self._number_type = number_type

    @property
    def device_info(self):
        """Return device information."""
        return {
            "identifiers": {(DOMAIN, self.coordinator.entry.entry_id)},
            "name": f"Aduro {self.coordinator.stove_model}",
            "manufacturer": "Aduro",
            "model": f"Hybrid {self.coordinator.stove_model}",
            "sw_version": self.coordinator.entry.data.get("version", "Unknown"),
        }


class AduroHeatlevelNumber(AduroNumberBase):
    """Number entity for heat level control."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, entry, "heatlevel", "Heat Level")
        self._attr_icon = "mdi:fire"
        self._attr_mode = NumberMode.SLIDER
        self._attr_native_min_value = HEAT_LEVEL_MIN
        self._attr_native_max_value = HEAT_LEVEL_MAX
        self._attr_native_step = HEAT_LEVEL_STEP

    @property
    def native_value(self) -> float | None:
        """Return the current heat level."""
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
        
        return {
            "display": HEAT_LEVEL_DISPLAY.get(heatlevel, str(heatlevel)),
            "operation_mode": self.coordinator.data.get("status", {}).get("operation_mode", 0),
        }

    async def async_set_native_value(self, value: float) -> None:
        """Set the heat level."""
        heatlevel = int(value)
        _LOGGER.info("Number: Setting heat level to %s", heatlevel)
        
        success = await self.coordinator.async_set_heatlevel(heatlevel)
        
        if success:
            # Request immediate update
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Number: Failed to set heat level to %s", heatlevel)


class AduroTemperatureNumber(AduroNumberBase):
    """Number entity for temperature control."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, entry, "temperature", "Target Temperature")
        self._attr_icon = "mdi:thermometer"
        self._attr_mode = NumberMode.SLIDER
        self._attr_native_min_value = TEMP_MIN
        self._attr_native_max_value = TEMP_MAX
        self._attr_native_step = TEMP_STEP
        self._attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    @property
    def native_value(self) -> float | None:
        """Return the current target temperature."""
        if self.coordinator.data and "operating" in self.coordinator.data:
            return self.coordinator.data["operating"].get("boiler_ref")
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data or "operating" not in self.coordinator.data:
            return {}
        
        return {
            "current_temp": self.coordinator.data["operating"].get("boiler_temp"),
            "operation_mode": self.coordinator.data.get("status", {}).get("operation_mode", 0),
        }

    async def async_set_native_value(self, value: float) -> None:
        """Set the target temperature."""
        temperature = float(value)
        _LOGGER.info("Number: Setting target temperature to %s°C", temperature)
        
        success = await self.coordinator.async_set_temperature(temperature)
        
        if success:
            # Request immediate update
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Number: Failed to set temperature to %s°C", temperature)


class AduroPelletCapacityNumber(AduroNumberBase):
    """Number entity for pellet capacity configuration."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, entry, "pellet_capacity", "Pellet Capacity")
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
        """Set the pellet capacity."""
        capacity = float(value)
        _LOGGER.info("Number: Setting pellet capacity to %s kg", capacity)
        
        self.coordinator.set_pellet_capacity(capacity)
        
        # Request immediate update
        await self.coordinator.async_request_refresh()


class AduroNotificationLevelNumber(AduroNumberBase):
    """Number entity for low pellet notification level."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, entry, "notification_level", "Low Pellet Notification Level")
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
        """Set the notification level."""
        level = float(value)
        _LOGGER.info("Number: Setting notification level to %s%%", level)
        
        self.coordinator.set_notification_level(level)
        
        # Request immediate update
        await self.coordinator.async_request_refresh()


class AduroShutdownLevelNumber(AduroNumberBase):
    """Number entity for auto-shutdown pellet level."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the number entity."""
        super().__init__(coordinator, entry, "shutdown_level", "Auto-Shutdown Pellet Level")
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
        """Set the shutdown level."""
        level = float(value)
        _LOGGER.info("Number: Setting shutdown level to %s%%", level)
        
        self.coordinator.set_shutdown_level(level)
        
        # Request immediate update
        await self.coordinator.async_request_refresh()
