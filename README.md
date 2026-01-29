## fortigate-netbox

Python application to validate and (in future versions) synchronize switch port configuration between FortiGate-managed switches and NetBox.

### Modules overview

- **`app/config.py`**: Loads configuration from environment variables and a FortiGate devices JSON file. Resolves API tokens from files or env vars and prepares a `Settings` object (FortiGate inventory, NetBox URL/token, data directory, log level).
- **`app/logging_config.py`**: Central logging setup. Configures a simple console logger with timestamp, level, and logger name, honoring the `LOG_LEVEL` setting.
- **`app/models.py`**: Defines normalized data models:
  - `Switch`: a managed switch.
  - `SwitchPort`: a single port with `name`, `native_vlan`, and `allowed_vlans` (VLANs by name).
- **`app/fortigate_client.py`**: FortiGate HTTPS client that:
  - Calls `/api/v2/cmdb/switch-controller/managed-switch/`.
  - Parses the real FortiGate JSON (e.g. `switch-id`, `ports[].port-name`, `untagged-vlans`, `allowed-vlans`, `allowed-vlans-all`).
  - Normalizes switches into `Switch`/`SwitchPort` models.
- **`app/netbox_client.py`**: Read-only NetBox client that:
  - Looks up devices by name.
  - Retrieves all interfaces for a device, including VLAN fields (`untagged_vlan`, `tagged_vlans`).
- **`app/storage.py`**: Handles on-disk JSON snapshots:
  - Clears the `data/` directory at the start of each run.
  - Writes per-FortiGate switch snapshots (`<fortigate_name>_switches.json`).
  - Reloads all stored switches for later comparison or reuse.
- **`app/vlan_validator.py`**: Compares FortiGate and NetBox VLAN configuration:
  - Extracts VLAN info from NetBox interfaces (native and allowed VLANs by name).
  - Logs mismatches, missing ports, and ambiguous configurations (e.g. `allowed-vlans-all`).
- **`app/sync_switches.py`**: Orchestrates a full sync run:
  - Clears stored data.
  - Fetches switches from each configured FortiGate and stores normalized JSON.
  - Reloads all stored switches, checks their existence in NetBox, and runs VLAN validation.
  - If a switch is missing in NetBox, stops execution and prints a concise error.
- **`app/main.py`**: Entry point for `python -m app.main`:
  - Loads settings.
  - Configures logging.
  - Executes `run_sync` and exits with its return code.

### Configuration

#### Environment Variables

The application is configured via environment variables, typically loaded from an `env.production` file using Docker's `--env-file` flag.

**Required Variables:**

- `FG_DEVICES_FILE`: Path to the FortiGate devices JSON file (default: `fortigate_devices.json`)
- `NETBOX_URL`: Base URL of your NetBox instance (e.g., `https://netbox.example.com`)
- `NETBOX_API_TOKEN`: NetBox API token (direct value). If not set, falls back to `NETBOX_API_TOKEN_FILE`

**Optional Variables:**

- `NETBOX_API_TOKEN_FILE`: Path to file containing NetBox API token (default: `secrets/netbox_api_token`). Used only if `NETBOX_API_TOKEN` is not set.
- `NETBOX_TIMEOUT`: API request timeout in seconds (default: `120`)
- `SYNC_DATA_DIR`: Directory for storing switch data snapshots (default: `/app/data`)
- `CACHE_DIR`: Directory for caching data (default: `/app/data/cache`)
- `USE_CACHED_DATA`: Whether to use cached data instead of fetching live (default: `false`). Accepts: `true`, `false`, `yes`, `no`, `1`, `0`, `on`, `off`
- `LOG_LEVEL`: Logging level (default: `INFO`). Options: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`
- `TEST_SWITCH`: If set, validates only this specific switch instead of all switches

#### Creating Your Environment File

**IMPORTANT:** Docker's `--env-file` has strict format requirements:
- **NO comments** (lines starting with `#`) are allowed in the file
- Each line must be in the format: `KEY=VALUE`
- No spaces around the `=` sign
- Use Unix line endings (LF), not Windows (CRLF)
- Empty values are allowed (e.g., `TEST_SWITCH=`)

Copy the provided `.env.example` to create your `env.production` file:

```bash
cp .env.example env.production
```

Then edit `env.production` with your actual values:

```bash
FG_DEVICES_FILE=/app/fortigate_devices.json
NETBOX_URL=https://netbox.example.com
NETBOX_API_TOKEN=your_actual_netbox_token_here
SYNC_DATA_DIR=/app/data
CACHE_DIR=/app/data/cache
USE_CACHED_DATA=false
NETBOX_TIMEOUT=120
LOG_LEVEL=INFO
TEST_SWITCH=AEX-ARN-UT2-SW01
```

**Note:** You can either:
- Set `NETBOX_API_TOKEN` directly in the env file (as shown above)
- Leave `NETBOX_API_TOKEN` empty and the app will use `NETBOX_API_TOKEN_FILE` to read from a file

The direct `NETBOX_API_TOKEN` variable takes priority if both are provided.

#### Troubleshooting Environment Variables

