"""The developer tools: the checks must catch what they claim to, and dev mode must work."""
import json
import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtWidgets import QComboBox, QPushButton

from test_window import WindowCase
from devtools import devmode
from devtools.checks import failures, run_checks
from sample import sample_tree
from storage import create_tree


def kinds(window):
    return {p.kind for p in failures(run_checks(window))}


class CheckRuleTests(WindowCase):
    def test_a_loose_button_is_a_stray_window(self):
        self.window.load_sample()
        loose = QPushButton("loose")
        self.addCleanup(loose.deleteLater)
        self.assertIn("stray_window", kinds(self.window))
        loose.setParent(self.window)
        self.assertNotIn("stray_window", kinds(self.window))

    def test_drop_down_lists_are_not_stray(self):
        self.window.load_sample()
        combo = QComboBox(self.window)
        combo.addItems(["a", "b"])
        combo.showPopup()
        combo.hidePopup()
        self.assertEqual(kinds(self.window), set())

    def test_disk_differing_from_memory_is_caught(self):
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.assertEqual(kinds(self.window), set())
        self.window.tree.people["ante"].given = "Changed but not saved"
        self.assertIn("disk_differs", kinds(self.window))
        self.window.tree.people["ante"].given = "Ante"

    def test_selected_person_must_be_shown(self):
        self.window.load_sample()
        self.window.selected = "zvonko"  # Zvonko is in another family line.
        self.assertIn("selected_not_shown", kinds(self.window))
        self.window.refresh()
        self.assertEqual(kinds(self.window), set())


class DevModeTests(WindowCase):
    def setUp(self):
        super().setUp()
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.dev = devmode.install(self.window, serve=False)

    def ask(self, command, arg=None):
        return json.loads(json.dumps(self.dev.handle(json.dumps({"cmd": command, "arg": arg}).encode())))

    def test_state_and_checks(self):
        reply = self.ask("state")
        self.assertTrue(reply["ok"])
        self.assertEqual(reply["result"]["people"], 16)
        self.assertEqual(self.ask("checks")["result"], [])
        self.assertIn("checks OK", self.dev.badge.text())

    def test_select_and_actions_are_logged(self):
        self.assertTrue(self.ask("select", "Luka")["ok"])
        self.assertEqual(self.window.selected, "luka")
        self.answers.people = [{"given": "Novi", "link": "birth"}]
        self.assertTrue(self.ask("action", "add_child Luka")["ok"])
        self.assertTrue(self.person_named("Novi"))
        log = "\n".join(self.ask("log", "50")["result"])
        self.assertIn("action add_child on Luka", log)

    def test_add_buttons_still_work_in_dev_mode(self):
        self.window.select("luka")
        self.answers.people = [{"given": "Klik", "link": "birth"}]
        self.window.view.on_add("add_child", "luka")
        self.assertTrue(self.person_named("Klik"))

    def test_overlay_draws_and_goes_away(self):
        self.assertTrue(self.ask("overlay", "on")["result"])
        self.assertIsNotNone(self.dev.overlay)
        self.window.refresh()
        self.assertIs(self.dev.overlay.scene(), self.window.view.scene())
        self.assertFalse(self.ask("overlay", "off")["result"])
        self.assertIsNone(self.dev.overlay)

    def test_failing_check_turns_the_badge_red(self):
        loose = QPushButton("loose")
        self.addCleanup(loose.deleteLater)
        self.dev.check_now()
        self.assertIn("FAILED", self.dev.badge.text())
        loose.setParent(self.window)
        self.dev.check_now()

    def test_bad_requests_answer_with_an_error(self):
        self.assertFalse(self.ask("select", "Nobody")["ok"])
        self.assertFalse(self.ask("fly")["ok"])
        self.assertFalse(self.dev.handle(b"not json")["ok"])


if __name__ == "__main__":
    unittest.main()


class DriveTests(WindowCase):
    """The commands tools/maiores-mcp uses: see and drive the window like a person."""

    def setUp(self):
        super().setUp()
        create_tree(self.folder, sample_tree())
        self.window.open_path(self.folder)
        self.dev = devmode.install(self.window, serve=False)

    ask = DevModeTests.ask

    def settle(self):
        from PySide6.QtWidgets import QApplication
        for _ in range(3):
            QApplication.processEvents()

    def test_picture_menu_and_widgets(self):
        picture = self.ask("picture", {})["result"]
        self.assertGreater(len(picture["png"]), 1000)
        entries = self.ask("menu", {"path": "Person"})["result"]["entries"]
        self.assertTrue(any("child" in e.lower() for e in entries))
        listing = self.ask("widgets", {"depth": 3})["result"]
        self.assertIn("@0 MainWindow", listing)
        self.assertFalse(self.ask("menu", {"path": "No such menu"})["ok"])

    def test_set_picks_the_exact_item_first(self):
        from devtools.drive import Driver
        combo = QComboBox(self.window)
        combo.setObjectName("sex_test")
        combo.addItems(["Unknown", "Female", "Male"])
        combo.show()
        self.addCleanup(combo.deleteLater)
        Driver(self.window).set_value("name:sex_test", "Male")
        self.assertEqual(combo.currentText(), "Male")

    def test_deferred_action_replies_before_its_dialog(self):
        self.answers.people = [{"given": "Kasniji", "link": "birth"}]
        reply = self.ask("action", {"key": "add_child", "who": "Luka"})
        self.assertTrue(reply["ok"])
        self.assertFalse(any(p.given == "Kasniji" for p in self.window.tree.people.values()))  # Not yet.
        self.settle()
        self.assertTrue(self.person_named("Kasniji"))

    def test_the_mcp_server_speaks_the_protocol(self):
        import subprocess
        server = Path(__file__).resolve().parent.parent / "tools" / "maiores-mcp"
        messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
                    {"jsonrpc": "2.0", "method": "notifications/initialized"},
                    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
                    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                     "params": {"name": "maiores_state", "arguments": {"instance": "hidden"}}}]
        done = subprocess.run([sys.executable, str(server)], input="\n".join(json.dumps(m) for m in messages),
                              capture_output=True, text=True, timeout=30,
                              env=dict(os.environ, XDG_CACHE_HOME=str(self.folder / "cache")))
        replies = [json.loads(line) for line in done.stdout.splitlines()]
        self.assertEqual([r["id"] for r in replies], [1, 2, 3])
        names = {t["name"] for t in replies[1]["result"]["tools"]}
        self.assertTrue({"maiores_launch", "maiores_screenshot", "maiores_click", "maiores_menu"} <= names)
        self.assertTrue(replies[2]["result"]["isError"])  # Nothing hidden runs in this test.
