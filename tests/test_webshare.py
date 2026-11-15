"""The tree as a web page: one file (optionally locked with a password), or shown live."""
import datetime
import json
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

import privacy  # noqa: E402
import webshare  # noqa: E402
from test_sources import parish_tree  # noqa: E402

TODAY = datetime.date(2026, 11, 13)


def everyone_dead():
    tree = parish_tree()
    for person in tree.people.values():
        person.living, person.death = "no", person.death or {"date": "", "place": ""}
    return tree


def payload_of(text):
    return json.loads(text.split("const PAYLOAD = ")[1].split(";\nconst app")[0].replace("<\\/", "</"))


class PageTests(unittest.TestCase):
    def test_the_page_holds_the_family_and_its_links(self):
        data = webshare.site_data(everyone_dead(), "davor")
        davor = data["people"]["davor"]
        self.assertEqual(davor["parents"], ["ivan"])
        self.assertIn("dragan", davor["siblings"])
        self.assertIn(["Born", "1957, Trogir"], davor["facts"])
        self.assertEqual(data["home"], "davor")
        self.assertEqual(payload_of(webshare.page(data))["open"]["people"]["ivan"]["name"], "Ivan Radić")

    @unittest.skipUnless(webshare.encryption_available(), "no encryption library here")
    def test_a_locked_page_says_nothing_without_the_password(self):
        data = webshare.site_data(everyone_dead(), "davor")
        text = webshare.page(data, "kum-dragan-1957")
        for word in ("Davor", "Dragan", "Radić", "Trogir", "Joannes", "fisherman"):
            self.assertNotIn(word, text)
        locked = payload_of(text)["locked"]
        self.assertEqual(json.loads(webshare.decrypt(locked, "kum-dragan-1957"))["people"]["ivan"]["story"],
                         "Ivan was a fisherman.\n\nHe built the house in 1950.")
        with self.assertRaises(Exception):
            webshare.decrypt(locked, "wrong-password")
        again = payload_of(webshare.page(data, "kum-dragan-1957"))["locked"]
        self.assertNotEqual(again["salt"], locked["salt"])  # A fresh salt and nonce every time.

    def test_the_sharing_rules_apply(self):
        tree = parish_tree()  # Davor has no death recorded: he counts as living.
        data = webshare.site_data(privacy.shareable(tree, TODAY), "davor")
        self.assertNotIn("Davor", json.dumps(data, ensure_ascii=False))

    def test_text_can_not_break_out_of_the_page(self):
        tree = everyone_dead()
        tree.people["ivan"].notes = "</script><script>alert(1)</script>"
        text = webshare.page(webshare.site_data(tree))
        self.assertEqual(text.count("</script>"), 1)  # Only the page's own closing tag.


class LiveShareTests(unittest.TestCase):
    def test_only_the_secret_address_answers_and_stop_ends_it(self):
        share = webshare.LiveShare(webshare.site_data(everyone_dead()))
        base = f"http://127.0.0.1:{share.port}"
        try:
            with urllib.request.urlopen(f"{base}/{share.token}", timeout=5) as reply:
                self.assertIn("Ivan Radić", reply.read().decode("utf-8"))
            for wrong in ("/", "/x", f"/{share.token}x", "/../tree.json"):
                with self.assertRaises(urllib.error.HTTPError):
                    urllib.request.urlopen(base + wrong, timeout=5)
            self.assertEqual(share.views, 1)
        finally:
            share.stop()
            share.stop()  # Twice is fine.
        with self.assertRaises(OSError):
            urllib.request.urlopen(f"{base}/{share.token}", timeout=2)

    def test_a_qr_code_is_drawn_for_the_address(self):
        png = webshare.qr_png("http://192.168.1.20:8000/abc")
        if png:  # The QR library may be missing on a phone build.
            self.assertEqual(png[:8], b"\x89PNG\r\n\x1a\n")


class WindowTests(unittest.TestCase):
    def test_the_window_writes_a_page_and_shows_one_live(self):
        from PySide6.QtCore import QSettings
        import app as app_module
        from storage import create_tree
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            create_tree(folder / "Radic.tree", everyone_dead())
            window = app_module.MainWindow(QSettings(str(folder / "s.ini"), QSettings.Format.IniFormat), today=TODAY)
            window.alert = window.inform = lambda *a: None
            window.open_path(folder / "Radic.tree")
            self.assertTrue(window.write_web_page(folder / "page", {"hide_living": True, "photos": True,
                                                                    "password": ""}))
            self.assertIn("Ivan", (folder / "page.html").read_text(encoding="utf-8"))
            seen = []
            window.ask_web_page = lambda with_password=True: {"hide_living": True, "photos": False, "password": ""}
            window.show_live_share = lambda share: seen.append(urllib.request.urlopen(
                f"http://127.0.0.1:{share.port}/{share.token}", timeout=5).status)
            window.start_live_share()
            self.assertEqual(seen, [200])
            self.assertIsNone(window.live_share)  # Stopped once the window closed.
            window.close()


if __name__ == "__main__":
    unittest.main()
