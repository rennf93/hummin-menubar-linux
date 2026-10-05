"""Entry point: wire config -> app -> tray, register with the panel, idle."""
import os
import signal
import sys
import threading
import time

from . import config, icon
from .app import App
from .dbus import Connection
from .tray import Tray, WATCHER

# org.freedesktop.appearance color-scheme: 1 = prefer-dark, 2 = prefer-light.
# COSMIC panels default dark, so "no preference" gets the light bird.
_SCHEME_DARK, _SCHEME_LIGHT = 1, 2


def _read_color_scheme(conn):
    try:
        value, = conn.call_blocking(
            "org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
            "org.freedesktop.portal.Settings", "ReadOne", "ss",
            ["org.freedesktop.appearance", "color-scheme"],
            reply_signature="v", timeout=3)
    except Exception:
        return None
    if isinstance(value, tuple) and value[0] == "v":  # unwrap a v-of-v portal
        value = value[1]
    if isinstance(value, tuple) and len(value) == 2 and value[0] == "u":
        return value[1]
    return None


def _pick_icon_variant(conn):
    override = os.environ.get("HUMMIN_MENUBAR_ICON")
    if override in ("dark", "light"):
        return override
    scheme = _read_color_scheme(conn)
    if scheme == _SCHEME_LIGHT:
        return "dark"
    return "light"


def main():
    conn = Connection()
    conn.on_disconnect = _on_disconnect
    conn.start()

    cfg_error = None
    servers, host_order, path = [], [], None
    try:
        cfg, path = config.load()
        servers, host_order = cfg.servers, cfg.host_order
    except config.ConfigError as exc:
        cfg_error = str(exc)

    app = App(servers, host_order, cfg_error)
    tray = Tray(conn)
    tray.set_app(app)
    app.attach(tray)
    tray.export()

    width, height, argb = icon.render(_pick_icon_variant(conn))
    tray.set_icon(width, height, argb)

    def watcher_owner_changed(name, old, new):
        if name == WATCHER and new:
            threading.Timer(0.5, tray.register).start()

    conn.add_signal("org.freedesktop.DBus", "NameOwnerChanged",
                    WATCHER, watcher_owner_changed)

    if cfg_error:
        app.log_main(cfg_error)
    else:
        app.log_main(f"loaded {len(servers)} servers from {path}")

    if not tray.register():
        print("hummin-menubar: no tray host yet; will retry when one appears "
              "(check the log for details)", file=sys.stderr)

    app.start()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: os._exit(0))

    while True:
        time.sleep(3600)


def _on_disconnect(reason):
    # Exit nonzero so `systemd --user` (Restart=on-failure) brings us back
    # after a bus restart; a manual Quit exits 0 and stays down.
    from .process import append_to_log
    from .config import logs_directory
    append_to_log(logs_directory() + "/hummin-menubar.log",
                  f"[{int(time.time())}] {reason}\n")
    os._exit(1)


if __name__ == "__main__":
    main()
