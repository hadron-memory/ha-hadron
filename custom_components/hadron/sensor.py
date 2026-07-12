"""Sensor showing the last Hadron run per configured webhook."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CONF_EVENT_WEBHOOK_ID, DOMAIN, SIGNAL_RUN_UPDATE


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the last-run sensor for a config entry."""
    async_add_entities([HadronLastRunSensor(entry)])


class HadronLastRunSensor(SensorEntity):
    """State = status of the most recent run started via this webhook.

    Updated push-style: on trigger (PENDING) and again when Hadron's
    result callback arrives. The event-inbox path is exposed as an
    attribute so users can point a Hadron run's web-fetch call at it.
    """

    _attr_should_poll = False
    _attr_icon = "mdi:memory"
    _attr_translation_key = "last_run"

    def __init__(self, entry: ConfigEntry) -> None:
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_last_run"
        self._attr_name = f"{entry.title} last run"
        self._run: dict[str, Any] = {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Hadron Memory",
            model="Webhook trigger",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://hadronmemory.com",
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to run updates for this entry."""
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_RUN_UPDATE.format(self._entry.entry_id),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self, data: dict[str, Any]) -> None:
        self._run.update({k: v for k, v in data.items() if v is not None})
        self.async_write_ha_state()

    @property
    def native_value(self) -> str | None:
        """The last run's status (PENDING until the callback arrives)."""
        return self._run.get("status")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Run details plus the event-inbox webhook path."""
        return {
            "run_id": self._run.get("run_id"),
            "result_node_ref": self._run.get("result_node_ref"),
            "triggered_at": self._run.get("triggered_at"),
            "finished_at": self._run.get("finished_at"),
            "event_inbox_path": f"/api/webhook/{self._entry.data[CONF_EVENT_WEBHOOK_ID]}",
        }
