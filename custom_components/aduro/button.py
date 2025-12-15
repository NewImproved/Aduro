"""Button platform for Aduro Hybrid Stove integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .coordinator import AduroCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Aduro button entities."""
    coordinator: AduroCoordinator = hass.data[DOMAIN][entry.entry_id]

    buttons = [
        AduroRefillPelletsButton(coordinator, entry),
        AduroCleanStoveButton(coordinator, entry),
        AduroToggleModeButton(coordinator, entry),
        AduroResumeAfterWoodButton(coordinator, entry),
        AduroForceAugerButton(coordinator, entry),
    ]

    async_add_entities(buttons)


class AduroButtonBase(CoordinatorEntity, ButtonEntity):
    """Base class for Aduro buttons."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AduroCoordinator,
        entry: ConfigEntry,
        button_type: str,
        translation_key: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entry = entry
        self._attr_unique_id = f"{entry.entry_id}_{button_type}"
        self._attr_translation_key = translation_key
        self._entity_id_suffix = button_type
        self._button_type = button_type

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        
        # Force the entity_id to be in English
        registry = er.async_get(self.hass)
        
        # Construct the desired English entity_id
        desired_entity_id = f"button.{DOMAIN}_{self.coordinator.stove_model.lower()}_{self._entity_id_suffix}"
        
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


class AduroRefillPelletsButton(AduroButtonBase):
    """Button to mark pellets as refilled."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the button."""
        super().__init__(coordinator, entry, "refill_pellets", "refill_pellets")
        self._attr_icon = "mdi:reload"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data or "pellets" not in self.coordinator.data:
            return {}
        
        pellets = self.coordinator.data["pellets"]
        
        return {
            "consumed_since_last_refill": round(pellets.get("consumed", 0), 1),
            "total_consumed_since_cleaning": round(pellets.get("consumed_total", 0), 1),
            "capacity": pellets.get("capacity", 0),
        }

    async def async_press(self) -> None:
        """Handle button press."""
        _LOGGER.info("Button: Pellets refilled - resetting per-refill consumption counter")
        
        # Get current consumption before reset for logging
        consumed = 0
        consumed_total = 0
        if self.coordinator.data and "pellets" in self.coordinator.data:
            consumed = self.coordinator.data["pellets"].get("consumed", 0)
            consumed_total = self.coordinator.data["pellets"].get("consumed_total", 0)
        
        # Reset pellet consumption (only per-refill counter)
        self.coordinator.refill_pellets()
        
        _LOGGER.info(
            "Button: Per-refill consumption reset from %.1f kg, total since cleaning: %.1f kg",
            consumed,
            consumed_total
        )
        
        # Request immediate update
        await self.coordinator.async_request_refresh()


class AduroCleanStoveButton(AduroButtonBase):
    """Button to mark stove as cleaned."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the button."""
        super().__init__(coordinator, entry, "clean_stove", "clean_stove")
        self._attr_icon = "mdi:broom"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data or "pellets" not in self.coordinator.data:
            return {}
        
        pellets = self.coordinator.data["pellets"]
        
        return {
            "total_consumed_before_cleaning": round(pellets.get("consumed_total", 0), 1),
            "consumed_since_refill": round(pellets.get("consumed", 0), 1),
        }

    async def async_press(self) -> None:
        """Handle button press."""
        _LOGGER.info("Button: Stove cleaned - resetting total consumption counter")
        
        # Get current counter before reset for logging
        consumed_total = 0
        if self.coordinator.data and "pellets" in self.coordinator.data:
            consumed_total = self.coordinator.data["pellets"].get("consumed_total", 0)
        
        # Reset total consumption counter
        self.coordinator.reset_refill_counter()
        
        _LOGGER.info(
            "Button: Total consumption counter reset from %.1f kg to 0 after cleaning",
            consumed_total
        )
        
        # Request immediate update
        await self.coordinator.async_request_refresh()


