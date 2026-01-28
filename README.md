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

- `secrets/netbox_api_token`:

```text
NETBOX_API_TOKEN_VALUE_HERE
```

All paths are mounted into the container as read-only and referenced via environment variables or via `fortigate_devices.json`.

### Running via Docker with secrets and config

Build the image from the repository root:

```bash
docker build -t fortigate-netbox:latest .
```

Run a one-off validation (for example from cron) mounting the config, secrets, and data directory.
In this example, we assume you run the command from the project root so `$(pwd)` points to the project folder:

```bash
docker run --rm \
  -v "$(pwd)/fortigate_devices.json:/app/fortigate_devices.json:ro" \
  -v "$(pwd)/secrets:/app/secrets:ro" \
  -v /var/lib/fortigate-netbox/data:/app/data \
  -e FG_DEVICES_FILE=/app/fortigate_devices.json \
  -e NETBOX_URL=https://netbox.example.com \
  -e NETBOX_API_TOKEN_FILE=/app/secrets/netbox_api_token \
  -e SYNC_DATA_DIR=/app/data \
  -e LOG_LEVEL=INFO \
  fortigate-netbox:latest
```

Typical cron entry to run daily at 02:00 (note that `$PWD` should be replaced with the absolute path to the project folder):

```cron
0 2 * * * docker run --rm \
  -v /home/tre/git/fortigate-netbox/fortigate_devices.json:/app/fortigate_devices.json:ro \
  -v /home/tre/git/fortigate-netbox/secrets:/app/secrets:ro \
  -v /var/lib/fortigate-netbox/data:/app/data \
  -e FG_DEVICES_FILE=/app/fortigate_devices.json \
  -e NETBOX_URL=https://netbox.example.com \
  -e NETBOX_API_TOKEN_FILE=/app/secrets/netbox_api_token \
  -e SYNC_DATA_DIR=/app/data \
  -e LOG_LEVEL=INFO \
  fortigate-netbox:latest
```
