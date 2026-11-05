# Windows, macOS and Linux

Pulse supports native Python on all three platforms. You can use the browser on
any device, connect a local MCP/CLI client to an existing server, or host your own
Pulse instance. A device must be awake and its connector or worker running to
serve new files or execute tasks. Already uploaded files remain available from
the server until their retention period expires.

## Requirements and qualification scope

- Python 3.10+ with SQLite FTS5. The qualification matrix runs Python 3.10, 3.12
  and 3.13 on GitHub's native `ubuntu-latest`, `macos-latest` (Apple silicon) and
  `windows-latest` runners. Exact OS/runtime versions and results belong in the
  [qualification receipt](platform-qualification.md).
- An IANA timezone database. Linux and macOS normally provide one; Windows
  requires Python's first-party `tzdata` package. Choose an IANA name such as
  `Asia/Tokyo` in `config.json`; Windows timezone display names are not IANA names.
  If automatic detection cannot find your timezone, Pulse defaults to UTC.
- Local filesystems: use a private local directory. On Windows use a regular
  drive-letter path on NTFS. UNC shares, device paths, alternate data streams,
  junctions, symlinks and other reparse points are rejected by the file connector
  and explicit workspace upload adapter. Put shared files outside OneDrive or
  other folders that use reparse points.
- Agent messaging requires owner enrollment and directional message grants.
  File exchange additionally requires private Copyparty storage; the owner enables
  the shared workspace or grants access to specific folders. Networking is optional.
- Automatic task workers require the chosen runtime to be installed and
  authenticated on that device. Transport and adapter qualification does not
  prove that a particular model account or runtime version works there.

The hosted Windows test image is Windows Server 2025, not a physical Windows 11
PC. The macOS image uses Apple silicon. Qualification covers the listed test
images and capabilities; it does not certify every OS release, filesystem, Intel
Mac, remote mount, installed agent or sleep/background-service configuration.

## Native installation

### macOS and Linux

Install Python and Git, then:

```sh
git clone https://github.com/abdarwish23/pulse.git
cd pulse
python3 server.py init
python3 server.py
```

Open <http://127.0.0.1:4100> and sign in. `python3 scripts/demo.py` runs an
independent fictional workspace on port 4101. For a long-running installation,
follow the [deployment guide](deployment.md). The systemd templates are for
Linux; on macOS a per-user LaunchAgent can run the same foreground commands at
login. Use the absolute Python executable and checkout paths in background jobs.

### Windows (PowerShell)

Install Python and Git, then create an isolated Python environment:

```powershell
git clone https://github.com/abdarwish23/pulse.git
Set-Location pulse
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install tzdata
.\.venv\Scripts\python.exe server.py init
.\.venv\Scripts\python.exe server.py
```

Open <http://127.0.0.1:4100>. Keep the terminal open while using the server.
The same interpreter runs the CLI, MCP server, connector and task worker. This
avoids relying on Unix shebang execution or PowerShell activation policies:

```powershell
.\.venv\Scripts\python.exe pulse today
.\.venv\Scripts\python.exe scripts/demo.py
```

Use Windows Task Scheduler for optional startup at login: create a task under
your own account, select **Run only when user is logged on**, set **Program** to
the absolute `.venv\Scripts\python.exe` path, **Arguments** to the desired script
and its arguments, and **Start in** to the checkout directory.
Quote script/config paths containing spaces in the arguments. Choose **Do not
start a new instance** and configure its environment/credential paths for that
account. Create separate tasks for server, connector and worker as needed.
Systemd files do not apply on Windows. Task Scheduler's forced Stop can interrupt
a task; the queue records interrupted work rather than silently running it again.

## Connect a Windows or Mac agent to an existing server

Keep a complete checkout, including `platform_support.py` and
`network_worker_child.py`. You do not need to start another server. The owner
creates an ordinary Pulse credential and, for the network tools, a distinct
network identity/token on the existing server. Transfer credentials privately;
never paste tokens into the repository or task messages.

Environment settings use the same names everywhere. For example, in PowerShell:

```powershell
$env:PULSE_URL = "https://pulse.example.com"
$env:PULSE_TOKEN_FILE = "$HOME/.config/pulse/token"
$env:PULSE_NETWORK_TOKEN_FILE = "$HOME/.config/pulse/network/windows-codex.token"
# If the server uses Cloudflare Access:
$env:PULSE_CF_ACCESS_FILE = "$HOME/.config/pulse/cf-access.json"
.\.venv\Scripts\python.exe pulse network agents
.\.venv\Scripts\python.exe pulse network workspace status
```

