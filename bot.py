#!/usr/bin/env python3
"""
Async Slack /metrics bot (Bolt for Python) over Socket Mode
with a split modal (dates/metric/format ↑ divider ↓ filter type + value),
dynamic controls, date validation, soft warnings, and XDMoD integration.
Improved timeseries styling: manager-friendly axis, Harvard IQSS colors,
and a human-readable description.
"""

import os
import io
import datetime
import asyncio
import logging
from itertools import chain
from dateutil.relativedelta import relativedelta

from slack_bolt.app.async_app import AsyncApp
from slack_bolt import Ack
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from prometheus_client import start_http_server, Counter, Histogram, Gauge

from xdmod_data.warehouse import DataWarehouse

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

# ───────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

start_http_server(8000)

# Prometheus metrics definitions
COMMANDS_TOTAL = Counter(
    "slack_commands_total", "Total slash commands received", ["command"]
)
ACTIONS_TOTAL = Counter(
    "slack_actions_total", "Total block actions received", ["action"]
)
VIEWS_TOTAL = Counter(
    "slack_views_total", "Total view submissions received", ["view"]
)
HANDLER_ERRORS = Counter(
    "slack_handler_errors_total", "Total errors in handlers", ["handler"]
)
HANDLERS_IN_PROGRESS = Gauge(
    "slack_handlers_in_progress", "Number of Slack handlers currently in progress"
)

COMMAND_DURATION = Histogram(
    "slack_command_duration_seconds",
    "Time spent handling slash commands",
    ["command"]
)
ACTION_DURATION = Histogram(
    "slack_action_duration_seconds",
    "Time spent handling block actions",
    ["action"]
)
VIEW_DURATION = Histogram(
    "slack_view_duration_seconds",
    "Time spent handling view submissions",
    ["view"]
)

# Map our internal metric keys → XDMoD metric names
METRICS = {
    "cpu_hours": "CPU Hours: Total",
    "gpu_hours": "GPU Hours: Total",
    "queue_wait": "Wait Hours: Total",
}
METRIC_OPTIONS = [
    {"text": {"type": "plain_text", "text": "CPU hours"}, "value": "cpu_hours"},
    {"text": {"type": "plain_text", "text": "GPU hours"}, "value": "gpu_hours"},
    {"text": {"type": "plain_text", "text": "Queue wait-time"}, "value": "queue_wait"},
]

FORMATS = [
    {"text": {"type": "plain_text", "text": "Aggregate"}, "value": "aggregate"},
    {"text": {"type": "plain_text", "text": "Timeseries"}, "value": "timeseries"},
]

FILTER_TYPES = [
    {"text": {"type": "plain_text", "text": "N/A"}, "value": "na"},
    {"text": {"type": "plain_text", "text": "User"}, "value": "user"},
    {"text": {"type": "plain_text", "text": "Group"}, "value": "group"},
]

# Harvard/IQSS color palette (approximate)
PLOT_COLORS = {
    "cpu_hours": "#A51C30",  # Crimson
    "gpu_hours": "#0072CE",  # Harvard Blue
    "queue_wait": "#4B4B4B",  # Dark Gray
}

CACHE_TYPEAHEAD = {"USERS": list(), "PI": list()}

SIX_MONTHS_AGO = (datetime.date.today() - relativedelta(months=6)).isoformat()
XDMOD_URL = os.environ.get("XDMOD_URL", "https://xdmod.rc.fas.harvard.edu")

