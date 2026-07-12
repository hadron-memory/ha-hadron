# Hadron Memory for Home Assistant

Connect [Home Assistant](https://www.home-assistant.io/) to
[Hadron](https://hadronmemory.com) — the access-controlled memory platform for
humans and AI agents. This integration lets your home trigger AI-driven
**headless runs** on a Hadron server, and lets those runs push results and
events back into your home.

No Hadron-side setup beyond a webhook: everything here rides Hadron's
built-in webhook trigger surface.

## What you get

- **`hadron.trigger` service** — fire a Hadron webhook from any automation or
  script, passing Home Assistant state as run arguments. Returns the `run_id`
  as service response data.
- **`hadron_run_finished` event + last-run sensor** — when the run ends,
  Hadron calls back and the result (`status`, `result_node_ref`) lands on the
  Home Assistant event bus and on a per-webhook sensor.
- **Event inbox (`hadron_event`)** — a generic webhook receiver per entry.
  Any Hadron run can POST arbitrary JSON to it (using Hadron's web-fetch run
  tool), so Hadron-initiated flows — scheduled runs, email-triggered runs —
  can drive your home too.

### Example: the desk warning light

A scheduled Hadron run checks your work Slack for questions waiting on you.
When it finds some, it POSTs `{"pending_questions": 3}` to the event inbox,
and this automation turns on the light:

```yaml
automation:
  - alias: "Desk light when Slack needs me"
    trigger:
      - platform: event
        event_type: hadron_event
    condition:
      - condition: template
        value_template: "{{ trigger.event.data.pending_questions | default(0) | int > 0 }}"
    action:
      - service: light.turn_on
        target:
          entity_id: light.desk_warning
        data:
          color_name: red
```

## Installation

### HACS (recommended)

1. HACS → Integrations → ⋮ → **Custom repositories**
2. Add `https://github.com/shadowbrush/ha-hadron`, category **Integration**
3. Install **Hadron Memory**, restart Home Assistant

### Manual

Copy `custom_components/hadron/` into your config's `custom_components/`
directory and restart.

## Setup

1. **Create a webhook in Hadron** (CLI shown; the portal works too):

   ```bash
   hadron webhook create --app acme.com:home --name desk-light \
     --entry acme.com::home::tasks:check-slack
   ```

   This prints the trigger URL path and the platform token (`hpt`) **once** —
   copy both.

2. **Add the integration**: Settings → Devices & Services → Add Integration →
   **Hadron Memory**. Paste the full trigger URL
   (`https://<server>/hooks/<secret>/<name>`) and the token. If your URL
   already contains `?hpt=…`, the token field can stay empty.

3. Repeat for each webhook — one config entry per Hadron webhook.

## Usage

### Trigger a run

```yaml
script:
  ask_hadron:
    sequence:
      - service: hadron.trigger
        data:
          config_entry: !input hadron_entry   # pick in the UI service editor
          args:
            room: office
            occupancy: "{{ states('binary_sensor.office_occupancy') }}"
        response_variable: run
      - service: notify.mobile_app
        data:
          message: "Hadron run {{ run.run_id }} started"
```

### React to the result

```yaml
automation:
  - alias: "Announce Hadron run result"
    trigger:
      - platform: event
        event_type: hadron_run_finished
    action:
      - service: notify.mobile_app
        data:
          message: >-
            Run {{ trigger.event.data.run_id }} finished:
            {{ trigger.event.data.status }}
```

The per-entry **last run** sensor mirrors the same data (state = run status;
attributes carry `run_id`, `result_node_ref`, timestamps).

### Push from Hadron into your home

Each entry's sensor exposes an `event_inbox_path` attribute
(`/api/webhook/<id>`). Give your Hadron flow the full URL
(`https://<your-ha>/api/webhook/<id>`) and have it POST JSON with the
web-fetch run tool — the payload arrives as a `hadron_event` on the bus.

## Notes

- **Result callbacks need an externally reachable Home Assistant URL**
  (Settings → System → Network, or Home Assistant Cloud). Hadron's egress
  policy refuses private/LAN destinations, so without an external URL the
  integration triggers runs without a callback (the run still executes; check
  the run audit in Hadron). Callbacks also consume a `comm.outbound` action
  ticket on the Hadron side — mint tickets for the App if callbacks are
  skipped with `no-ticket`.
- Platform tokens expire (90 days by default). A 404 on trigger means URL,
  token, or enabled-state is wrong — rotate the webhook
  (`hadron webhook rotate`) and re-add the entry with the new credentials.
- Triggering always answers `202 Accepted` with a `run_id`; run results are
  asynchronous by contract.

## Development

```bash
pip install -r requirements_test.txt
pytest
```
