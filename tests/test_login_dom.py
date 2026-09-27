"""Opt-in Chrome regression: OGU's search and hidden quick-login precede login."""
import os
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from autobumper_linux import run_browser_session


class Stop:
    def __init__(self):
        self.stopped = False

    def is_set(self):
        return self.stopped

    def wait(self, seconds):
        return self.stopped


class PageDriver:
    def __init__(self, page, html, reject=False):
        self.page, self.html, self.reject = page, html, reject

    def get(self, url):
        self.page.set_content(self.html)
        self.page.evaluate("value => window.rejectLogin = value", self.reject)

    def run_js(self, script):
        return self.page.evaluate("() => {" + script + "\n}")

    def wait_for_element(self, selector, wait):
        return self.select(selector)

    def select(self, selector, wait=0):
        matches = self.page.locator(selector)
        return matches.first if matches.count() else None

    def select_all(self, selector):
        return self.page.locator(selector).all()


@unittest.skipUnless(os.environ.get("OGU_BROWSER_TESTS") == "1", "Set OGU_BROWSER_TESTS=1 for local Chrome regression")
class LoginDomTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from playwright.sync_api import sync_playwright
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(channel="chrome", headless=True)
        cls.html = (Path(__file__).parent / "fixtures/login.html").read_text(encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.playwright.stop()

    def exercise(self, html, reject=False):
        page = self.browser.new_page()
        self.addCleanup(page.close)
        stop, events = Stop(), []

        def active():
            events.append("active")
            stop.stopped = True  # Exercise authentication only; never enter posting.

        config = {"username": 'demo\"account', "password": 'demo\\password\"PASSWORD_VALUE',
                  "threads": [], "interval": 31}
        runtime = SimpleNamespace(stop_event=stop, active=active,
                                  emit=lambda level, kind, message, **kwargs: events.append(kind))
        with patch("autobumper_linux.LOGIN_WAIT_SECONDS", 3, create=True):
            result = run_browser_session(PageDriver(page, html, reject), runtime, config)
        return page, config, result, events

    def test_search_and_hidden_login_are_untouched_with_default_submit_button(self):
        page, config, result, events = self.exercise(self.html)
        self.assertEqual(page.evaluate("window.submissions"), ["login"])
        self.assertEqual(result, "stopped")
        self.assertIn("login.verified", events)
        self.assertEqual(page.locator('#login input[name="username"]').input_value(), config["username"])
        self.assertEqual(page.locator('#login input[name="password"]').input_value(), config["password"])
        self.assertEqual(page.locator('#quick-login input[name="username"]').input_value(), "")
        self.assertEqual(page.locator('#quick-login input[name="password"]').input_value(), "")
        self.assertEqual(page.locator('#login input[name="my_post_key"]').input_value(), "fixture-token")

    def test_explicit_submit_is_scoped_to_visible_login(self):
        page, _, result, events = self.exercise(self.html.replace("<button>Login</button>", '<input type="submit" value="Login">'))
        self.assertEqual(page.evaluate("window.submissions"), ["login"])
        self.assertEqual(result, "stopped")
        self.assertIn("active", events)

    def test_rejected_login_never_activates_or_posts(self):
        page, _, result, events = self.exercise(self.html, reject=True)
        self.assertEqual(page.evaluate("window.submissions"), ["login"])
        self.assertEqual(result, "failed")
        self.assertIn("login.unverified", events)
        self.assertNotIn("active", events)
        self.assertNotIn("thread.opening", events)


if __name__ == "__main__":
    unittest.main()
