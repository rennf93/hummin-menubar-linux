"""Config loading: same servers.json schema and search order as the macOS app."""
import json
import os
from dataclasses import dataclass
from typing import Optional

CONFIG_FILE_NAME = "servers.json"


@dataclass
class Server:
    id: str
    label: str
    host: str
    port: Optional[int]
    up: str
    down: str
    health: str
    mutex_group: Optional[str] = None
    modes: Optional[list] = None
    mode_get: Optional[str] = None
    mode_set: Optional[str] = None


@dataclass
class MenubarConfig:
    host_order: list
    servers: list


class ConfigError(Exception):
    pass


def search_paths():
    paths = []
    env = os.environ.get("HUMMIN_MENUBAR_CONFIG")
    if env:
        paths.append(env)
    home = os.path.expanduser("~")
    paths.append(os.path.join(home, ".config", "hummin-menubar", CONFIG_FILE_NAME))
    paths.append(CONFIG_FILE_NAME)
    return paths


def logs_directory():
    """macOS counterpart is ~/Library/Logs; XDG's is ~/.local/state."""
    state = os.environ.get("XDG_STATE_HOME") or os.path.join(
        os.path.expanduser("~"), ".local", "state")
    return os.path.join(state, "hummin-menubar")


def load():
    """Returns (MenubarConfig, path); raises ConfigError with the macOS wording."""
    paths = search_paths()
    for path in paths:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, ValueError) as exc:
            raise ConfigError(f"servers.json at {path} is invalid: {exc}")
        return _parse(raw), path
    raise ConfigError(
        "No servers.json found. Looked in:\n" + "\n".join(paths) +
        "\nCopy examples/servers.example.json to ~/.config/hummin-menubar/servers.json and edit it.")


def _parse(raw):
    if not isinstance(raw, dict):
        raise ConfigError("servers.json is invalid: expected a JSON object")
    servers = []
    try:
        for s in raw.get("servers", []):
            servers.append(Server(
                id=s["id"], label=s["label"], host=s["host"],
                port=s.get("port"), up=s["up"], down=s["down"], health=s["health"],
                mutex_group=s.get("mutexGroup"), modes=s.get("modes"),
                mode_get=s.get("modeGet"), mode_set=s.get("modeSet")))
    except (KeyError, TypeError) as exc:
        raise ConfigError(f"servers.json is invalid: missing field {exc}")
    return MenubarConfig(host_order=raw.get("hostOrder", []), servers=servers)
