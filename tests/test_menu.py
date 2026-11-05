import unittest

from hummin_menubar.app import App
from hummin_menubar.config import Server


class FakeMenu:
    """tray.Menu's tree bookkeeping, without D-Bus."""

    def __init__(self):
        self.items, self.children, self.static, self.dyn = {}, {0: []}, {}, {}

    def add(self, parent, kind, static=None, **payload):
        item_id = max(self.children) + 1
        self.items[item_id] = dict(kind=kind, **payload)
        self.children.setdefault(item_id, [])
        self.children.setdefault(parent, []).append(item_id)
        if static:
            self.static[item_id] = static
        return item_id

    def update(self, targets):
        for item_id, props in targets.items():
            self.dyn.setdefault(item_id, {}).update(props)


class FakeTray:
    def __init__(self):
        self.menu = FakeMenu()


def server(sid, host, port=9990):
    return Server(id=sid, label=sid, host=host, port=port, up="true", down="true", health="true")


class MenuTreeTest(unittest.TestCase):
    def setUp(self):
        self.app = App([server("a", "Laptop"), server("link", "Laptop", port=None), server("m", "Mac")],
                       ["Laptop", "Mac", "Empty"], None)
        self.tray = FakeTray()
        self.app.attach(self.tray)
        self.m = self.tray.menu

    def test_hosts_are_submenus_holding_their_servers(self):
        root = self.m.children[0]
        self.assertEqual([self.m.items[i]["kind"] for i in root], ["status", "host", "host", "sep", "quit"])
        laptop, mac = root[1], root[2]
        for host in (laptop, mac):
            self.assertEqual(self.m.static[host]["children-display"], ("s", "submenu"))
        self.assertEqual([self.m.items[i]["server"].id for i in self.m.children[laptop]], ["a", "link"])
        self.assertEqual([self.m.items[i]["server"].id for i in self.m.children[mac]], ["m"])
        row = self.m.children[laptop][0]
        self.assertEqual([self.m.items[i]["action"] for i in self.m.children[row]], ["start", "stop", "restart"])

    def test_host_labels_render(self):
        self.app.render()
        laptop = self.m.children[0][1]
        self.assertEqual(self.m.dyn[laptop]["label"], ("s", "Laptop"))


if __name__ == "__main__":
    unittest.main()
