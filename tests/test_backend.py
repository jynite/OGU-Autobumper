import asyncio
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from activity import ActivityLog, _ConsoleSink
from autobumper_linux import create_app, run_browser_session


CONFIG = {"username": "private-account", "password": "secret-password", "interval": 31,
          "threads": [{"url": "https://example.com/thread/1?token=private", "message": "private reply text"}]}


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = self.root / "config.json"
        self.config.write_text(json.dumps(CONFIG), encoding="utf-8")
        self.app = create_app(self.config, self.root / "logs", worker=lambda runtime, config: "failed")
        self.client = TestClient(self.app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.temp.cleanup()

    def wait_state(self, expected):
        for _ in range(100):
            state = self.client.get("/api/status").json()
            if state["state"] == expected:
                return state
            time.sleep(.01)
        self.fail(f"Expected {expected}, got {state}")

    def test_password_write_only_and_blank_or_omitted_preserves(self):
        before = self.config.read_bytes()
        response = self.client.get("/api/config")
        self.assertEqual(before, self.config.read_bytes())
        self.assertNotIn("password", response.json())
        self.assertTrue(response.json()["password_set"])
        for password in (None, ""):
            payload = dict(CONFIG)
            payload.pop("password")
            if password is not None:
                payload["password"] = password
            response = self.client.post("/api/config", json=payload)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(CONFIG["password"], response.text)
            self.assertEqual(json.loads(self.config.read_text())["password"], CONFIG["password"])

    def test_invalid_save_atomic_and_error_does_not_echo(self):
        before = self.config.read_bytes()
        for update in ({"interval": 0}, {"interval": 1441}, {"interval": True},
                       {"threads": [{"url": "javascript:secret-password", "message": "ok"}]},
                       {"threads": [{"url": "https://u:p@example.com", "message": "ok"}]},
                       {"threads": [{"url": "https://example.com", "message": " "}]},
                       {"password": "secret-password" * 200}):
            response = self.client.post("/api/config", json=CONFIG | update)
            self.assertEqual(response.status_code, 422)
            self.assertNotIn("secret-password", response.text)
            self.assertEqual(before, self.config.read_bytes())

    def test_write_failure_keeps_previous_file(self):
        before = self.config.read_bytes()
        with patch("autobumper_linux.os.replace", side_effect=OSError("secret-password")):
            response = self.client.post("/api/config", json=CONFIG | {"interval": 12})
        self.assertEqual(response.status_code, 500)
        self.assertNotIn("secret-password", response.text)
        self.assertEqual(before, self.config.read_bytes())
        self.assertEqual(list(self.root.glob("tmp*")), [])

    def test_corrupt_config_cannot_be_silently_overwritten(self):
        self.config.write_text("invalid secret-password")
        self.assertEqual(self.client.get("/api/config").status_code, 500)
        self.assertEqual(self.client.post("/api/config", json=CONFIG).status_code, 500)
        self.assertEqual(self.config.read_text(), "invalid secret-password")

    def test_missing_credentials_and_idle_stop_are_error_statuses(self):
        self.config.write_text(json.dumps(CONFIG | {"password": ""}))
        self.assertEqual(self.client.post("/api/start").status_code, 400)
        self.assertEqual(self.client.post("/api/stop").status_code, 409)

    def test_fatal_and_returned_failure_end_in_error_and_clear_task(self):
        for worker in (lambda runtime, config: "failed", lambda runtime, config: 1 / 0):
            self.app.state.runtime.worker = worker
            self.assertEqual(self.client.post("/api/start").status_code, 200)
            state = self.wait_state("Error")
            self.assertFalse(state["is_running"])
            self.assertIsNone(self.app.state.runtime.task)

    def test_stop_during_starting_blocks_restart_until_worker_completes(self):
        release = threading.Event()
        entered = threading.Event()
        def worker(runtime, config):
            entered.set()
            release.wait(2)
            return "stopped"
        self.app.state.runtime.worker = worker
        try:
            initial = self.client.get("/api/status").json()
            starting = self.client.post("/api/start").json()
            self.assertTrue(entered.wait(1))
            self.assertGreater(starting["status_version"], initial["status_version"])
            self.assertEqual(starting["server_id"], initial["server_id"])
            self.assertEqual(self.client.post("/api/start").status_code, 409)
            stopping = self.client.post("/api/stop").json()
            self.assertEqual(stopping["state"], "Stopping")
            self.assertGreater(stopping["status_version"], starting["status_version"])
            self.assertEqual(self.client.post("/api/start").status_code, 409)
            self.assertTrue(self.client.get("/api/status").json()["is_running"])
        finally:
            release.set()
        final = self.wait_state("Offline")
        self.assertFalse(final["is_running"])
        self.assertGreater(final["status_version"], stopping["status_version"])

    def test_cancel_retains_tracking_until_cleanup(self):
        release = threading.Event()
        entered = threading.Event()
        def worker(runtime, config):
            entered.set()
            release.wait(2)
            return "stopped"
        runtime = self.app.state.runtime
        runtime.worker = worker
        try:
            self.client.post("/api/start")
            self.assertTrue(entered.wait(1))
            runtime.loop.call_soon_threadsafe(runtime.task.cancel)
            self.wait_state("Stopping")
            self.assertEqual(self.client.post("/api/start").status_code, 409)
        finally:
            release.set()
        self.wait_state("Offline")

    def test_websocket_snapshot_replay_and_worker_events(self):
        events = self.app.state.events
        previous = events.emit("INFO", "test.previous", "Previous event")
        with self.client.websocket_connect("/api/ws") as ws:
            self.assertEqual(ws.receive_json()["type"], "status")
            history = ws.receive_json()
            self.assertEqual(history["type"], "history")
            self.assertIn(previous["id"], [event["id"] for event in history["events"]])
            thread = threading.Thread(target=lambda: events.emit("ERROR", "test.worker", "Worker failure"))
            thread.start()
            thread.join()
            while True:
                payload = ws.receive_json()
                if payload.get("event", {}).get("event_type") == "test.worker":
                    self.assertEqual(payload["event"]["level"], "ERROR")
                    break
        with self.client.websocket_connect("/api/ws") as ws:
            ws.receive_json()
            self.assertTrue(any(e["event_type"] == "test.worker" for e in ws.receive_json()["events"]))

    def test_disk_health_changes_push_versioned_status_without_run_transition(self):
        log = self.app.state.events
        with self.client.websocket_connect('/api/ws') as ws:
            before = ws.receive_json()
            ws.receive_json()
            original_directory = log.directory
            bad_directory = self.root / 'not-a-directory'
            bad_directory.write_text('file')
            log.directory = bad_directory
            try:
                log.emit('INFO', 'test.disk_failure', 'Disk failure example')
                while (failed := ws.receive_json())['type'] != 'status':
                    pass
                self.assertFalse(failed['log_persistence_ok'])
                self.assertGreater(failed['status_version'], before['status_version'])
                self.assertEqual(failed['state'], before['state'])
            finally:
                log.directory = original_directory
            log.emit('INFO', 'test.disk_recovered', 'Disk recovered')
            while (recovered := ws.receive_json())['type'] != 'status':
                pass
            self.assertTrue(recovered['log_persistence_ok'])
            self.assertGreater(recovered['status_version'], failed['status_version'])
            self.assertEqual(recovered['state'], before['state'])

    def test_shutdown_is_bounded_even_when_worker_does_not_return(self):
        release = threading.Event()
        entered = threading.Event()
        def worker(runtime, config):
            entered.set()
            release.wait(2)
            return "stopped"
        app = create_app(self.root / "separate.json", self.root / "separate-logs", worker=worker)
        (self.root / "separate.json").write_text(json.dumps(CONFIG))
        app.state.runtime.shutdown_timeout = .03
        started = time.monotonic()
        try:
            with TestClient(app) as client:
                self.assertEqual(client.post("/api/start").status_code, 200)
                self.assertTrue(entered.wait(1))
            self.assertLess(time.monotonic() - started, 1)
            self.assertEqual(app.state.runtime.state, "Error")
            self.assertTrue(app.state.runtime.shutting_down)
            self.assertTrue(any(event["event_type"] == "shutdown.pending" for event in app.state.events.history()))
        finally:
            release.set()


class ActivityTests(unittest.TestCase):
    def test_console_mirrors_redacted_event_without_terminal_controls(self):
        with tempfile.TemporaryDirectory() as directory, redirect_stdout(io.StringIO()) as output:
            log = ActivityLog(directory)
            log.set_secrets(CONFIG)
            event = log.emit('WARNING', 'test.console', 'secret-password private-account private reply text https://example.com?token=private\n\x1b[2J', thread_index=2)
            self.assertTrue(log.console.flush())
            line = output.getvalue()
            self.assertIn('[WARNING] [thread 2]', line)
            self.assertIn('[redacted]', line)
            for secret in ('secret-password', 'private-account', 'private reply text', 'token=private', '\x1b'):
                self.assertNotIn(secret, line)
            self.assertEqual(len(line.splitlines()), 1)
            self.assertEqual(log.history()[-1], event)

    def test_closed_console_does_not_break_disk_or_live_events(self):
        with tempfile.TemporaryDirectory() as directory:
            log = ActivityLog(directory)
            output = io.StringIO()
            with redirect_stdout(output), patch.object(output, 'write', side_effect=BrokenPipeError), patch.object(log, 'publish') as publish:
                event = log.emit('INFO', 'test.console_closed', 'Worker continues')
                self.assertTrue(log.console.flush())
            self.assertEqual(json.loads(log.path.read_text())['id'], event['id'])
            publish.assert_called_once_with({'type': 'event', 'event': event})

    def test_stalled_console_is_bounded_and_does_not_block_disk_or_delivery(self):
        entered, release = threading.Event(), threading.Event()
        output = io.StringIO()
        sink = _ConsoleSink(capacity=2)

        def stalled_write(value):
            entered.set()
            release.wait(2)

        try:
            with tempfile.TemporaryDirectory() as directory, redirect_stdout(output), patch.object(output, 'write', side_effect=stalled_write):
                log = ActivityLog(directory, console=sink)
                first = log.emit('INFO', 'test.stalled', 'First event')
                self.assertTrue(entered.wait(1))
                with patch.object(log, 'publish') as publish:
                    for index in range(5):
                        log.emit('INFO', 'test.stalled', f'Later event {index}')
                self.assertFalse(release.is_set())
                self.assertEqual(sink.queue.qsize(), 2)
                self.assertEqual(publish.call_count, 5)
                records = [json.loads(line) for line in log.path.read_text().splitlines()]
                self.assertEqual(len(records), 6)
                self.assertEqual(records[0]['id'], first['id'])
                self.assertEqual(len(log.history()), 6)
                release.set()
        finally:
            release.set()
            # Wait for queued writes to drain before stopping this isolated sink.
            for _ in range(100):
                if sink.flush(.01):
                    break
                time.sleep(.01)
            self.assertTrue(sink.close())

    def test_redaction_rotation_restore_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            log = ActivityLog(directory, capacity=4, max_bytes=700, backups=2)
            log.set_secrets(CONFIG)
            for index in range(30):
                log.emit("INFO", "test", f"{index} secret-password private-account private reply text https://example.com?token=private token=hidden", run_id="a" * 32, thread_index=2)
            self.assertEqual(len(log.history()), 4)
            paths = list(Path(directory).iterdir())
            self.assertLessEqual(len(paths), 3)
            content = "".join(path.read_text() for path in paths)
            for secret in ("secret-password", "private-account", "private reply text", "token=hidden", "token=private"):
                self.assertNotIn(secret, content)
            restored = ActivityLog(directory, capacity=4, max_bytes=700, backups=2)
            restored.set_secrets(CONFIG)
            restored.restore()
            self.assertEqual(restored.history()[-1]["id"], log.history()[-1]["id"])
            self.assertEqual(restored.history()[-1]["run_id"], "a" * 32)
            self.assertEqual(restored.history()[-1]["thread_index"], 2)
            self.assertLessEqual(len(restored.history()), 4)

    def test_disk_failure_keeps_live_history_and_reports_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "file"
            path.write_text("not a directory")
            log = ActivityLog(path)
            log.emit("ERROR", "test", "Still visible")
            self.assertFalse(log.persistence_ok)
            self.assertEqual({e["event_type"] for e in log.history()}, {"test", "log.persistence_failed"})

    def test_slow_client_does_not_block_fast_client(self):
        log = ActivityLog("unused")
        slow, fast = asyncio.Queue(maxsize=1), asyncio.Queue(maxsize=5)
        slow.put_nowait({"old": True})
        log.clients.update([slow, fast])
        log._deliver({"type": "event", "event": {"id": "new"}})
        self.assertNotIn(slow, log.clients)
        self.assertIsNone(slow.get_nowait())
        self.assertEqual(fast.get_nowait()["event"]["id"], "new")


class FakeStop:
    def __init__(self):
        self.stopped = False
    def is_set(self):
        return self.stopped
    def wait(self, seconds):
        if seconds == 31 * 60:
            self.stopped = True
        return self.stopped


class BrowserTests(unittest.TestCase):
    def runtime(self):
        from types import SimpleNamespace
        entries = []
        runtime = SimpleNamespace(stop_event=FakeStop(), active=lambda: entries.append("active"),
            emit=lambda level, kind, message, **kwargs: entries.append(kind),
            store=SimpleNamespace(load=lambda: CONFIG), events=SimpleNamespace(set_secrets=lambda config: None))
        return runtime, entries

    def driver(self, authenticated=True, post_buttons=True):
        from types import SimpleNamespace
        driver = SimpleNamespace(get=lambda url: None, wait_for_element=lambda selector, wait: True,
            run_js=lambda script: True, select=lambda selector: authenticated if "logout" in selector else None,
            select_all=lambda selector: [SimpleNamespace(click=lambda: None)] if "type='submit'" in selector or post_buttons else [])
        return driver

    def test_failed_login_does_not_activate_or_attempt_reply(self):
        runtime, entries = self.runtime()
        self.assertEqual(run_browser_session(self.driver(authenticated=False), runtime, CONFIG), "failed")
        self.assertIn("login.unverified", entries)
        self.assertNotIn("active", entries)
        self.assertNotIn("thread.opening", entries)

    def test_missing_post_control_reports_failure(self):
        runtime, entries = self.runtime()
        self.assertEqual(run_browser_session(self.driver(post_buttons=False), runtime, CONFIG), "stopped")
        self.assertIn("reply.control_missing", entries)
        self.assertNotIn("reply.submitted_unconfirmed", entries)

    def test_post_is_submitted_unconfirmed_never_success(self):
        runtime, entries = self.runtime()
        self.assertEqual(run_browser_session(self.driver(), runtime, CONFIG), "stopped")
        self.assertIn("reply.submitted_unconfirmed", entries)
        self.assertFalse(any("success" in e for e in entries))

    def test_failed_click_reports_failure(self):
        runtime, entries = self.runtime()
        driver = self.driver()
        original = driver.select_all
        def buttons(selector):
            if "name='submit'" in selector:
                from types import SimpleNamespace
                return [SimpleNamespace(click=lambda: (_ for _ in ()).throw(ValueError("private")))]
            return original(selector)
        driver.select_all = buttons
        run_browser_session(driver, runtime, CONFIG)
        self.assertIn("reply.failed", entries)
        self.assertNotIn("reply.submitted_unconfirmed", entries)

    def test_credentials_are_single_json_literal_not_placeholder_replacements(self):
        runtime, entries = self.runtime()
        driver = self.driver(authenticated=False)
        scripts = []
        driver.run_js = lambda script: scripts.append(script) or True
        config = CONFIG | {"username": 'PASSWORD_VALUE"; dangerous()', "password": "secret\nUSER_VALUE"}
        run_browser_session(driver, runtime, config)
        line = scripts[0].splitlines()[0]
        self.assertEqual(json.loads(line.removeprefix("const credentials = ").removesuffix(";")),
                         [config["username"], config["password"]])


if __name__ == "__main__":
    unittest.main()
