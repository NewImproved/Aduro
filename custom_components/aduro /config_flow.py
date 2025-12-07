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
                    
                    _LOGGER.info(
                        "Updating entry - Model: %s, IP: %s",
                        new_data.get(CONF_STOVE_MODEL),
                        new_data.get(CONF_STOVE_IP, "auto-discovery")
                    )
                    
                    # Update the config entry data
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data=new_data
                    )
                    return self.async_create_entry(title="", data={})
            except Exception as err:
                _LOGGER.exception("Unexpected error in options flow: %s", err)
                errors["base"] = "unknown"

        # Get current values
        current_model = self.config_entry.data.get(CONF_STOVE_MODEL, DEFAULT_STOVE_MODEL)
        current_ip = self.config_entry.data.get(CONF_STOVE_IP, "")

        options_schema = vol.Schema(
            {
                vol.Required(CONF_STOVE_MODEL, default=current_model): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=STOVE_MODELS,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(CONF_STOVE_IP, description={"suggested_value": current_ip}): cv.string,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=errors,
            description_placeholders={
                "model_info": "Update your Aduro stove model",
                "ip_info": "Optional: Enter a fixed IP address for your stove. Leave empty for automatic discovery."
            },
        )
