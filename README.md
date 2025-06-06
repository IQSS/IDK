# IDK: The Slack XDMoD metrics robot

This is an asynchronous Slack bot (built with Bolt for Python) that lets users generate CPU, GPU, or queue wait–time reports (aggregate or timeseries) directly in Slack. It integrates with XDMoD Data Warehouse to fetch usage data, renders professional charts in the Harvard IQSS style, and posts results back into Slack (in channels or DMs). You can filter by user or group, choose a date range (up to 6 months ago), and view either a single aggregate number or a full timeseries graph. It also exposes a Prometheus endpoint for telemetry, so you can monitor handler latencies, error counts, and throughput.

Evan Sarmiento 
Institute for Quantitative Social Science (IQSS)
Harvard University
<esarmien@iq.harvard.edu>

---

## Table of Contents

1. [Features](#features)  
2. [Prerequisites](#prerequisites)  
3. [Development Setup](#development-setup)  
   - [Install Python via asdf on macOS](#install-python-via-asdf-on-macos)  
   - [Install Dependencies with `uv`](#install-dependencies-with-uv)  
4. [Running Locally](#running-locally)  
5. [Docker Setup](#docker-setup)  
   - [Using OrbStack on macOS](#using-orbstack-on-macos)  
   - [Building the Docker Image](#building-the-docker-image)  
   - [Running the Container](#running-the-container)  
6. [Environment Variables](#environment-variables)  
7. [How to Add This App to Your Slack Workspace](#how-to-add-this-app-to-your-slack-workspace)  
   - [Create a Slack App & Enable Socket Mode](#create-a-slack-app--enable-socket-mode)  
   - [Configure Scopes, Slash Command, and Interactivity](#configure-scopes-slash-command-and-interactivity)  
   - [Obtain and Export Environment Variables](#obtain-and-export-environment-variables)  
8. [Prometheus Telemetry](#prometheus-telemetry)  
9. [Troubleshooting](#troubleshooting)  
10. [License](#license)  

---

## Features

- Slash command `/metrics` to open a modal for date range, metric, format (aggregate/timeseries), and optional user/group filters.  
- Supports CPU hours, GPU hours, or queue wait–time metrics from XDMoD.  
- Aggregate summary (single number) or timeseries chart (PNG) in Slack.  
- Harvard IQSS–branded chart colors (Crimson, Harvard Blue, Dark Gray).  
- Prometheus exporter on port **8000** for handler latency, error counts, and in-progress gauges.  
- Written in modern async Bolt for Python with Socket Mode (no public HTTP server required).  

---

## Prerequisites

Before you begin, ensure you have:

- **macOS** or Linux/Windows subsystem.  
- **Docker** (see [Using OrbStack on macOS](#using-orbstack-on-macos)).  
- **asdf** version manager (for Python).  
- **uv** CLI (to install and run Python dependencies).  

---

## Development Setup

### Install Python via asdf on macOS

We pin our Python version in `.tool-versions`. On macOS, the easiest way to install `asdf` and Python is:

1. **Install Homebrew** (if not already installed):

   ```bash
   /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
   ```

2. **Install `asdf`**:

   ```bash
   brew install asdf
   ```

3. **Add `asdf` to your shell** (e.g. `~/.zshrc` or `~/.bashrc`):

   ```bash
   . /opt/homebrew/opt/asdf/libexec/asdf.sh
   ```

4. **Install the Python plugin**:

   ```bash
   asdf plugin-add python https://github.com/danhper/asdf-python.git
   ```

5. **Install the version from `.tool-versions`**:

   ```bash
   cd /path/to/this/project
   asdf install
   ```

   This ensures `python --version` matches what’s declared in `.tool-versions`.

### Install Dependencies with `uv`

We use [uv](https://github.com/jdxcode/uv) to manage our virtual environment and dependencies:

1. **Ensure `uv` is installed**:

   ```bash
   pip install uv
   ```

2. **Sync dependencies** (reads `pyproject.toml` and `uv.lock`, if present):

   ```bash
   uv sync
   ```

3. **Activate the venv** (optional; `uv run` will auto-activate):

   ```bash
   source .venv/bin/activate
   ```

4. **Install new dependencies**:  
   - Edit `pyproject.toml` → add to `[project.dependencies]`  
   - Run `uv sync` again.

---

## Running Locally

1. **Activate** (if not auto-activated):

   ```bash
   source .venv/bin/activate
   ```

2. **Set required env vars** (see [Environment Variables](#environment-variables)).  

   ```bash
   export SLACK_BOT_TOKEN="xoxb-…"
   export SLACK_SIGNING_SECRET="…"
   export SLACK_APP_TOKEN="xapp-…"
   export XDMOD_URL="https://xdmod.rc.fas.harvard.edu"
   export XDMOD_API_TOKEN="your-xdmod-api-token"
   ```

3. **Run the bot**:

   ```bash
   uv run python bot.py
   ```

4. **Visit telemetry** (optional):  
   Open `http://localhost:8000/metrics` in your browser to see Prometheus stats.

---

## Docker Setup

### Using OrbStack on macOS

If you run Docker on macOS, consider using [OrbStack](https://orbstack.dev) instead of Docker Desktop:

1. **Download OrbStack** from <https://orbstack.dev> and install.  
2. **Start OrbStack** (launch the app).  
3. **Verify**:

   ```bash
   docker version
   ```

   You should see OrbStack’s Docker daemon active.

### Building the Docker Image

We supply a `Dockerfile` that uses the slim Python image and `uv`:

1. **Determine Python version** from `.tool-versions`:

   ```bash
   PYVER=$(awk '/^python/ {print $2}' .tool-versions)
   ```

2. **Build**:

   ```bash
   docker build --build-arg PYTHON_VERSION=$PYVER -t idk:latest .
   ```

### Running the Container

Create a file named `.env` (or whatever) with your env vars:

```env
SLACK_BOT_TOKEN=xoxb-…
SLACK_SIGNING_SECRET=…
SLACK_APP_TOKEN=xapp-…
XDMOD_URL=https://xdmod.rc.fas.harvard.edu
XDMOD_API_TOKEN=your-xdmod-api-token
```

Then:

```bash
docker run --env-file .env -p 8000:8000 idk:latest
```

- `--env-file .env` loads Slack tokens and XDMoD URL/API token  
- `-p 8000:8000` exposes Prometheus telemetry  

---

## Environment Variables

| Variable                | Description                                                             |
|-------------------------|-------------------------------------------------------------------------|
| `SLACK_BOT_TOKEN`       | Bot User OAuth Token (starts with `xoxb-…`)                             |
| `SLACK_SIGNING_SECRET`  | Signing secret from your Slack App’s Basic Information → App Credentials |
| `SLACK_APP_TOKEN`       | App-level token (starts with `xapp-…`), required for Socket Mode         |
| `XDMOD_URL`             | Base URL for XDMoD (e.g. `https://xdmod.rc.fas.harvard.edu`)             |
| `XDMOD_API_TOKEN`       | API token or key to authenticate when querying XDMoD                     |

You can store these in a file (e.g. `.env`) and load with `--env-file` when running Docker, or export them directly for local development.

---

## How to Add This App to Your Slack Workspace

Follow these steps to configure and install the bot in your Slack workspace:

### Create a Slack App & Enable Socket Mode

1. Go to <https://api.slack.com/apps> and click **Create New App**.  
2. Choose **From scratch**, give it a name (e.g. “XDMoD Metrics Bot”), and pick your development workspace.  
3. In the left sidebar under **Settings**, click **Socket Mode** and toggle **Enable Socket Mode** to “On.”  
4. Under **App-Level Tokens**, click **Generate Token and Scopes**, give it scope `connections:write`, and copy the generated `xapp-…` token. Set it as `SLACK_APP_TOKEN`.

### Configure Scopes, Slash Command, and Interactivity

1. In the left sidebar, under **Features**, click **OAuth & Permissions**.  
2. Under **Scopes → Bot Token Scopes**, add:
   - `commands`
   - `chat:write`
   - `files:write`
   - `im:write`  
3. Click **Install to Workspace** (or **Reinstall**) and authorize.  
4. Copy the **Bot User OAuth Token** (`xoxb-…`) and set it as `SLACK_BOT_TOKEN`.  
5. Copy the **Signing Secret** from **Basic Information → App Credentials** and set it as `SLACK_SIGNING_SECRET`.

### Create the `/metrics` Slash Command

1. In the left sidebar, under **Features**, click **Slash Commands** → **Create New Command**.  
2. Command: `/metrics`  
   - Request URL: leave blank (we use Socket Mode; no HTTP endpoint)  
   - Short description: `Generate CPU/GPU/Queue usage reports`  
   - Usage hint: `[start] [end] [metric]` (not required; modal pops up)  
3. Save.

### Enable Interactivity & Shortcuts

1. Under **Features**, click **Interactivity & Shortcuts**.  
2. Toggle **Interactivity** to “On.”  
3. For **Request URL**, leave it blank in Socket Mode.  

---

## Prometheus Telemetry

The bot exposes an HTTP endpoint on port **8000** (by default) for Prometheus metrics. Available metrics include:

- `slack_command_duration_seconds{command="/metrics"}` – Histogram of `/metrics` handler time.  
- `slack_action_duration_seconds{action="metric_select"}` – Histogram of block-action handlers (e.g. metric changes).  
- `slack_view_duration_seconds{view="metrics_modal"}` – Histogram of modal-submission times.  
- `slack_handler_errors_total{handler="<handler_name>"}` – Counter of exceptions in each handler.  
- `slack_handlers_in_progress` – Gauge of currently running handler coroutines.  
- `slack_commands_total{command="/metrics"}`, `slack_actions_total{action="filter_type"}`, etc. – Total invocations.

Point Prometheus at `http://<bot-host>:8000/metrics` to scrape these.

---

## Troubleshooting

- **Missing environment variables** → ensure `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_APP_TOKEN`, `XDMOD_URL`, and `XDMOD_API_TOKEN` are set.  
- **`xdmod_data` build errors** → confirm `build-essential`, `libffi-dev`, `libssl-dev`, `libpng-dev`, and `cairo` libs are installed (Dockerfile covers these).  
- **Modal doesn’t update on selection** → ensure your action blocks include `dispatch_action: true` and that your handler calls `views_update` with `view_id` & `hash`.  
- **Dates older than 6 months rejected** → I set this limitation arbitrarily to prevent accidental long queries to XDMOD.

---

## License

This project is licensed under the **GPL-3.0 License**. See [COPYING](./COPYING) for details.  