def build_modal_view(channel_id, selected_metric, state_values):
    def sv(bid, aid):
        if not state_values:
            return ""
        v = state_values.get(bid, {}).get(aid, {}).get("value")
        return v if isinstance(v, str) else ""

    prev_filter = (
        state_values.get("filter_block", {})
        .get("filter_type", {})
        .get("selected_option", {})
        .get("value", "na")
        if state_values
        else "na"
    )
    prev_format = (
        state_values.get("format_block", {})
        .get("format_select", {})
        .get("selected_option", {})
        .get("value", "aggregate")
        if state_values
        else "aggregate"
    )

    blocks = [
        # Dates
        {
            "type": "input",
            "block_id": "start_date_block",
            "label": {"type": "plain_text", "text": "Start date"},
            "element": {
                "type": "datepicker",
                "action_id": "start_date",
                "initial_date": sv("start_date_block", "start_date")
                or datetime.date.today().isoformat(),
                "placeholder": {"type": "plain_text", "text": f"≥ {SIX_MONTHS_AGO}"},
            },
        },
        {
            "type": "input",
            "block_id": "end_date_block",
            "label": {"type": "plain_text", "text": "End date"},
            "element": {
                "type": "datepicker",
                "action_id": "end_date",
                "initial_date": sv("end_date_block", "end_date")
                or datetime.date.today().isoformat(),
                "placeholder": {"type": "plain_text", "text": "≤ today"},
            },
        },
        # Metric selector
        {
            "type": "input",
            "block_id": "metric_block",
            "dispatch_action": True,
            "label": {"type": "plain_text", "text": "Metric"},
            "element": (
                lambda: {
                    **{
                        "type": "static_select",
                        "action_id": "metric_select",
                        "options": METRIC_OPTIONS,
                    },
                    **(
                        {
                            "initial_option": next(
                                (
                                    o
                                    for o in METRIC_OPTIONS
                                    if o["value"] == selected_metric
                                )
                            )
                        }
                        if selected_metric
                        else {}
                    ),
                }
            )(),
        },
        # Format selector (always visible)
        {
            "type": "input",
            "block_id": "format_block",
            "label": {"type": "plain_text", "text": "Format"},
            "element": {
                "type": "static_select",
                "action_id": "format_select",
                "options": FORMATS,
                "initial_option": next(f for f in FORMATS if f["value"] == prev_format),
            },
        },
        {"type": "divider"},
    ]

    # Filters only for CPU/GPU
    if selected_metric in ("cpu_hours", "gpu_hours", "queue_wait"):
        blocks.append(
            {
                "type": "input",
                "block_id": "filter_block",
                "dispatch_action": True,
                "label": {"type": "plain_text", "text": "Filter Type"},
                "element": {
                    "type": "static_select",
                    "action_id": "filter_type",
                    "options": FILTER_TYPES,
                    "initial_option": next(
                        ft for ft in FILTER_TYPES if ft["value"] == prev_filter
                    ),
                },
            }
        )
        if prev_filter in ("user", "group"):
            label_txt = "FASRC Username" if prev_filter == "user" else "FASRC Group"
            placeholder = "e.g. jdoe" if prev_filter == "user" else "e.g. analytics"
            init_val = sv("filter_value_block", "filter_value")
            action_id = (
                "filter_value_user" if prev_filter == "user" else "filter_value_pi"
            )
            elem = {
                "type": "external_select",
                "action_id": action_id,
                "min_query_length": 0,
                "placeholder": {"type": "plain_text", "text": placeholder},
            }
            if init_val:
                elem["initial_value"] = init_val
            blocks.append(
                {
                    "type": "input",
                    "block_id": "filter_value_block",
                    "label": {"type": "plain_text", "text": label_txt},
                    "element": elem,
                }
            )
    else:
        blocks.append(
            {
                "type": "section",
                "block_id": "no_filter_block",
                "text": {
                    "type": "mrkdwn",
                    "text": "No filter block available for selection. You should never see this.",
                },
            }
        )

    return {
        "type": "modal",
        "callback_id": "metrics_modal",
        "private_metadata": channel_id,
        "title": {"type": "plain_text", "text": "Metrics"},
        "submit": {"type": "plain_text", "text": "Generate"},
        "close": {"type": "plain_text", "text": "Cancel"},
        "blocks": blocks,
    }


def build_aggregate_blocks(noun, start, end, who, total):
    return [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{noun} Summary", "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Period:*\n{start} → {end}"},
                {"type": "mrkdwn", "text": f"*Subject:*\n{who}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Total {noun}:* `{total}`"},
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Data extracted from XDMoD {XDMOD_URL}"}
            ],
        },
    ]


def describe_graph(who, noun, start, end):
    return f"This graph shows {who} {noun.lower()} between {start} and {end}."


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


app = AsyncApp(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"],
)


