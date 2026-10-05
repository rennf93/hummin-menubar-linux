"""App state: the macOS AppDelegate, ported.

Same rules as the Mac app: the menu renders instantly from a health cache,
checks run concurrently in the background with a TTL, actions flip a pending
state that disables the right buttons, mutex groups stop their siblings first,
and restart is spelled `down; sleep 2; up`.
"""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from .process import append_to_log, run, run_captured, run_logged

CHECK_TTL = 5.0      # seconds; same as the macOS app
CHECK_TIMEOUT = 5.0  # hard cap per health probe cycle

_DOT_BUSY, _DOT_UP, _DOT_DOWN = "\u25d0", "\u25cf", "\u25cb"  # ◐ ● ○


class App:
    def __init__(self, servers, host_order, config_error):
        order = host_order
        rank = {host: i for i, host in enumerate(order)}
        self.servers = sorted(
            servers, key=lambda s: (rank.get(s.host, len(order)), s.label.lower()))
        self.host_order = list(order)
        self.config_error = config_error

        self.lock = threading.Lock()
        self.pending = {}       # server id -> "start" | "stop" | "restart"
        self.cached_up = {}     # server id -> bool
        self.cached_modes = {}  # server id -> str
        self.last_check = 0.0
        self.checking = False
        self.menu = None

    def attach(self, tray):
        """Build the static menu tree; ids are stable for the app's lifetime."""
        self.menu = tray.menu
        add = self.menu.add
        self.id_status = add(0, "status")
        if self.config_error:
            self.id_error = add(0, "error", static={
                "label": ("s", "Config error (see log)"),
                "enabled": ("b", False)})
        self.host_ids, self.row_ids, self.action_ids, self.mode_ids = {}, {}, {}, {}
        # COSMIC's status-area popup can expand only ONE submenu level, so the
        # Linux menu is flat: disabled host header rows, then every server row
        # directly under the root with its actions as the row's own submenu.
        # (The macOS app keeps its nested host -> server -> actions tree.)
        for host in self.host_order:
            host_id = add(0, "hostheader", static={
                "enabled": ("b", False)})
            self.host_ids[host] = host_id
            for s in (x for x in self.servers if x.host == host):
                row_id = add(0, "row", static={
                    "children-display": ("s", "submenu")}, server=s)
                self.row_ids[s.id] = row_id
                for action, title in (("start", "Start"), ("stop", "Stop"),
                                      ("restart", "Restart")):
                    self.action_ids[(s.id, action)] = add(
                        row_id, "action", static={"label": ("s", title)},
                        server=s, action=action)
                if s.modes:
                    parent = add(row_id, "modeparent", static={
                        "label": ("s", "Mode"),
                        "children-display": ("s", "submenu")}, server=s)
                    for mode in s.modes:
                        self.mode_ids[(s.id, mode)] = add(
                            parent, "mode",
                            static={"label": ("s", mode),
                                    "toggle-state": ("i", 0)},
                            server=s, mode=mode)
        add(0, "sep", static={"type": ("s", "separator")})
        self.id_quit = add(0, "quit", static={"label": ("s", "Quit menubar")})

    def start(self):
        self.render()
        self.schedule_check(force=True)

    # ---- rendering (instant, cache-driven) -------------------------------------

    def render(self):
        with self.lock:
            pending = dict(self.pending)
            cached_up = dict(self.cached_up)
            cached_modes = dict(self.cached_modes)

        targets = {}
        up_count = 0
        host_up = {}

        for s in self.servers:
            up = cached_up.get(s.id, False)
            if up:
                up_count += 1
                host_up[s.host] = host_up.get(s.host, 0) + 1
            state = pending.get(s.id)
            mark = _DOT_BUSY if state else (_DOT_UP if up else _DOT_DOWN)
            suffix = f"  {state}ing..." if state else ""
            mode = cached_modes.get(s.id)
            mode_text = f" \u00b7{mode}" if mode else ""
            port = f" :{s.port}" if s.port else ""
            targets[self.row_ids[s.id]] = {
                "label": ("s", f"{s.label}{port}{mode_text}  {mark}{suffix}")}

            # While starting or restarting, Start/Restart are disabled and Stop
            # stays live (an abort lever); while stopping everything is disabled.
            if state in ("start", "restart"):
                start_en, stop_en, restart_en = False, True, False
            elif state == "stop":
                start_en, stop_en, restart_en = False, False, False
            else:
                start_en, stop_en, restart_en = not up, up, up
            for action, en in (("start", start_en), ("stop", stop_en),
                               ("restart", restart_en)):
                targets[self.action_ids[(s.id, action)]] = {
                    "enabled": ("b", en)}

            for mode in (s.modes or ()):
                key = (s.id, mode)
                if key in self.mode_ids:
                    targets[self.mode_ids[key]] = {
                        "toggle-state": ("i", 1 if cached_modes.get(s.id) == mode else 0)}

        for host, host_id in self.host_ids.items():
            n = host_up.get(host, 0)
            label = f"{host}  ({n} running)" if n > 0 else host
            targets[host_id] = {"label": ("s", label)}

        if cached_up:
            status = ("All servers stopped" if up_count == 0
                      else f"{up_count} server(s) running")
        elif self.config_error:
            status = "Config error (see log)"
        else:
            status = "Status: checking..."
        targets[self.id_status] = {"label": ("s", status)}

        self.menu.update(targets)

    # ---- checking (background, TTL-guarded) --------------------------------------

    def menu_opened(self):
        self.render()
        self.schedule_check(force=False)

    def schedule_check(self, force):
        with self.lock:
            if self.checking:
                return
            if not force and time.time() - self.last_check < CHECK_TTL:
                return
            self.checking = True
        threading.Thread(target=self._check, daemon=True).start()

    def _check(self):
        results, mode_results = {}, {}
        if self.servers:
            deadline = time.time() + CHECK_TIMEOUT
            with ThreadPoolExecutor(max_workers=min(16, 2 * len(self.servers))) as ex:
                futures = []
                for s in self.servers:
                    futures.append((ex.submit(run_logged, s.health, CHECK_TIMEOUT - 0.5),
                                    "up", s.id))
                    if s.mode_get:
                        futures.append((ex.submit(run_captured, s.mode_get, CHECK_TIMEOUT - 0.5),
                                        "mode", s.id))
                for future, kind, server_id in futures:
                    remaining = max(0.05, deadline - time.time())
                    try:
                        value = future.result(timeout=remaining)
                    except TimeoutError:
                        value = -1 if kind == "up" else (-1, "")
                    if kind == "up":
                        results[server_id] = (value == 0)
                    elif value[0] == 0:
                        mode_results[server_id] = value[1].strip()
        with self.lock:
            self.cached_up = results
            self.cached_modes = mode_results
            self.last_check = time.time()
            self.checking = False
        self.render()

    # ---- actions -------------------------------------------------------------------

    def clicked(self, item_id):
        info = self.menu.items.get(item_id)
        if info is None:
            return
        kind = info["kind"]
        if kind == "action":
            self.act(info["server"], info["action"])
        elif kind == "mode":
            self.set_mode(info["server"], info["mode"])
        elif kind == "quit":
            self.quit()

    def act(self, server, action):
        with self.lock:
            if self.pending.get(server.id):
                return
            self.pending[server.id] = action
        self.render()

        def work():
            try:
                if action in ("start", "restart") and server.mutex_group:
                    # Resource-sharers are exclusive: stop the others first.
                    for other in self.servers:
                        if other.id != server.id and other.mutex_group == server.mutex_group:
                            run(other.down)
                    time.sleep(2)
                if action == "stop":
                    command = server.down
                elif action == "start":
                    command = server.up
                else:
                    command = f"{server.down}; sleep 2; {server.up}"
                exit_code = run_logged(command)
                self.log_action(
                    f"{server.id} {action} exit={exit_code} cmd={command}")
            finally:
                with self.lock:
                    self.pending.pop(server.id, None)
                self.schedule_check(force=True)

        threading.Thread(target=work, daemon=True).start()

    def set_mode(self, server, mode):
        if not server.mode_set:
            return
        command = server.mode_set.replace("{mode}", mode)
        self.log_action(f"{server.id} mode={mode} cmd={command}")

        def work():
            run_logged(command)
            self.schedule_check(force=True)

        threading.Thread(target=work, daemon=True).start()

    def quit(self):
        os._exit(0)

    # ---- logging -------------------------------------------------------------------

    def log_main(self, line):
        append_to_log(_log_path("hummin-menubar.log"),
                      f"[{int(time.time())}] {line}\n")

    def log_action(self, line):
        stamp = time.strftime("%H:%M:%S")
        append_to_log(_log_path("hummin-menubar-actions.log"),
                      f"[{stamp}] {line}\n")


def _log_path(name):
    from .config import logs_directory
    return logs_directory() + "/" + name
