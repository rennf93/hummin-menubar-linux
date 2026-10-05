"""StatusNotifierItem + com.canonical.dbusmenu served on one object path.

This is the Linux equivalent of NSStatusItem: the panel (COSMIC, KDE, XFCE,
GNOME's AppIndicator extension, ...) shows our icon and renders our menu from
the dbusmenu layout we expose here.
"""
import os
import threading

SNI_IFACE = "org.kde.StatusNotifierItem"
MENU_IFACE = "com.canonical.dbusmenu"
PROPS_IFACE = "org.freedesktop.DBus.Properties"
INTROSPECTABLE_IFACE = "org.freedesktop.DBus.Introspectable"
PEER_IFACE = "org.freedesktop.DBus.Peer"
WATCHER = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"

_MENU_PROPS = {
    "Version": ("u", 3),
    "TextDirection": ("s", "ltr"),
    "Status": ("s", "normal"),
    "IconThemePath": ("as", []),
}

_INTROSPECT_XML = """\
<node name="{path}">
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="i" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="AttentionIconPixmap" type="a(iiay)" access="read"/>
    <property name="AttentionMovieName" type="s" access="read"/>
    <property name="ToolTip" type="(sa(iiay)ss)" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <signal name="NewIcon"/>
    <signal name="NewTitle"/>
    <signal name="NewStatus"/>
  </interface>
  <interface name="com.canonical.dbusmenu">
    <method name="GetLayout">
      <arg direction="in" name="parentId" type="i"/>
      <arg direction="in" name="recursionDepth" type="i"/>
      <arg direction="in" name="propertyNames" type="as"/>
      <arg direction="out" name="revision" type="u"/>
      <arg direction="out" name="layout" type="(ia{sv}v)"/>
    </method>
    <method name="GetGroupProperties">
      <arg direction="in" name="ids" type="ai"/>
      <arg direction="in" name="propertyNames" type="as"/>
      <arg direction="out" name="properties" type="a(ia{{sv}})"/>
    </method>
    <method name="GetProperty">
      <arg direction="in" name="id" type="i"/>
      <arg direction="in" name="property" type="s"/>
      <arg direction="out" name="value" type="v"/>
    </method>
    <method name="AboutToShow">
      <arg direction="in" name="id" type="i"/>
      <arg direction="out" name="needUpdate" type="b"/>
    </method>
    <method name="Event">
      <arg direction="in" name="id" type="i"/>
      <arg direction="in" name="eventId" type="s"/>
      <arg direction="in" name="data" type="v"/>
      <arg direction="in" name="timestamp" type="u"/>
    </method>
    <method name="EventGroup">
      <arg direction="in" name="events" type="a(isvu)"/>
      <arg direction="out" name="idErrors" type="ai"/>
    </method>
    <method name="AboutToShowGroup">
      <arg direction="in" name="ids" type="ai"/>
      <arg direction="out" name="updatesNeeded" type="ai"/>
      <arg direction="out" name="idErrors" type="ai"/>
    </method>
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <signal name="ItemsPropertiesUpdated">
      <arg name="updatedProps" type="a(ia{{sv}})"/>
      <arg name="removedProps" type="a(ias)"/>
    </signal>
    <signal name="LayoutUpdated">
      <arg name="revision" type="u"/>
      <arg name="parent" type="i"/>
    </signal>
  </interface>
  <interface name="org.freedesktop.DBus.Properties">
    <method name="Get">
      <arg direction="in" name="interface" type="s"/>
      <arg direction="in" name="property" type="s"/>
      <arg direction="out" name="value" type="v"/>
    </method>
    <method name="GetAll">
      <arg direction="in" name="interface" type="s"/>
      <arg direction="out" name="props" type="a{{sv}}"/>
    </method>
    <method name="Set">
      <arg direction="in" name="interface" type="s"/>
      <arg direction="in" name="property" type="s"/>
      <arg direction="in" name="value" type="v"/>
    </method>
  </interface>
  <interface name="org.freedesktop.DBus.Introspectable">
    <method name="Introspect">
      <arg direction="out" name="data" type="s"/>
    </method>
  </interface>
  <interface name="org.freedesktop.DBus.Peer">
    <method name="Ping"/>
  </interface>
</node>
"""