async def make_suggest_options(cache_key, body):
    q = body.get("value", "")
    matches = [c for c in CACHE_TYPEAHEAD[cache_key] if q.lower() in c.lower()][:10]
    options = [{"text": {"type": "plain_text", "text": m}, "value": m} for m in matches]

    if q:
        options.append(
            {"text": {"type": "plain_text", "text": f"Use “{q}”"}, "value": q}
        )

    return options


@app.options("filter_value_user")
async def suggest_filter_values_user(ack, body, logger):
    # what the user has typed so far:
    options = await make_suggest_options("USERS", body)
    await ack(options=options)


@app.options("filter_value_pi")
async def suggest_filter_values_pi(ack, body, logger):
    # what the user has typed so far:
    options = await make_suggest_options("PI", body)
    await ack(options=options)


@app.command("/metrics")
async def cmd_metrics(ack, body, client):
    HANDLERS_IN_PROGRESS.inc()
    COMMANDS_TOTAL.labels(command="/metrics").inc()
    with COMMAND_DURATION.labels(command="/metrics").time():
        try:
            await ack()
            view = build_modal_view(body["channel_id"], "cpu_hours", None)
            await client.views_open(trigger_id=body["trigger_id"], view=view)
        except Exception:
            HANDLER_ERRORS.labels(handler="cmd_metrics").inc()
            raise
        finally:
            HANDLERS_IN_PROGRESS.dec()


@app.action("metric_select")
async def on_metric_change(ack, body, client):
    HANDLERS_IN_PROGRESS.inc()
    ACTIONS_TOTAL.labels(action="metric_select").inc()
    with ACTION_DURATION.labels(action="metric_select").time():
        try:
            await ack()
            sel = body["actions"][0]["selected_option"]["value"]
            svs = body["view"]["state"]["values"]
            new = build_modal_view(body["view"]["private_metadata"], sel, svs)
            await client.views_update(
                view_id=body["view"]["id"], hash=body["view"]["hash"], view=new
            )
        except Exception:
            HANDLER_ERRORS.labels(handler="on_metric_change").inc()
            raise
        finally:
            HANDLERS_IN_PROGRESS.dec()



@app.action("filter_type")
async def on_filter_type_change(ack, body, client):
    HANDLERS_IN_PROGRESS.inc()
    ACTIONS_TOTAL.labels(action="filter_type").inc()
    with ACTION_DURATION.labels(action="filter_type").time():
        try:
            await ack()
            svs = body["view"]["state"]["values"]
            sel_metric = svs["metric_block"]["metric_select"]["selected_option"]["value"]
            new = build_modal_view(body["view"]["private_metadata"], sel_metric, svs)
            await client.views_update(
                view_id=body["view"]["id"], hash=body["view"]["hash"], view=new
            )
        except Exception:
            HANDLER_ERRORS.labels(handler="on_filter_type_change").inc()
            raise
        finally:
            HANDLERS_IN_PROGRESS.dec()

