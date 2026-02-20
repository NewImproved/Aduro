"""Config flow for Aduro Hybrid Stove integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv
import ipaddress

from .const import (
    DOMAIN,
    CONF_STOVE_SERIAL,
    CONF_STOVE_PIN,
    CONF_STOVE_MODEL,
    CONF_STOVE_IP,
    CONF_EXTERNAL_TEMP_SENSOR,
    CONF_WEATHER_FORECAST_SENSOR,
    DEFAULT_STOVE_MODEL,
    STOVE_MODELS,
)

_LOGGER = logging.getLogger(__name__)


class AduroConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Aduro Hybrid Stove."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                # Validate IP address if provided and not empty
                stove_ip = user_input.get(CONF_STOVE_IP, "").strip()
                if stove_ip:
                    try:
                        ipaddress.IPv4Address(stove_ip)
                        user_input[CONF_STOVE_IP] = stove_ip
                    except ipaddress.AddressValueError as err:
                        _LOGGER.warning("Invalid IP address: %s - %s", stove_ip, err)
                        errors[CONF_STOVE_IP] = "invalid_ip"
                else:
                    user_input.pop(CONF_STOVE_IP, None)
                
                if not errors:
                    # Set unique ID based on serial number
                    await self.async_set_unique_id(user_input[CONF_STOVE_SERIAL])
                    self._abort_if_unique_id_configured()

                    # Create the config entry
                    stove_model = user_input.get(CONF_STOVE_MODEL, DEFAULT_STOVE_MODEL)
                    
                    _LOGGER.info(
                        "Creating entry for Aduro %s - Serial: %s, IP: %s",
                        stove_model,
                        user_input[CONF_STOVE_SERIAL],
                        user_input.get(CONF_STOVE_IP, "auto-discovery")
                    )
                    
                    return self.async_create_entry(
                        title=f"Aduro {stove_model} ({user_input[CONF_STOVE_SERIAL]})",
                        data=user_input,
                    )
            except Exception as err:
                _LOGGER.exception("Unexpected error in config flow: %s", err)
                errors["base"] = "unknown"

        # Define the configuration schema
        data_schema = vol.Schema(
            {
                vol.Required(CONF_STOVE_MODEL, default=DEFAULT_STOVE_MODEL): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=STOVE_MODELS,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_STOVE_SERIAL): cv.string,
                vol.Required(CONF_STOVE_PIN): cv.string,
                vol.Optional(CONF_STOVE_IP, description={"suggested_value": ""}): cv.string,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "model_info": "Select your Aduro stove model (H1, H2, H3, H4, H5, or H6)",
                "ip_info": "Optional: Enter a fixed IP address for your stove. Leave empty for automatic discovery."
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> AduroOptionsFlowHandler:
        """Get the options flow for this handler."""
        return AduroOptionsFlowHandler(config_entry)


class AduroOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Aduro integration."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        self.config_entry = config_entry
        """Initialize options flow."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                # Validate IP address if provided and not empty
                stove_ip = user_input.get(CONF_STOVE_IP, "").strip()
                if stove_ip:
                    try:
                        ipaddress.IPv4Address(stove_ip)
                        user_input[CONF_STOVE_IP] = stove_ip
                    except ipaddress.AddressValueError as err:
                        _LOGGER.warning("Invalid IP address: %s - %s", stove_ip, err)
                        errors[CONF_STOVE_IP] = "invalid_ip"
                else:
                    user_input.pop(CONF_STOVE_IP, None)
                
                # Validate external temperature sensor if provided
                external_temp_sensor = user_input.get(CONF_EXTERNAL_TEMP_SENSOR, "").strip()
                if external_temp_sensor:
                    # Check if entity exists
                    state = self.hass.states.get(external_temp_sensor)
                    if state is None:
                        _LOGGER.warning("External temperature sensor not found: %s", external_temp_sensor)
                        errors[CONF_EXTERNAL_TEMP_SENSOR] = "sensor_not_found"
                    else:
                        user_input[CONF_EXTERNAL_TEMP_SENSOR] = external_temp_sensor
                else:
                    user_input.pop(CONF_EXTERNAL_TEMP_SENSOR, None)

                # Validate weather forecast sensor if provided
                weather_forecast_sensor = user_input.get(CONF_WEATHER_FORECAST_SENSOR, "").strip()
                if weather_forecast_sensor:
                    # Check if entity exists and is a weather entity
                    state = self.hass.states.get(weather_forecast_sensor)
                    if state is None:
                        _LOGGER.warning("Weather forecast sensor not found: %s", weather_forecast_sensor)
                        errors[CONF_WEATHER_FORECAST_SENSOR] = "sensor_not_found"
                    elif not weather_forecast_sensor.startswith("weather."):
                        _LOGGER.warning("Entity is not a weather entity: %s", weather_forecast_sensor)
                        errors[CONF_WEATHER_FORECAST_SENSOR] = "not_weather_entity"
                    else:
                        # Entity exists and is a weather entity - accept it
                        user_input[CONF_WEATHER_FORECAST_SENSOR] = weather_forecast_sensor
                        _LOGGER.info("Configured weather forecast sensor: %s", weather_forecast_sensor)
                else:
                    user_input.pop(CONF_WEATHER_FORECAST_SENSOR, None)

                if not errors:
                    # Merge with existing data, preserving serial and PIN
                    new_data = {
                        **self.config_entry.data,
                        CONF_STOVE_MODEL: user_input.get(CONF_STOVE_MODEL, self.config_entry.data.get(CONF_STOVE_MODEL)),
                    }
                    
                    # Handle IP: add if present, remove if empty
                    if CONF_STOVE_IP in user_input:
                        new_data[CONF_STOVE_IP] = user_input[CONF_STOVE_IP]
                    else:
                        new_data.pop(CONF_STOVE_IP, None)
                    
                    # Handle external temp sensor: add if present, remove if empty
                    if CONF_EXTERNAL_TEMP_SENSOR in user_input:
                        new_data[CONF_EXTERNAL_TEMP_SENSOR] = user_input[CONF_EXTERNAL_TEMP_SENSOR]
                    else:
                        new_data.pop(CONF_EXTERNAL_TEMP_SENSOR, None)
                    
                    # Handle weather forecast sensor: add if present, remove if empty
                    if CONF_WEATHER_FORECAST_SENSOR in user_input:
                        new_data[CONF_WEATHER_FORECAST_SENSOR] = user_input[CONF_WEATHER_FORECAST_SENSOR]
                    else:
                        new_data.pop(CONF_WEATHER_FORECAST_SENSOR, None)
                    
                    _LOGGER.info(
                        "Updating entry - Model: %s, IP: %s, External Temp Sensor: %s",
                        new_data.get(CONF_STOVE_MODEL),
                        new_data.get(CONF_STOVE_IP, "auto-discovery"),
                        new_data.get(CONF_EXTERNAL_TEMP_SENSOR, "not configured")
                    )
                    
                    # Update the config entry data
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data=new_data
                    )
                                      
                    # Reload the integration so async_setup_entry runs again
                    await self.hass.config_entries.async_reload(self.config_entry.entry_id)

                    return self.async_create_entry(title="", data={})
            except Exception as err:
                _LOGGER.exception("Unexpected error in options flow: %s", err)
                errors["base"] = "unknown"

        # Get current values
        current_model = self.config_entry.data.get(CONF_STOVE_MODEL, DEFAULT_STOVE_MODEL)
        current_ip = self.config_entry.data.get(CONF_STOVE_IP, "")
        current_external_temp = self.config_entry.data.get(CONF_EXTERNAL_TEMP_SENSOR, "")

        # Get current values
        current_model = self.config_entry.data.get(CONF_STOVE_MODEL, DEFAULT_STOVE_MODEL)
        current_ip = self.config_entry.data.get(CONF_STOVE_IP, "")
        current_external_temp = self.config_entry.data.get(CONF_EXTERNAL_TEMP_SENSOR, "")
        current_weather_forecast = self.config_entry.data.get(CONF_WEATHER_FORECAST_SENSOR, "")

        options_schema = vol.Schema(
            {
                vol.Required(CONF_STOVE_MODEL, default=current_model): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=STOVE_MODELS,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_STOVE_IP, description={"suggested_value": current_ip}): cv.string,
                vol.Optional(CONF_EXTERNAL_TEMP_SENSOR, description={"suggested_value": current_external_temp}): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["sensor", "weather"],
                    )
                ),
                vol.Optional(CONF_WEATHER_FORECAST_SENSOR, description={"suggested_value": current_weather_forecast}): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=["weather"],
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=errors,
            description_placeholders={
                "model_info": "Update your Aduro stove model",
                "ip_info": "Optional: Enter a fixed IP address for your stove. Leave empty for automatic discovery.",
                "external_temp_info": "Optional: Select an external temperature sensor for improved pellet depletion predictions.",
                "weather_forecast_info": "Optional: Select a weather forecast entity for advanced predictions using forecasted temperatures."
            },
        )
