# hummin-menubar-linux

The Linux sibling of [hummin-menubar-macos](https://github.com/rennf93/hummin-menubar-macos):
a status-tray app for controlling a personal fleet of LLM servers across
machines - local systemd services, Linux laptops over ssh, NAS docker compose
stacks. One tray icon, nested host submenus, every model start/stop/restart
from one place. **Same `servers.json`, same ports, same menu, same behavior as
the Mac app** - copy your config over and it works.

![bird](docs/bird-preview.png)

Part of the [hummin](https://github.com/rennf93/hummin) family. MIT licensed,
zero third-party dependencies: it speaks the StatusNotifierItem/dbusmenu tray
protocol directly over the session bus with the Python standard library alone
(there is nothing to compile).

## Features (same as the macOS app)

- One tray icon, live state dots (running / stopped / in flight) per server,
  per-host running counts, and Start / Stop / Restart (+ mode switching) for
  every server. The Linux menu is one level flatter than the Mac's - host
  headers, then every server row with its actions in its own submenu - because
  COSMIC's status-area popup expands only one submenu level; on KDE/GNOME/XFCE
  it behaves like the Mac's nested tree
- Config-driven: servers live in a personal `servers.json`, not in code. Adding
  a model or a machine never means recompiling
- Mutex groups for servers that share a resource: starting one stops the
  others (e.g. several models, one small GPU)
- Optional mode switcher per server for anything driven by a mode file
  (included: a replay-trim proxy mode with instant `all / strip / off`
  switching)
- Non-blocking health checks: the menu renders instantly from a cache and
  refreshes in the background; checks run concurrently with a timeout, so an
  asleep laptop never stalls the menu
- Actions and health probes are logged to `~/.local/state/hummin-menubar/*.log`
  (the XDG counterpart of the Mac's `~/Library/Logs`)

## Tray support

Works with any desktop implementing StatusNotifierItem + dbusmenu: COSMIC
(Pop!_OS 24.04+), KDE Plasma, XFCE, MATE, Cinnamon, Budgie, sway/waybar,
Hyprland, and GNOME with the AppIndicator extension (Ubuntu and Pop!_OS ship
it enabled).

## Run

```bash
./bin/hummin-menubar          # from a checkout
```

## Install

```bash
make install             # ~/.local/bin + systemd user unit
make install-config      # seeds ~/.config/hummin-menubar/servers.json (never overwrites)
systemctl --user enable --now hummin-menubar
```

Then copy your `servers.json` from the Mac into
`~/.config/hummin-menubar/servers.json` (or edit the seeded example). Quitting
from the menu exits with status 0, so `Restart=on-failure` keeps it stopped;
the service starts again at the next login.

## Configure

Config search order: `$HUMMIN_MENUBAR_CONFIG`, then
`~/.config/hummin-menubar/servers.json`, then `./servers.json`.

The file is byte-compatible with the macOS app (same schema, same field
names, same example with the same ports). Command strings run through the
login shell - `/bin/bash -lc` here, `/bin/zsh -lc` on the Mac - so ssh-based
rows work unchanged on both; `launchctl` rows obviously want `systemctl`
equivalents for local services.

| Field | Meaning |
|---|---|
| `hostOrder` | root menu order of the host groups |
| `servers[].id` | stable identifier (used in logs) |
| `servers[].label` | menu title |
| `servers[].host` | group name, must appear in `hostOrder` to be shown |
| `servers[].port` | optional, shown after the label; omit for non-network rows |
| `servers[].up` / `down` / `health` | shell commands; `health` exits 0 = running |
| `servers[].mutexGroup` | optional exclusivity group (start one, stop the rest) |
| `servers[].modes` / `modeGet` / `modeSet` | optional mode switcher; `{mode}` in `modeSet` is replaced |

## Icon

The macOS app ships a template image the system recolors; Linux panels don't
do that, so the app recolors the same bird itself: a light silhouette on dark
themes, a dark one on light themes (read once at startup from the XDG
settings portal, where available). Override with `HUMMIN_MENUBAR_ICON=dark`
or `=light`. `icon/art-64.png` is the macOS repo's extracted art downscaled -
regenerate it with `scripts/downscale-art.py <menubar-template.png>`;
`scripts/preview-icon.py` renders the previews in `docs/`.

## Logs

Same line formats as the macOS app, in `$XDG_STATE_HOME`
(`~/.local/state/hummin-menubar/`):

- `hummin-menubar.log` - lifecycle: config loads, config errors, bus drops
- `hummin-menubar-actions.log` - one line per action/mode switch
- `hummin-menubar-health.log` - every health probe and command output

## Security notes

- `servers.json` contains shell commands that this app executes through your
  login shell. That is the entire point (it wraps ssh, systemctl, docker),
  and it means the file is trusted input: never install a config you have
  not read, and keep personal hostnames out of anything you publish.
- The app performs no network calls of its own. Every network action it can
  trigger is a command you wrote in your config.
- Health checks and actions run concurrently in their own process groups and
  are bounded by timeouts, so an unreachable machine degrades to a gray dot,
  never to a hang.

## License

MIT. The bird is the macOS repo's template art, downscaled to a tray-sized
PNG - and the fallback in `icon.py` is drawn pixel by pixel in code, so the
app runs even without the asset.