@app.view("metrics_modal")
async def on_submit(ack, body, view, client):
    HANDLERS_IN_PROGRESS.inc()
    VIEWS_TOTAL.labels(view="metrics_modal").inc()

    with VIEW_DURATION.labels(view="metrics_modal").time():
        try:
            vals = view["state"]["values"]
            start = vals["start_date_block"]["start_date"]["selected_date"]
            end = vals["end_date_block"]["end_date"]["selected_date"]
            metric = vals["metric_block"]["metric_select"]["selected_option"]["value"]
            fmt = vals["format_block"]["format_select"]["selected_option"]["value"]
            filt_t = (
                vals.get("filter_block", {})
                .get("filter_type", {})
                .get("selected_option", {})
                .get("value", "na")
            )
            filt_v = ""
            fv_block = vals.get("filter_value_block", {})
            if fv_block:
                act_id, state = next(iter(fv_block.items()))
                filt_v = state.get("selected_option", {}).get("value", "")

            errs = validate_dates(start, end)
            if errs:
                await ack(response_action="errors", errors=errs)
                return
            await ack()

            origin = view["private_metadata"]
            is_dm = origin.startswith("D")
            target = origin

            dw_metric = METRICS[metric]
            noun = metric.replace("_", " ").title()
            dimension = None if filt_t == "na" else ("User" if filt_t == "user" else "PI")
            filters = {} if filt_t == "na" else {dimension: filt_v}
            who = filt_v if filt_t in ("user", "group") else "All Users"
            who = "PI" if who == "group" else who

            with DataWarehouse(XDMOD_URL) as dw:
                if fmt == "aggregate":
                    df = dw.get_data(
                        duration=(start, end),
                        realm="Jobs",
                        metric=dw_metric,
                        dimension=dimension or "None",
                        filters=filters,
                        dataset_type="aggregate",
                    )
                    total = df[dw_metric].item() if dimension == "None" else df.squeeze()
                    blocks = build_aggregate_blocks(noun, start, end, who, total)
                    await client.chat_postMessage(channel=target, blocks=blocks)
                else:
                    df = dw.get_data(
                        duration=(start, end),  # type: ignore
                        realm="Jobs",
                        metric=dw_metric,
                        dimension=dimension or "None",
                        filters=filters,
                        dataset_type="timeseries",
                        aggregation_unit="Auto",
                    )

                    logger.debug(df)

                    x = df.index
                    # Scale to 1
                    if df.empty:
                        blocks = build_aggregate_blocks(
                            noun, start, end, who, "No data returned from query."
                        )
                        return await client.chat_postMessage(channel=target, blocks=blocks)

                    y = df.iloc[:, 0] / 1

                    fig, ax = plt.subplots(figsize=(12, 6), dpi=100)
                    ax.plot(x, y, color=PLOT_COLORS[metric], linewidth=2)
                    ax.set_title(f"{noun} ({start} → {end})", pad=16)
                    ax.set_xlabel("Date")
                    ax.set_ylabel(f"{noun}")
                    # our FuncFormatter already ensures plain numbers:
                    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, p: f"{v:.1f}"))

                    buf = io.BytesIO()
                    fig.savefig(buf, format="png", bbox_inches="tight")
                    buf.seek(0)
                    plt.close(fig)

                    # human-friendly description
                    desc = describe_graph(who, noun, start, end)
                    comment = f"{desc}\n_Data extracted from XDMoD {XDMOD_URL}_"

                    await client.chat_postMessage(channel=target, text=comment)
                    await client.files_upload_v2(
                        file=buf,
                        channels=[target],
                        filename=f"{metric}_{start}_{end}.png",
                        title=f"{noun} {start}→{end}",
                    )
                    buf.close()
        except Exception:
            HANDLER_ERRORS.labels(handler="on_submit").inc()
            raise
        finally:
            HANDLERS_IN_PROGRESS.dec()


async def update_typeahead_cache():
    while True:
        logger.debug(
            f"count(CACHE_TYPEAHEAD[USERS])={len(CACHE_TYPEAHEAD['USERS'])}\t"
            f"count(CACHE_TYPEAHEAD[PI])={len(CACHE_TYPEAHEAD['PI'])}"
        )

        with DataWarehouse(XDMOD_URL) as dw:
            args = {
                "duration": "7 day",
                "realm": "Jobs",
                "metric": "job_count",
                "dataset_type": "aggregate",
            }
            u0 = dw.get_data(**args, dimension="User")
            u1 = sorted(u0.index.unique().tolist())
            g0 = dw.get_data(**args, dimension="PI")
            g1 = sorted(g0.index.unique().tolist())

            CACHE_TYPEAHEAD["USERS"] = list(
                dict.fromkeys(chain(CACHE_TYPEAHEAD["USERS"], u1))
            )
            CACHE_TYPEAHEAD["PI"] = list(
                dict.fromkeys(chain(CACHE_TYPEAHEAD["PI"], g1))
            )

        logger.debug(
            f"count(CACHE_TYPEAHEAD[USERS])={len(CACHE_TYPEAHEAD['USERS'])}\t"
            f"count(CACHE_TYPEAHEAD[PI])={len(CACHE_TYPEAHEAD['PI'])}"
        )

        await asyncio.sleep(100)


async def main():
    handler = AsyncSocketModeHandler(app, os.environ["SLACK_APP_TOKEN"])
    asyncio.create_task(update_typeahead_cache())

    await handler.start_async()


if __name__ == "__main__":
    asyncio.run(main())
