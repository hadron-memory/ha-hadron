"""The Hadron integration.

Connects Home Assistant to a Hadron webhook (https://hadronmemory.com):

- the ``hadron.trigger`` service fires the webhook, which starts a headless
  run on the Hadron server (always answered 202 + runId — the work is
  asynchronous by contract);
- when the run finishes, Hadron POSTs a result callback to a Home Assistant
  webhook this integration registers, fired onto the bus as
  ``hadron_run_finished``;
- a second, generic "event inbox" webhook lets any Hadron run push arbitrary
  JSON into Home Assistant (fired as ``hadron_event``) using Hadron's
  web-fetch run tool — no Hadron-side code required.
"""
from __future__ import annotations

import logging
from functools import partial
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.components import webhook
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.network import NoURLAvailableError, get_url
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_ARGS,
    ATTR_CALLBACK,
    ATTR_CONFIG_ENTRY,
    CONF_CALLBACK_WEBHOOK_ID,
    CONF_EVENT_WEBHOOK_ID,
    CONF_TOKEN,
    CONF_URL,
    DOMAIN,
    EVENT_HADRON_EVENT,
    EVENT_RUN_FINISHED,
    EVENT_RUN_STARTED,
    OPT_ENABLE_CALLBACK,
    REQUEST_TIMEOUT_S,
    SERVICE_TRIGGER,
    SIGNAL_RUN_UPDATE,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor"]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

SERVICE_TRIGGER_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CONFIG_ENTRY): cv.string,
        vol.Optional(ATTR_ARGS): dict,
        vol.Optional(ATTR_CALLBACK): cv.boolean,
    }
)


class HadronWebhook:
    """Runtime for one configured Hadron webhook trigger."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.url: str = entry.data[CONF_URL]
        self.token: str = entry.data[CONF_TOKEN]

    @property
    def callback_enabled(self) -> bool:
        """Whether run-result callbacks are requested by default."""
        return self.entry.options.get(OPT_ENABLE_CALLBACK, True)

    def _callback_url(self) -> str | None:
        """Externally reachable URL of this entry's callback webhook.

        Hadron's egress policy refuses private/reserved destinations, so
        only an external URL is worth sending. None disables the callback.
        """
        try:
            base = get_url(self.hass, prefer_external=True, allow_internal=False)
        except NoURLAvailableError:
            return None
        webhook_id = self.entry.data[CONF_CALLBACK_WEBHOOK_ID]
        return f"{base}/api/webhook/{webhook_id}"

    async def async_trigger(
        self, args: dict[str, Any], want_callback: bool | None
    ) -> dict[str, Any]:
        """Fire the Hadron webhook; return {run_id, status} from the 202.

        A callbackUrl the server rejects (egress policy) fails the whole
        trigger with a 400, so that case is retried once without it.
        """
        use_callback = self.callback_enabled if want_callback is None else want_callback
        body: dict[str, Any] = dict(args)
        if use_callback:
            callback_url = self._callback_url()
            if callback_url:
                body["callbackUrl"] = callback_url
            else:
                _LOGGER.warning(
                    "Hadron %s: no external URL configured for Home Assistant; "
                    "triggering without a result callback",
                    self.entry.title,
                )

        response = await self._post(body)
        if response.status == 400 and "callbackUrl" in body:
            payload = await _safe_json(response)
            _LOGGER.warning(
                "Hadron %s rejected the callback URL (%s); retrying without it",
                self.entry.title,
                payload.get("error"),
            )
            body.pop("callbackUrl")
            response = await self._post(body)

        payload = await _safe_json(response)
        if response.status == 202:
            run_id = payload.get("runId")
            data = {
                "run_id": run_id,
                "status": payload.get("status", "PENDING"),
                "triggered_at": dt_util.utcnow().isoformat(),
            }
            self.hass.bus.async_fire(
                EVENT_RUN_STARTED, {"entry_id": self.entry.entry_id, **data}
            )
            async_dispatcher_send(
                self.hass, SIGNAL_RUN_UPDATE.format(self.entry.entry_id), data
            )
            return {"run_id": run_id, "status": payload.get("status", "PENDING")}
        if response.status == 404:
            raise HomeAssistantError(
                "Hadron answered 404: the trigger URL or platform token is "
                "wrong, the token has expired, or the webhook is disabled. "
                "Rotate the webhook in Hadron and reconfigure this entry."
            )
        if response.status == 429:
            raise HomeAssistantError(
                f"Hadron denied the run launch: {payload.get('error', 'quota/policy')}"
            )
        raise HomeAssistantError(
            f"Hadron trigger failed with HTTP {response.status}: "
            f"{payload.get('error', 'unknown error')}"
        )

    async def _post(self, body: dict[str, Any]) -> aiohttp.ClientResponse:
        session = async_get_clientsession(self.hass)
        try:
            return await session.post(
                self.url,
                params={"hpt": self.token},
                json=body,
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_S),
            )
        except (aiohttp.ClientError, TimeoutError) as err:
            raise HomeAssistantError(f"Could not reach Hadron: {err}") from err


async def _safe_json(response: aiohttp.ClientResponse) -> dict[str, Any]:
    """Best-effort JSON body; error surfaces must not mask the HTTP status."""
    try:
        data = await response.json(content_type=None)
    except (aiohttp.ClientError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


async def _handle_run_callback(
    entry_id: str, hass: HomeAssistant, webhook_id: str, request
) -> None:
    """Receive Hadron's terminal-status run callback."""
    try:
        payload = await request.json()
    except ValueError:
        _LOGGER.warning("Hadron run callback with non-JSON body ignored")
        return
    if not isinstance(payload, dict):
        return
    data = {
        "entry_id": entry_id,
        "run_id": payload.get("runId"),
        "status": payload.get("status"),
        "result_node_ref": payload.get("resultNodeRef"),
        "finished_at": payload.get("finishedAt"),
    }
    hass.bus.async_fire(EVENT_RUN_FINISHED, data)
    async_dispatcher_send(hass, SIGNAL_RUN_UPDATE.format(entry_id), data)


