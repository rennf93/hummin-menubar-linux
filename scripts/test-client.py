#!/usr/bin/env python3
"""Live test client: pokes a running hummin-menubar instance the way a tray
host would (GetLayout / AboutToShow / Event) and prints what it sees."""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hummin_menubar.dbus import Connection  # noqa: E402


def layout(conn, dest, path):
    rev, node = conn.call_blocking(
        dest, path, "com.canonical.dbusmenu", "GetLayout",
        "iias", [0, -1, []], reply_signature="u(ia{sv}v)", timeout=5)
    return rev, node


def render(node, depth=0):
    item_id, props, children = node
    label = props.get("label", ("s", ""))[1]
    enabled = props.get("enabled", ("b", True))[1]
    toggle = props.get("toggle-state")
    extra = f" [toggle={toggle[1]}]" if toggle else ""
    dis = "" if enabled else " (disabled)"
    kind = props.get("type", ("s", "standard"))[1]
    if kind == "separator":
        print("  " * depth + "--------")
    else:
        print("  " * depth + f"{item_id:>3} {label!r}{dis}{extra}")
    for sig, child in children[1]:
        render(child, depth + 1)


def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "layout"
    dest, path = sys.argv[2], sys.argv[3]
    conn = Connection()
    conn.start()

    if action == "layout":
        rev, node = layout(conn, dest, path)
        print(f"revision {rev}")
        render(node)
    elif action == "open":
        need, = conn.call_blocking(dest, path, "com.canonical.dbusmenu",
                                   "AboutToShow", "i", [0],
                                   reply_signature="b", timeout=5)
        print(f"AboutToShow(0) -> {need}")
    elif action == "click":
        item_id = int(sys.argv[4])
        conn.call_blocking(dest, path, "com.canonical.dbusmenu", "Event",
                           "isvu", [item_id, "clicked", ("s", ""), 0],
                           reply_signature="", timeout=5)
        print(f"clicked {item_id}")
        time.sleep(0.3)
    elif action == "watch-props":
        # capture ItemsPropertiesUpdated signals for a few seconds
        got = []
        conn.add_signal("com.canonical.dbusmenu", "ItemsPropertiesUpdated",
                        None, lambda *v: got.append(v))
        deadline = time.time() + float(sys.argv[4])
        while time.time() < deadline:
            time.sleep(0.1)
        print(f"captured {len(got)} updates: {got}")


if __name__ == "__main__":
    main()
