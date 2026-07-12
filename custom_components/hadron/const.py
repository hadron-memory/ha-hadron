"""Constants for the Hadron integration."""

DOMAIN = "hadron"

CONF_URL = "url"
CONF_TOKEN = "token"
CONF_CALLBACK_WEBHOOK_ID = "callback_webhook_id"
CONF_EVENT_WEBHOOK_ID = "event_webhook_id"

OPT_ENABLE_CALLBACK = "enable_callback"

SERVICE_TRIGGER = "trigger"
ATTR_CONFIG_ENTRY = "config_entry"
ATTR_ARGS = "args"
ATTR_CALLBACK = "callback"

EVENT_RUN_STARTED = "hadron_run_started"
EVENT_RUN_FINISHED = "hadron_run_finished"
EVENT_HADRON_EVENT = "hadron_event"

SIGNAL_RUN_UPDATE = "hadron_run_update_{}"

REQUEST_TIMEOUT_S = 30