async def _handle_event_inbox(
    entry_id: str, hass: HomeAssistant, webhook_id: str, request
) -> None:
    """Receive arbitrary JSON pushed by a Hadron run (web-fetch tool)."""
    try:
        payload = await request.json()
    except ValueError:
        _LOGGER.warning("Hadron event inbox: non-JSON body ignored")
        return
    if not isinstance(payload, dict):
        payload = {"data": payload}
    hass.bus.async_fire(EVENT_HADRON_EVENT, {"entry_id": entry_id, **payload})


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register the domain-level hadron.trigger service."""

    async def _handle_trigger(call: ServiceCall) -> ServiceResponse:
        entry_id: str = call.data[ATTR_CONFIG_ENTRY]
        runtime: HadronWebhook | None = hass.data.get(DOMAIN, {}).get(entry_id)
        if runtime is None:
            raise HomeAssistantError(
                f"No loaded Hadron webhook for config entry {entry_id!r}"
            )
        result = await runtime.async_trigger(
            call.data.get(ATTR_ARGS) or {}, call.data.get(ATTR_CALLBACK)
        )
        return result if call.return_response else None

    hass.services.async_register(
        DOMAIN,
        SERVICE_TRIGGER,
        _handle_trigger,
        schema=SERVICE_TRIGGER_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up one Hadron webhook from a config entry."""
    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = HadronWebhook(hass, entry)

    webhook.async_register(
        hass,
        DOMAIN,
        f"{entry.title} run callback",
        entry.data[CONF_CALLBACK_WEBHOOK_ID],
        partial(_handle_run_callback, entry.entry_id),
        allowed_methods=["POST"],
    )
    webhook.async_register(
        hass,
        DOMAIN,
        f"{entry.title} event inbox",
        entry.data[CONF_EVENT_WEBHOOK_ID],
        partial(_handle_event_inbox, entry.entry_id),
        allowed_methods=["POST"],
    )
    _LOGGER.info(
        "Hadron %s: event inbox path is /api/webhook/%s",
        entry.title,
        entry.data[CONF_EVENT_WEBHOOK_ID],
    )

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    webhook.async_unregister(hass, entry.data[CONF_CALLBACK_WEBHOOK_ID])
    webhook.async_unregister(hass, entry.data[CONF_EVENT_WEBHOOK_ID])
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    return unload_ok