class Tray:
    def __init__(self, conn):
        self.conn = conn
        self.path = f"/StatusNotifierItem/{os.getpid()}"
        self.menu = Menu(conn, self.path)
        self._lock = threading.Lock()
        self._pixmap = []

    def set_app(self, app):
        self.menu.app = app

    def export(self):
        c = self.conn
        c.add_method(self.path, PROPS_IFACE, "Get", self._prop_get)
        c.add_method(self.path, PROPS_IFACE, "GetAll", self._prop_get_all)
        c.add_method(self.path, PROPS_IFACE, "Set", self._prop_set)
        c.add_method(self.path, INTROSPECTABLE_IFACE, "Introspect",
                     self._introspect)
        c.add_method(self.path, PEER_IFACE, "Ping", lambda msg: None)
        self.menu.export()

    def set_icon(self, width, height, argb):
        with self._lock:
            self._pixmap = [(width, height, argb)]
        self.conn.send_signal(self.path, SNI_IFACE, "NewIcon", "", [])

    def register(self):
        """Best effort; a watcher appearing later re-registers via NameOwnerChanged."""
        try:
            self.conn.call_blocking(
                WATCHER, WATCHER_PATH, WATCHER,
                "RegisterStatusNotifierItem", "s", [self.path], "")
            return True
        except Exception as exc:
            if self.menu.app is not None:
                self.menu.app.log_main(f"SNI registration failed: {exc}")
            return False

    # ---- org.freedesktop.DBus.Properties ------------------------------------

    def _all_props(self):
        with self._lock:
            pixmap = self._pixmap
        return {
            "Category": ("s", "ApplicationStatus"),
            "Id": ("s", "hummin-menubar"),
            "Title": ("s", "hummin-menubar"),
            "Status": ("s", "Active"),
            "WindowId": ("i", 0),
            "IconName": ("s", ""),
            "IconPixmap": ("a(iiay)", pixmap),
            "OverlayIconPixmap": ("a(iiay)", []),
            "AttentionIconName": ("s", ""),
            "AttentionIconPixmap": ("a(iiay)", []),
            "AttentionMovieName": ("s", ""),
            "ToolTip": ("(sa(iiay)ss)", ("", [], "hummin-menubar",
                                         "LLM fleet control")),
            "ItemIsMenu": ("b", True),
            "Menu": ("o", self.path),
        }

    def _prop_get(self, _msg, iface, name):
        if iface == SNI_IFACE:
            props = self._all_props()
        elif iface == MENU_IFACE:
            props = _MENU_PROPS
        else:
            raise _no_prop(iface, name)
        if name not in props:
            raise _no_prop(iface, name)
        return ("v", [props[name]])

    def _prop_get_all(self, _msg, iface):
        if iface == SNI_IFACE:
            return ("a{sv}", [self._all_props()])
        if iface == MENU_IFACE:
            return ("a{sv}", [dict(_MENU_PROPS)])
        raise _no_prop(iface, "*")

    def _prop_set(self, _msg, _iface, _name, _value):
        return None

    def _introspect(self, _msg):
        return ("s", [_INTROSPECT_XML.format(path=self.path)])


def _no_prop(iface, name):
    from .dbus import DBusError, ERR_UNKNOWN_PROP
    return DBusError(ERR_UNKNOWN_PROP, f"{iface}.{name}")


class Menu:
    """dbusmenu server. The tree is static after build; state changes flow
    through ItemsPropertiesUpdated, and AboutToShow always reports True so
    panels refetch (the macOS app re-renders on menuWillOpen the same way)."""

    def __init__(self, conn, path):
        self.conn = conn
        self.path = path
        self.app = None
        self.items = {}     # id -> payload dict (kind, server, action, mode)
        self.children = {0: []}
        self.static = {}    # id -> {prop: (sig, value)}
        self.dyn = {}       # id -> {prop: (sig, value)}
        self.revision = 1

    def export(self):
        c = self.conn
        for member, fn in (("GetLayout", self._get_layout),
                           ("GetGroupProperties", self._get_group_properties),
                           ("GetProperty", self._get_property),
                           ("AboutToShow", self._about_to_show),
                           ("Event", self._event),
                           ("EventGroup", self._event_group),
                           ("AboutToShowGroup", self._about_to_show_group)):
            c.add_method(self.path, MENU_IFACE, member, fn)

    # ---- tree building (called by App.attach) --------------------------------

    def add(self, parent, kind, static=None, **payload):
        item_id = max(self.children) + 1
        self.items[item_id] = dict(kind=kind, **payload)
        self.children.setdefault(item_id, [])
        self.children.setdefault(parent, []).append(item_id)
        if static:
            self.static[item_id] = static
        return item_id

    # ---- property updates -----------------------------------------------------

    def update(self, targets):
        """targets: {id: {prop: (sig, value)}}; emits one signal for the delta."""
        changed = {}
        for item_id, wanted in targets.items():
            cur = self.dyn.setdefault(item_id, {})
            delta = {k: v for k, v in wanted.items() if cur.get(k) != v}
            if delta:
                cur.update(delta)
                changed[item_id] = delta
        if changed:
            self.revision += 1
            updated = [(i, props) for i, props in sorted(changed.items())]
            self.conn.send_signal(self.path, MENU_IFACE,
                                  "ItemsPropertiesUpdated",
                                  "a(ia{sv})a(ias)", (updated, []))

    def props_for(self, item_id, names=None):
        props = dict(self.static.get(item_id, {}))
        props.update(self.dyn.get(item_id, {}))
        if names:
            props = {k: v for k, v in props.items() if k in names}
        return props

    # ---- protocol methods ------------------------------------------------------

    def _get_layout(self, _msg, parent_id, _depth, names):
        # recursionDepth is ignored on purpose: the whole tree is small, and
        # delivering it in one go keeps lazy-fetch quirks out of the picture.
        return ("u(ia{sv}av)", (self.revision, self._node(parent_id, names)))

    def _node(self, item_id, names):
        # COSMIC's dbusmenu client wants the children as a plain array of
        # variants (signature (ia{sv}av) per node), NOT the spec's v-wrapped
        # form — it rejects the reply otherwise and the menu never opens.
        kids = [self._node(c, names) for c in self.children.get(item_id, ())]
        return (item_id, self.props_for(item_id, names),
                [("(ia{sv}av)", k) for k in kids])

    def _get_group_properties(self, _msg, ids, names):
        return ("a(ia{sv})", [(i, self.props_for(i, names)) for i in ids])

    def _get_property(self, _msg, item_id, name):
        props = self.props_for(item_id)
        if name in props:
            return ("v", [props[name]])
        return ("v", [("s", "")])

    def _about_to_show(self, _msg, _item_id):
        if self.app is not None:
            self.app.menu_opened()
        return ("b", (True,))

    def _event(self, _msg, item_id, event, _data, _timestamp):
        if event == "clicked" and self.app is not None:
            self.app.clicked(item_id)
        return None

    def _event_group(self, _msg, events):
        for item_id, event, _data, _ts in events:
            if event == "clicked" and self.app is not None:
                self.app.clicked(item_id)
        return ("ai", ([],))

    def _about_to_show_group(self, _msg, _ids):
        if self.app is not None:
            self.app.menu_opened()
        return ("aiai", ([], []))
