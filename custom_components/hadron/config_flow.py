"""Config flow for the Hadron integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.components import webhook
from homeassistant.core import callback

from .const import (
    CONF_CALLBACK_WEBHOOK_ID,
    CONF_EVENT_WEBHOOK_ID,
    CONF_TOKEN,
    CONF_URL,
    DOMAIN,
    OPT_ENABLE_CALLBACK,
)
from .util import InvalidTriggerUrl, parse_trigger_url

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_URL): str,
        vol.Optional(CONF_TOKEN): str,
        vol.Optional("name"): str,
    }
)


class HadronConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle adding a Hadron webhook.

    One config entry per Hadron webhook; the trigger URL's opaque secret is
    the unique id, so the same webhook cannot be added twice.
    """

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Collect the trigger URL and platform token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                parsed = parse_trigger_url(user_input[CONF_URL])
            except InvalidTriggerUrl:
                errors[CONF_URL] = "invalid_url"
            else:
                # The hpt may be pasted embedded in the URL or separately;
                # the separate field wins when both are present.
                token = (user_input.get(CONF_TOKEN) or "").strip() or parsed.token
                if not token:
                    errors[CONF_TOKEN] = "token_required"
                else:
                    await self.async_set_unique_id(parsed.secret)
                    self._abort_if_unique_id_configured()
                    title = (user_input.get("name") or "").strip() or parsed.name
                    return self.async_create_entry(
                        title=title,
                        data={
                            CONF_URL: parsed.url,
                            CONF_TOKEN: token,
                            CONF_CALLBACK_WEBHOOK_ID: webhook.async_generate_id(),
                            CONF_EVENT_WEBHOOK_ID: webhook.async_generate_id(),
                        },
                    )

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow."""
        return HadronOptionsFlow()


class HadronOptionsFlow(config_entries.OptionsFlow):
    """Options: toggle the default result callback."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> config_entries.ConfigFlowResult:
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        OPT_ENABLE_CALLBACK,
                        default=self.config_entry.options.get(
                            OPT_ENABLE_CALLBACK, True
                        ),
                    ): bool,
                }
            ),
        )
