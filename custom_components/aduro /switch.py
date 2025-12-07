"""Switch platform for Aduro Hybrid Stove integration."""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN, STARTUP_STATES, SHUTDOWN_STATES
from .coordinator import AduroCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Aduro switch entities."""
    coordinator: AduroCoordinator = hass.data[DOMAIN][entry.entry_id]

    switches = [
        AduroStartStopSwitch(coordinator, entry),
        AduroAutoShutdownSwitch(coordinator, entry),
        AduroAutoResumeAfterWoodSwitch(coordinator, entry),
    ]

    async_add_entities(switches)


class AduroSwitchBase(CoordinatorEntity, SwitchEntity):
    """Base class for Aduro switches."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: AduroCoordinator,
        entry: ConfigEntry,
        entity_id_suffix: str,
        translation_key: str,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entry = entry
        # Use English suffix for entity ID
        self._attr_unique_id = f"{entry.entry_id}_{entity_id_suffix}"
        # Use translation key for display name translation
        self._attr_translation_key = translation_key
        self._switch_type = entity_id_suffix
        self._entity_id_suffix = entity_id_suffix

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        await super().async_added_to_hass()
        
        # Force the entity_id to be in English
        registry = er.async_get(self.hass)
        
        # Construct the desired English entity_id
        desired_entity_id = f"switch.{DOMAIN}_{self.coordinator.stove_model.lower()}_{self._entity_id_suffix}"
        
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


class AduroStartStopSwitch(AduroSwitchBase):
    """Switch to start/stop the stove."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, entry, "power", "power")
        self._attr_icon = "mdi:power"

    @property
    def is_on(self) -> bool:
        """Return true if stove is running."""
        if not self.coordinator.data or "operating" not in self.coordinator.data:
            return False
        
        current_state = self.coordinator.data["operating"].get("state")
        
        # Stove is "on" if in any startup/running state
        is_running = current_state in STARTUP_STATES
        
        # Log warning for unknown states
        if current_state and current_state not in STARTUP_STATES and current_state not in SHUTDOWN_STATES:
            _LOGGER.warning(
                "Unknown stove state %s - Cannot determine if stove is running. Assuming OFF. Please report this to the integration developer.",
                current_state
            )
            return False
        
        return is_running

    @property
    def icon(self) -> str:
        """Return icon based on state."""
        if self.is_on:
            return "mdi:power"
        return "mdi:power"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data or "operating" not in self.coordinator.data:
            return {}
        
        current_state = self.coordinator.data["operating"].get("state", "unknown")
        
        # Get state description
        from .const import STATE_NAMES, SUBSTATE_NAMES
        
        state_desc = STATE_NAMES.get(current_state, f"State {current_state}")
        substate_desc = SUBSTATE_NAMES.get(current_state, "")
        
        return {
            "state": current_state,
            "state_description": state_desc,
            "substate_description": substate_desc,
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn on the stove."""
        _LOGGER.info("Switch: Turning on stove")
        success = await self.coordinator.async_start_stove()
        
        if success:
            # Request immediate update
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Switch: Failed to turn on stove")

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off the stove."""
        _LOGGER.info("Switch: Turning off stove")
        success = await self.coordinator.async_stop_stove()
        
        if success:
            # Request immediate update
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Switch: Failed to turn off stove")


class AduroAutoShutdownSwitch(AduroSwitchBase):
    """Switch to enable/disable automatic shutdown at low pellet level."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, entry, "auto_shutdown", "auto_shutdown")
        self._attr_icon = "mdi:power-settings"

    @property
    def is_on(self) -> bool:
        """Return true if auto-shutdown is enabled."""
        if not self.coordinator.data or "pellets" not in self.coordinator.data:
            return False
        
        return self.coordinator.data["pellets"].get("auto_shutdown_enabled", False)

    @property
    def icon(self) -> str:
        """Return icon based on state."""
        if self.is_on:
            return "mdi:shield-check"
        return "mdi:shield-off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        if not self.coordinator.data or "pellets" not in self.coordinator.data:
            return {}
        
        pellets_data = self.coordinator.data["pellets"]
        
        return {
            "shutdown_level": pellets_data.get("shutdown_level", 5),
            "current_percentage": pellets_data.get("percentage", 0),
            "shutdown_alert": pellets_data.get("shutdown_alert", False),
        }

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable auto-shutdown."""
        _LOGGER.info("Switch: Enabling auto-shutdown at low pellet level")
        self.coordinator.set_auto_shutdown_enabled(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable auto-shutdown."""
        _LOGGER.info("Switch: Disabling auto-shutdown at low pellet level")
        self.coordinator.set_auto_shutdown_enabled(False)
        await self.coordinator.async_request_refresh()


class AduroAutoResumeAfterWoodSwitch(AduroSwitchBase):
    """Switch to enable/disable automatic resume after wood mode."""

    def __init__(self, coordinator: AduroCoordinator, entry: ConfigEntry) -> None:
        """Initialize the switch."""
        super().__init__(coordinator, entry, "auto_resume_wood", "auto_resume_wood")
        self._attr_icon = "mdi:restart"

    @property
    def is_on(self) -> bool:
        """Return true if auto-resume is enabled."""
        # Access internal coordinator state
        return self.coordinator._auto_resume_after_wood

    @property
    def icon(self) -> str:
        """Return icon based on state."""
        if self.is_on:
            return "mdi:replay"
        return "mdi:pause"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional attributes."""
        attrs = {
            "in_wood_mode": self.coordinator._was_in_wood_mode,
        }
        
        # Add saved settings if available
        if self.coordinator._pre_wood_mode_operation_mode is not None:
            mode_names = {0: "Heat Level", 1: "Temperature", 2: "Wood"}
            attrs["saved_mode"] = mode_names.get(
                self.coordinator._pre_wood_mode_operation_mode, 
                "Unknown"
            )
            
        if self.coordinator._pre_wood_mode_heatlevel is not None:
            attrs["saved_heatlevel"] = self.coordinator._pre_wood_mode_heatlevel
            
        if self.coordinator._pre_wood_mode_temperature is not None:
            attrs["saved_temperature"] = self.coordinator._pre_wood_mode_temperature
        
        return attrs

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable auto-resume after wood mode."""
        _LOGGER.info("Switch: Enabling auto-resume after wood mode")
        self.coordinator.set_auto_resume_after_wood(True)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable auto-resume after wood mode."""
        _LOGGER.info("Switch: Disabling auto-resume after wood mode")
        self.coordinator.set_auto_resume_after_wood(False)
        await self.coordinator.async_request_refresh()