If you see `DEBUG: VARIABLE_NAME=<not set>` in the output:

1. **Check for comments**: Remove all lines starting with `#` from your env file
2. **Check file format**: Ensure no spaces around `=` signs
3. **Check line endings**: Convert to Unix format with `dos2unix env.production` if needed
4. **Check file location**: The env file must be in your current directory or use absolute path
5. **Test the file manually**: Run `docker run --rm --env-file env.production alpine env` to see if Docker loads it

### Data storage

- **Full sync run** (no `TEST_SWITCH`):
  - At the **start of each run**, the data directory is **cleared**.
  - The app then fetches switch config from each FortiGate via the HTTPS API, saves normalized JSON to disk, loads it back, and compares with NetBox.
  - Nothing is reused between runs; each run does a fresh fetch and overwrites stored data.
- **Test-switch run** (`TEST_SWITCH` set, e.g. dry run):
  - **No storage is used.** The app fetches **live** from the FortiGate API for that run only, compares with NetBox, and prints results. Nothing is read from or written to disk.
- **Where data is stored:**
  - Directory: `SYNC_DATA_DIR` (default: `/app/data`). In Docker you typically mount a host path, e.g. `-v /var/lib/fortigate-netbox/data:/app/data`.
  - Files: `<fortigate_name>_switches.json` (e.g. `fg1_switches.json`) inside that directory. These are created only during full sync runs.

### Example FortiGate devices config

Create a JSON file in this project folder (for example `fortigate_devices.json`, which is already in `.gitignore`) describing each FortiGate and its own token file:

```json
[
  {
    "name": "fg1",
    "host": "fw1.fortiddns.com",
    "token_file": "secrets/fg1_api_token",
    "verify_ssl": false
  },
  {
    "name": "fg2",
    "host": "10.0.0.2",
    "token_file": "secrets/fg2_api_token",
    "verify_ssl": true
  }
]
```

### Example secret/token files

These files contain **only** the token value (no quotes, no JSON), and should live in the project folder but are excluded from Git by `.gitignore`:

- `secrets/fg1_api_token`:

```text
FG1_API_TOKEN_VALUE_HERE
```

- `secrets/fg2_api_token`:

```text
FG2_API_TOKEN_VALUE_HERE
```

- `secrets/netbox_api_token` (only needed if using `NETBOX_API_TOKEN_FILE`):

```text
NETBOX_API_TOKEN_VALUE_HERE
```

All paths are mounted into the container as read-only and referenced via environment variables or via `fortigate_devices.json`.

### Running via Docker

#### Build the Image

Build the image from the repository root:

```bash
docker build -t fortigate-netbox:latest .
```

#### Run with env.production File

The recommended approach is to use an `env.production` file with Docker's `--env-file` flag:

```bash
docker run --rm \
  --env-file env.production \
  -v "$(pwd)/fortigate_devices.json:/app/fortigate_devices.json:ro" \
  -v "$(pwd)/secrets:/app/secrets:ro" \
  -v "$(pwd)/cache:/app/data/cache" \
  fortigate-netbox:latest
```

#### Run with Individual Environment Variables

Alternatively, you can pass environment variables directly (useful for testing):

```bash
docker run --rm \
  -v "$(pwd)/fortigate_devices.json:/app/fortigate_devices.json:ro" \
  -v "$(pwd)/secrets:/app/secrets:ro" \
  -v /var/lib/fortigate-netbox/data:/app/data \
  -e FG_DEVICES_FILE=/app/fortigate_devices.json \
  -e NETBOX_URL=https://netbox.example.com \
  -e NETBOX_API_TOKEN=your_token_here \
  -e SYNC_DATA_DIR=/app/data \
  -e CACHE_DIR=/app/data/cache \
  -e LOG_LEVEL=INFO \
  fortigate-netbox:latest
```

#### Scheduled Execution via Cron

Typical cron entry to run daily at 02:00 using the `env.production` file:

```cron
0 2 * * * cd /home/user/fortigate-netbox && docker run --rm \
  --env-file env.production \
  -v "$(pwd)/fortigate_devices.json:/app/fortigate_devices.json:ro" \
  -v "$(pwd)/secrets:/app/secrets:ro" \
  -v "$(pwd)/cache:/app/data/cache" \
  fortigate-netbox:latest >> /var/log/fortigate-netbox.log 2>&1
```

Or with explicit environment variables:

```cron
0 2 * * * docker run --rm \
  -v /home/user/fortigate-netbox/fortigate_devices.json:/app/fortigate_devices.json:ro \
  -v /home/user/fortigate-netbox/secrets:/app/secrets:ro \
  -v /var/lib/fortigate-netbox/data:/app/data \
  -e FG_DEVICES_FILE=/app/fortigate_devices.json \
  -e NETBOX_URL=https://netbox.example.com \
  -e NETBOX_API_TOKEN=your_token_here \
  -e SYNC_DATA_DIR=/app/data \
  -e LOG_LEVEL=INFO \
  fortigate-netbox:latest >> /var/log/fortigate-netbox.log 2>&1
```
