"""Config flow for Aduro Hybrid Stove integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector
import homeassistant.helpers.config_validation as cv

from .const import (
    DOMAIN,
    CONF_STOVE_SERIAL,
    CONF_STOVE_PIN,
    CONF_STOVE_MODEL,
    CONF_MQTT_HOST,
    CONF_MQTT_PORT,
    CONF_MQTT_USERNAME,
    CONF_MQTT_PASSWORD,
    CONF_MQTT_BASE_PATH,
    DEFAULT_MQTT_PORT,
    DEFAULT_STOVE_MODEL,
    STOVE_MODELS,
    STOVE_MODEL_BASE_PATHS,
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
            # Set unique ID based on serial number
            await self.async_set_unique_id(user_input[CONF_STOVE_SERIAL])
            self._abort_if_unique_id_configured()

            # Auto-set MQTT base path based on model selection
            stove_model = user_input.get(CONF_STOVE_MODEL, DEFAULT_STOVE_MODEL)
            user_input[CONF_MQTT_BASE_PATH] = STOVE_MODEL_BASE_PATHS[stove_model]

            # Create the config entry
            return self.async_create_entry(
                title=f"Aduro {stove_model} ({user_input[CONF_STOVE_SERIAL]})",
                data=user_input,
            )

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
                vol.Required(CONF_MQTT_HOST): cv.string,
                vol.Optional(CONF_MQTT_PORT, default=DEFAULT_MQTT_PORT): cv.port,
                vol.Optional(CONF_MQTT_USERNAME): cv.string,
                vol.Optional(CONF_MQTT_PASSWORD): cv.string,
            }
        )

        return self.async_show_form(
            step_id="user",
            data_schema=data_schema,
            errors=errors,
            description_placeholders={
                "model_info": "Select your Aduro stove model (H1, H2, H3, or H4)"
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
        self.config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Update MQTT base path if model changed
            if CONF_STOVE_MODEL in user_input:
                stove_model = user_input[CONF_STOVE_MODEL]
                user_input[CONF_MQTT_BASE_PATH] = STOVE_MODEL_BASE_PATHS[stove_model]

            # Update the config entry
            return self.async_create_entry(title="", data=user_input)

        # Get current values
        current_model = self.config_entry.data.get(CONF_STOVE_MODEL, DEFAULT_STOVE_MODEL)
        current_mqtt_host = self.config_entry.data.get(CONF_MQTT_HOST, "")
        current_mqtt_port = self.config_entry.data.get(CONF_MQTT_PORT, DEFAULT_MQTT_PORT)
        current_mqtt_username = self.config_entry.data.get(CONF_MQTT_USERNAME, "")
        current_mqtt_password = self.config_entry.data.get(CONF_MQTT_PASSWORD, "")

        options_schema = vol.Schema(
            {
                vol.Required(CONF_STOVE_MODEL, default=current_model): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=STOVE_MODELS,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(CONF_MQTT_HOST, default=current_mqtt_host): cv.string,
                vol.Optional(CONF_MQTT_PORT, default=current_mqtt_port): cv.port,
                vol.Optional(CONF_MQTT_USERNAME, default=current_mqtt_username): cv.string,
                vol.Optional(CONF_MQTT_PASSWORD, default=current_mqtt_password): cv.string,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=options_schema,
            errors=errors,
            description_placeholders={
                "model_info": "Update your Aduro stove model or MQTT settings"
            },
        )