class AduroToggleModeButton(AduroButtonBase):
    """Button to toggle between heatlevel and temperature modes."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the button."""
        super().__init__(coordinator, entry, "toggle_mode", "toggle_mode")

    @property
    def icon(self) -> str:
        """Return icon based on current state."""
        if not self.coordinator.data:
            return "mdi:help-circle"
        
        # Check if change is in progress
        if self.coordinator.data.get("calculated", {}).get("change_in_progress", False):
            return "mdi:sync-circle"
        
        # Icon based on current operation mode
        operation_mode = self.coordinator.data.get("status", {}).get("operation_mode", 0)
        
        if operation_mode == 0:
            return "mdi:fire"
        elif operation_mode == 1:
            return "mdi:thermometer"
        elif operation_mode == 2:
            return "mdi:campfire"
        
        return "mdi:help-circle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data:
            return {}
        
        operation_mode = self.coordinator.data.get("status", {}).get("operation_mode", 0)
        change_in_progress = self.coordinator.data.get("calculated", {}).get("change_in_progress", False)
        
        mode_names = {0: "Heat Level", 1: "Temperature", 2: "Wood"}
        current_mode = mode_names.get(operation_mode, "Unknown")
        next_mode = mode_names.get(1 if operation_mode == 0 else 0, "Unknown")
        
        return {
            "current_mode": current_mode,
            "will_switch_to": next_mode,
            "change_in_progress": change_in_progress,
        }

    async def async_press(self) -> None:
        """Handle button press."""
        if not self.coordinator.data:
            _LOGGER.error("Button: No data available to toggle mode")
            return
        
        current_mode = self.coordinator.data.get("status", {}).get("operation_mode", 0)
        mode_names = {0: "Heat Level", 1: "Temperature", 2: "Wood"}
        
        _LOGGER.info(
            "Button: Toggling mode from %s to %s",
            mode_names.get(current_mode, current_mode),
            mode_names.get(1 if current_mode == 0 else 0, "other")
        )
        
        success = await self.coordinator.async_toggle_mode()
        
        if success:
            _LOGGER.info("Button: Mode toggle initiated successfully")
            # Request immediate update
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Button: Failed to toggle mode")


class AduroResumeAfterWoodButton(AduroButtonBase):
    """Button to manually resume pellet operation after wood mode."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the button."""
        super().__init__(coordinator, entry, "resume_after_wood_mode", "resume_after_wood_mode")
        self._attr_icon = "mdi:play-circle"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data or "operating" not in self.coordinator.data:
            return {}
        
        current_state = self.coordinator.data["operating"].get("state", "")
        in_wood_mode = current_state in ["9"]
        
        attrs = {
            "current_state": current_state,
            "in_wood_mode": in_wood_mode,
            "can_resume": in_wood_mode,
        }
        
        # Add saved settings if available
        if self.coordinator._pre_wood_mode_operation_mode is not None:
            mode_names = {0: "Heat Level", 1: "Temperature", 2: "Wood"}
            attrs["will_restore_mode"] = mode_names.get(
                self.coordinator._pre_wood_mode_operation_mode,
                "Unknown"
            )
        
        if self.coordinator._pre_wood_mode_heatlevel is not None:
            attrs["will_restore_heatlevel"] = self.coordinator._pre_wood_mode_heatlevel
        
        if self.coordinator._pre_wood_mode_temperature is not None:
            attrs["will_restore_temperature"] = self.coordinator._pre_wood_mode_temperature
        
        return attrs

    async def async_press(self) -> None:
        """Handle button press."""
        if not self.coordinator.data or "operating" not in self.coordinator.data:
            _LOGGER.error("Button: No data available to resume after wood mode")
            return
        
        current_state = self.coordinator.data["operating"].get("state", "")
        
        if current_state not in ["9"]:
            _LOGGER.warning(
                "Button: Cannot resume - stove not in wood mode (current state: %s)",
                current_state
            )
            return
        
        _LOGGER.info("Button: Manually resuming pellet operation after wood mode")
        
        success = await self.coordinator.async_resume_after_wood_mode()
        
        if success:
            _LOGGER.info("Button: Resume initiated successfully")
            # Request immediate update
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Button: Failed to resume after wood mode")


class AduroForceAugerButton(AduroButtonBase):
    """Button to force the auger to run."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the button."""
        super().__init__(coordinator, entry, "force_auger", "force_auger")
        self._attr_icon = "mdi:cog-play"
        self._attr_entity_category = EntityCategory.CONFIG

    async def async_press(self) -> None:
        """Handle button press."""
        _LOGGER.info("Button: Forcing auger to run")
        
        success = await self.coordinator.async_force_auger()
        
        if success:
            _LOGGER.info("Button: Auger forced successfully")
            # Request immediate update
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Button: Failed to force auger")
