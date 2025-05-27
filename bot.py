#!/usr/bin/env python3
"""
Async Slack /metrics bot (Bolt for Python) over Socket Mode
with a split modal (dates/metric ↑ divider ↓ filter type + value),
dynamic controls, date validation, and soft warnings.
"""

import os, io, datetime, asyncio, logging
from dateutil.relativedelta import relativedelta

from slack_bolt.app.async_app import AsyncApp
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.errors import SlackApiError

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

# ───────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

METRICS = [
    {"text": {"type": "plain_text", "text": "CPU hours"},       "value": "cpu_hours"},
    {"text": {"type": "plain_text", "text": "GPU hours"},       "value": "gpu_hours"},
    {"text": {"type": "plain_text", "text": "Queue wait-time"},"value": "queue_wait"},
]
FILTER_TYPES = [
    {"text": {"type": "plain_text", "text": "N/A"},   "value": "na"},
    {"text": {"type": "plain_text", "text": "User"},  "value": "user"},
    {"text": {"type": "plain_text", "text": "Group"}, "value": "group"},
]
SIX_MONTHS_AGO = (datetime.date.today() - relativedelta(months=6)).isoformat()

def build_modal_view(channel_id, selected_metric, state_values):
    def sv(block_id, action_id):
        # Always return a real string; drop None or non-str values
        if not state_values:
            return ""
        val = state_values.get(block_id, {}).get(action_id, {}).get("value")
        return val if isinstance(val, str) else ""

    # previous filter type (default "na")
    prev_filter = (
        state_values.get("filter_block", {})
                    .get("filter_type", {})
                    .get("selected_option", {})
                    .get("value", "na")
        if state_values else "na"
    )

    blocks = [
        # ── Top: Choose dates ─────────────────────────────────────
        {
            "type": "input",
            "block_id": "start_date_block",
            "label": {"type": "plain_text", "text": "Start date"},
            "element": {
                "type": "datepicker",
                "action_id": "start_date",
                "initial_date": sv("start_date_block", "start_date") or datetime.date.today().isoformat(),
                "placeholder": {"type": "plain_text", "text": f"≥ {SIX_MONTHS_AGO}"},
            }
        },
        {
            "type": "input",
            "block_id": "end_date_block",
            "label": {"type": "plain_text", "text": "End date"},
            "element": {
                "type": "datepicker",
                "action_id": "end_date",
                "initial_date": sv("end_date_block", "end_date") or datetime.date.today().isoformat(),
                "placeholder": {"type": "plain_text", "text": "≤ today"},
            }
        },
        # ── Top: Metric selector ─────────────────────────────────
        {
            "type": "input",
            "block_id": "metric_block",
            "dispatch_action": True,
            "label": {"type": "plain_text", "text": "Metric"},
            "element": (lambda: {
                **{"type": "static_select", "action_id": "metric_select", "options": METRICS},
                **(
                    {"initial_option": next(opt for opt in METRICS if opt["value"] == selected_metric)}
                    if selected_metric else {}
                )
            })()
        },
        {"type": "divider"},
    ]

    # ── Bottom: conditional filtering ──────────────────────────
    if selected_metric in ("cpu_hours", "gpu_hours"):
        # choose filter type
        blocks.append({
            "type": "input",
            "block_id": "filter_block",
            "dispatch_action": True,
            "label": {"type": "plain_text", "text": "Filter Type"},
            "element": {
                "type": "static_select",
                "action_id": "filter_type",
                "options": FILTER_TYPES,
                "initial_option": next(ft for ft in FILTER_TYPES if ft["value"] == prev_filter)
            }
        })
        # if filtering by user or group, show one text input
        if prev_filter in ("user", "group"):
            if prev_filter == "user":
                label_txt = "FASRC Username"
                placeholder = "e.g. jdoe"
            else:
                label_txt = "FASRC Group"
                placeholder = "e.g. analytics"
            init_val = sv("filter_value_block", "filter_value")
            elem = {
                "type": "plain_text_input",
                "action_id": "filter_value",
                "placeholder": {"type": "plain_text", "text": placeholder}
            }
            if init_val:
                elem["initial_value"] = init_val
            blocks.append({
                "type": "input",
                "block_id": "filter_value_block",
                "label": {"type": "plain_text", "text": label_txt},
                "element": elem
            })
    else:
        blocks.append({
            "type": "section",
            "block_id": "no_filter_block",
            "text": {"type": "mrkdwn", "text": "_Filtering not available for Queue wait-time_"}
        })

    return {
        "type": "modal",
        "callback_id": "metrics_modal",
        "private_metadata": channel_id,
        "title": {"type": "plain_text", "text": "Metrics"},
        "submit": {"type": "plain_text", "text": "Generate"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks
    }

def validate_dates(start, end):
    errs = {}
    today = datetime.date.today()
    sd = datetime.date.fromisoformat(start)
    ed = datetime.date.fromisoformat(end)
    if sd > ed:
        errs["start_date_block"] = "Start must be on or before End."
    if sd < today - relativedelta(months=6):
        errs["start_date_block"] = f"Start cannot be earlier than {SIX_MONTHS_AGO}."
    if ed > today:
        errs["end_date_block"] = "End cannot be in the future."
    return errs

# ───────────────────────────────────────────────────────────────
app = AsyncApp(token=os.environ["SLACK_BOT_TOKEN"],
               signing_secret=os.environ["SLACK_SIGNING_SECRET"])

@app.command("/metrics")
async def cmd_metrics(ack, body, client):
    await ack()
    view = build_modal_view(body["channel_id"], None, None)
    logger.debug("Opening modal: %s", view)
    await client.views_open(trigger_id=body["trigger_id"], view=view)

@app.action("metric_select")
async def on_metric_change(ack, body, client):
    await ack()
    selected   = body["actions"][0]["selected_option"]["value"]
    state_vals = body["view"]["state"]["values"]
    new_view   = build_modal_view(body["view"]["private_metadata"], selected, state_vals)
    logger.debug("views_update(metric_select): %s", new_view)
    await client.views_update(
        view_id=body["view"]["id"],
        hash=body["view"]["hash"],
        view=new_view
    )

@app.action("filter_type")
async def on_filter_type_change(ack, body, client):
    await ack()
    state_vals      = body["view"]["state"]["values"]
    selected_metric = state_vals["metric_block"]["metric_select"]["selected_option"]["value"]
    new_view        = build_modal_view(body["view"]["private_metadata"], selected_metric, state_vals)
    logger.debug("views_update(filter_type): %s", new_view)
    await client.views_update(
        view_id=body["view"]["id"],
        hash=body["view"]["hash"],
        view=new_view
    )

@app.view("metrics_modal")
async def on_submit(ack, body, view, client):
    vals   = view["state"]["values"]
    start  = vals["start_date_block"]["start_date"]["selected_date"]
    end    = vals["end_date_block"]["end_date"]["selected_date"]
    metric = vals["metric_block"]["metric_select"]["selected_option"]["value"]
    filt_t = vals.get("filter_block", {}).get("filter_type", {}).get("selected_option", {}).get("value", "na")
    filt_v = vals.get("filter_value_block", {}).get("filter_value", {}).get("value", "")

    errs = validate_dates(start, end)
    if errs:
        await ack(response_action="errors", errors=errs)
        return
    await ack()

    channel = view["private_metadata"]
    user    = body["user"]["id"]

    # Soft warning if filter type != N/A but no value given
    if metric in ("cpu_hours","gpu_hours") and filt_t in ("user","group") and not filt_v:
        await client.chat_postMessage(
            channel=channel,
            blocks=[{
                "type": "context",
                "elements": [{
                    "type": "mrkdwn",
                    "text": ":warning: _No filter value given; showing all results._"
                }]
            }]
        )

    # ... generate and post chart ...

async def main():
    handler = AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    await handler.start_async()

if __name__ == "__main__":
    asyncio.run(main())