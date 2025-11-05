"""The Aduro Hybrid Stove integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryNotReady

from .const import DOMAIN, PLATFORMS
from .coordinator import AduroCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Aduro Hybrid Stove from a config entry."""
    _LOGGER.debug("Setting up Aduro integration for entry: %s", entry.entry_id)

    # Create and setup the coordinator
    coordinator = AduroCoordinator(hass, entry)

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator in hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Forward setup to platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Register services
    await async_setup_services(hass, coordinator)

    # Setup update listener for options changes
    entry.async_on_unload(entry.add_update_listener(async_reload_entry))

    _LOGGER.info("Aduro integration setup completed for %s", entry.title)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    _LOGGER.debug("Unloading Aduro integration for entry: %s", entry.entry_id)

    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Remove coordinator from hass.data
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        
        # Clean up if this was the last entry
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)
            # Unregister services
            await async_unload_services(hass)

    return unload_ok


async def async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload config entry when options change."""
    _LOGGER.debug("Reloading Aduro integration for entry: %s", entry.entry_id)
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_services(hass: HomeAssistant, coordinator: AduroCoordinator) -> None:
    """Set up services for Aduro integration."""
    from homeassistant.helpers import config_validation as cv
    import voluptuous as vol

    from .const import (
        SERVICE_START_STOVE,
        SERVICE_STOP_STOVE,
        SERVICE_SET_HEATLEVEL,
        SERVICE_SET_TEMPERATURE,
        SERVICE_SET_OPERATION_MODE,
        SERVICE_TOGGLE_MODE,
        SERVICE_REFILL_PELLETS,
        SERVICE_CLEAN_STOVE,
        SERVICE_RESUME_AFTER_WOOD,
        HEAT_LEVEL_MIN,
        HEAT_LEVEL_MAX,
        TEMP_MIN,
        TEMP_MAX,
    )

    # Skip if services already registered
    if hass.services.has_service(DOMAIN, SERVICE_START_STOVE):
        return

    async def handle_start_stove(call):
        """Handle start stove service call."""
        _LOGGER.debug("Service called: start_stove")
        # Get all coordinators and start them
        for entry_id, coord in hass.data[DOMAIN].items():
            if isinstance(coord, AduroCoordinator):
                success = await coord.async_start_stove()
                if success:
                    _LOGGER.info("Stove started successfully")
                else:
                    _LOGGER.error("Failed to start stove")

    async def handle_stop_stove(call):
        """Handle stop stove service call."""
        _LOGGER.debug("Service called: stop_stove")
        for entry_id, coord in hass.data[DOMAIN].items():
            if isinstance(coord, AduroCoordinator):
                success = await coord.async_stop_stove()
                if success:
                    _LOGGER.info("Stove stopped successfully")
                else:
                    _LOGGER.error("Failed to stop stove")

    async def handle_set_heatlevel(call):
        """Handle set heatlevel service call."""
        heatlevel = call.data.get("heatlevel")
        _LOGGER.debug("Service called: set_heatlevel, level=%s", heatlevel)
        
        for entry_id, coord in hass.data[DOMAIN].items():
            if isinstance(coord, AduroCoordinator):
                success = await coord.async_set_heatlevel(heatlevel)
                if success:
                    _LOGGER.info("Heat level set to %s", heatlevel)
                else:
                    _LOGGER.error("Failed to set heat level")

    async def handle_set_temperature(call):
        """Handle set temperature service call."""
        temperature = call.data.get("temperature")
        _LOGGER.debug("Service called: set_temperature, temp=%s", temperature)
        
        for entry_id, coord in hass.data[DOMAIN].items():
            if isinstance(coord, AduroCoordinator):
                success = await coord.async_set_temperature(temperature)
                if success:
                    _LOGGER.info("Temperature set to %s", temperature)
                else:
                    _LOGGER.error("Failed to set temperature")

    async def handle_set_operation_mode(call):
        """Handle set operation mode service call."""
        mode = call.data.get("mode")
        _LOGGER.debug("Service called: set_operation_mode, mode=%s", mode)
        
        for entry_id, coord in hass.data[DOMAIN].items():
            if isinstance(coord, AduroCoordinator):
                success = await coord.async_set_operation_mode(mode)
                if success:
                    _LOGGER.info("Operation mode set to %s", mode)
                else:
                    _LOGGER.error("Failed to set operation mode")

    async def handle_toggle_mode(call):
        """Handle toggle mode service call (switch between heatlevel and temperature)."""
        _LOGGER.debug("Service called: toggle_mode")
        
        for entry_id, coord in hass.data[DOMAIN].items():
            if isinstance(coord, AduroCoordinator):
                # Get current mode from coordinator data
                current_mode = 0
                if coord.data and "status" in coord.data:
                    current_mode = coord.data["status"].get("operation_mode", 0)
                
                # Toggle between mode 0 (heatlevel) and mode 1 (temperature)
                new_mode = 1 if current_mode == 0 else 0
                
                success = await coord.async_set_operation_mode(new_mode)
                if success:
                    _LOGGER.info("Toggled operation mode from %s to %s", current_mode, new_mode)
                else:
                    _LOGGER.error("Failed to toggle operation mode")

    async def handle_force_auger(call):
        """Handle force auger service call."""
        _LOGGER.debug("Service called: force_auger")
        
        for entry_id, coord in hass.data[DOMAIN].items():
            if isinstance(coord, AduroCoordinator):
                success = await coord.async_force_auger()
                if success:
                    _LOGGER.info("Auger forced successfully")
                else:
                    _LOGGER.error("Failed to force auger")

    async def handle_set_custom(call):
        """Handle set custom parameter service call."""
        path = call.data.get("path")
        value = call.data.get("value")
        _LOGGER.debug("Service called: set_custom, path=%s, value=%s", path, value)
        
        for entry_id, coord in hass.data[DOMAIN].items():
            if isinstance(coord, AduroCoordinator):
                success = await coord.async_set_custom(path, value)
                if success:
                    _LOGGER.info("Custom parameter set: %s = %s", path, value)
                else:
                    _LOGGER.error("Failed to set custom parameter")

    async def handle_resume_after_wood(call):
        """Handle resume after wood mode service call."""
        _LOGGER.debug("Service called: resume_after_wood_mode")
        
        for entry_id, coord in hass.data[DOMAIN].items():
            if isinstance(coord, AduroCoordinator):
                success = await coord.async_resume_after_wood_mode()
                if success:
                    _LOGGER.info("Resumed pellet operation after wood mode")
                else:
                    _LOGGER.error("Failed to resume after wood mode")

    # Register services
    hass.services.async_register(
        DOMAIN,
        SERVICE_START_STOVE,
        handle_start_stove,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_STOP_STOVE,
        handle_stop_stove,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_HEATLEVEL,
        handle_set_heatlevel,
        schema=vol.Schema({
            vol.Required("heatlevel"): vol.All(
                vol.Coerce(int),
                vol.Range(min=HEAT_LEVEL_MIN, max=HEAT_LEVEL_MAX)
            ),
        }),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_TEMPERATURE,
        handle_set_temperature,
        schema=vol.Schema({
            vol.Required("temperature"): vol.All(
                vol.Coerce(float),
                vol.Range(min=TEMP_MIN, max=TEMP_MAX)
            ),
        }),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_SET_OPERATION_MODE,
        handle_set_operation_mode,
        schema=vol.Schema({
            vol.Required("mode"): vol.All(
                vol.Coerce(int),
                vol.In([0, 1, 2])
            ),
        }),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_TOGGLE_MODE,
        handle_toggle_mode,
    )

    hass.services.async_register(
        DOMAIN,
        "force_auger",
        handle_force_auger,
    )

    hass.services.async_register(
        DOMAIN,
        "set_custom",
        handle_set_custom,
        schema=vol.Schema({
            vol.Required("path"): cv.string,
            vol.Required("value"): vol.Any(str, int, float),
        }),
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_RESUME_AFTER_WOOD,
        handle_resume_after_wood,
    )

    _LOGGER.info("Aduro services registered")


async def async_unload_services(hass: HomeAssistant) -> None:
    """Unload Aduro services."""
    from .const import (
        SERVICE_START_STOVE,
        SERVICE_STOP_STOVE,
        SERVICE_SET_HEATLEVEL,
        SERVICE_SET_TEMPERATURE,
        SERVICE_SET_OPERATION_MODE,
        SERVICE_TOGGLE_MODE,
        SERVICE_RESUME_AFTER_WOOD,
    )

    services = [
        SERVICE_START_STOVE,
        SERVICE_STOP_STOVE,
        SERVICE_SET_HEATLEVEL,
        SERVICE_SET_TEMPERATURE,
        SERVICE_SET_OPERATION_MODE,
        SERVICE_TOGGLE_MODE,
        SERVICE_RESUME_AFTER_WOOD,
        "force_auger",
        "set_custom",
    ]

    for service in services:
        if hass.services.has_service(DOMAIN, service):
            hass.services.async_remove(DOMAIN, service)

    _LOGGER.info("Aduro services unregistered")