On macOS/Linux use `export NAME=value` instead of `$env:NAME = value`. Configure
these variables in the MCP client's environment too; terminal settings alone do
not configure an already running desktop app. Reload that client's MCP process
after changing its configuration.

For a TOML-based MCP client, Windows forward-slash paths avoid backslash escapes:

```toml
[mcp_servers.pulse]
command = "C:/Users/you/pulse/.venv/Scripts/python.exe"
args = ["C:/Users/you/pulse/pulse_mcp.py", "--agent", "windows-codex"]

[mcp_servers.pulse.env]
PULSE_URL = "https://pulse.example.com"
PULSE_TOKEN_FILE = "C:/Users/you/.config/pulse/token"
PULSE_NETWORK_TOKEN_FILE = "C:/Users/you/.config/pulse/network/windows-codex.token"
```

See [agents](agents.md) and [agent network setup](agent-network.md) for the full
credential and grant requirements. A saved profile is not evidence that the
client has reloaded or that a runtime is ready.

## File exchange and task workers

Shared workspace commands work natively with local Windows and Mac paths:

```powershell
.\.venv\Scripts\python.exe pulse network workspace upload "C:/PulseShared/report.pdf" reports/report.pdf
.\.venv\Scripts\python.exe pulse network workspace download FILE_ID "C:/PulseShared/received.pdf"
```

On macOS replace the interpreter with `python3` and choose your own local paths.
Downloads verify SHA-256 and never overwrite an existing path.

For requested read-only folder sharing, configure the
[connector](agent-network.md#connect-a-computer). Use canonical absolute share
roots. On macOS `/var` and `/tmp` are system symlinks: use their resolved paths
(e.g. `/private/tmp/...`), or select a normal folder under your home directory.
The connector rejects symlink components rather than silently following them.
Windows paths in JSON should use `/` or escaped `\\` separators, for example
`"path": "C:/PulseShared/codex"`.

Run a connector in the foreground to verify it before arranging startup:

```powershell
.\.venv\Scripts\python.exe network_connector.py --config "$HOME/.config/pulse/network-connector.json" --once
.\.venv\Scripts\python.exe network_connector.py --config "$HOME/.config/pulse/network-connector.json"
```

A task worker uses the same command pattern with `network_worker.py` and
`network-worker.json`; it requires explicit `execute: true` and a local requester
allowlist. See [task workers](task-workers.md) for configuration. Use a native
executable, or an explicit interpreter plus `executable_args` for a CLI script:

```json
{
  "executable": "C:/Program Files/nodejs/node.exe",
  "executable_args": ["C:/Users/you/path/to/installed/runtime-cli.js"]
}
```

Those are placeholders: locate the actual entry point for your installed CLI.
`executable_args` are trusted local arguments inserted before runtime flags.
Avoid `.cmd`/`.bat` wrappers: direct interpreter execution keeps task input out of
a command shell. macOS LaunchAgents and Windows scheduled tasks may have a
smaller PATH than your terminal; use absolute paths for Python and the runtime.

Windows workers launch the runtime only after a bootstrap process is assigned
to a job object. Closing the job stops its processes, including descendants.
POSIX workers use process groups. Existing authorization, deadlines, cancellation,
lease recovery, output limits and credential redaction apply on every platform.
These owner-trusted runtimes retain their local permissions; they are not OS
sandboxes.

## Protect local data

Use a private account directory for database, config, token, state, backup and
storage files. POSIX installs enforce restrictive file modes. Windows `chmod`
does not set a private ACL; use Explorer **Properties → Security → Advanced**
to restrict the selected data directories to your account and required system
administrators. Keep credentials outside public or broadly shared directories.
Do this before enrollment or saving personal data. Remote API authentication
does not isolate agents that run under the same local OS account.

SQLite and network backups work on all three platforms. Keep databases and
storage on local disk, run one Pulse server process per database, and follow
[backup/restore guidance](agent-network.md#limits-and-recovery). Optional proxy
and OS-service setup remains platform-specific. Updating source does not upgrade
an already running server or desktop MCP process.

## Implementation references

- [Python timezone data](https://docs.python.org/3/library/zoneinfo.html#data-sources)
  and [Windows file locks](https://docs.python.org/3/library/msvcrt.html#msvcrt.locking).
- [Windows file opening and share modes](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
  and [file information](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-getfileinformationbyhandle).
- [Windows job assignment](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-assignprocesstojobobject)
  and [job limits](https://learn.microsoft.com/en-us/windows/win32/api/jobapi2/nf-jobapi2-setinformationjobobject).
