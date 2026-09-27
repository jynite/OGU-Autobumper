"""Bounded, redacted operational events shared by CMD, disk and connected clients."""
import asyncio
from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import queue
import sys
import threading
import uuid


class _ConsoleSink:
    """Best-effort console delivery; a stalled terminal cannot hold the event lock."""
    def __init__(self, capacity=500):
        self.queue = queue.Queue(maxsize=capacity)
        self.thread = threading.Thread(target=self._run, name="activity-console", daemon=True)
        self.thread.start()

    def enqueue(self, line):
        try:
            self.queue.put_nowait((sys.stdout, line, None))
        except queue.Full:
            # Disk and replay remain authoritative when console output is backpressured.
            pass

    def flush(self, timeout=1):
        done = threading.Event()
        try:
            self.queue.put_nowait((None, None, done))
        except queue.Full:
            return False
        return done.wait(timeout)

    def close(self, timeout=1):
        if not self.flush(timeout):
            return False
        self.queue.put_nowait(None)
        self.thread.join(timeout)
        return not self.thread.is_alive()

    def _run(self):
        while True:
            item = self.queue.get()
            if item is None:
                return
            stream, line, done = item
            if done is not None:
                done.set()
                continue
            try:
                stream.write(line + "\n")
                stream.flush()
            except (OSError, ValueError, UnicodeError):
                pass


_CONSOLE = _ConsoleSink()


class ActivityLog:
    def __init__(self, directory, capacity=500, max_bytes=1_000_000, backups=3, console=None):
        self.directory = Path(directory)
        self.path = self.directory / "activity.jsonl"
        self.events = deque(maxlen=capacity)
        self.max_bytes, self.backups = max_bytes, backups
        self.lock = threading.RLock()
        self.secrets = set()
        self.loop = None
        self.clients = set()
        self.persistence_ok = True
        self.on_persistence_change = None
        self.console = console if console is not None else _CONSOLE

    def set_secrets(self, config):
        # Retain previous values too: a running worker can still use the old config.
        with self.lock:
            self.secrets.update(str(v) for v in [config.get("username"), config.get("password"),
                *[t.get("message") for t in config.get("threads", [])]] if v)

    def redact(self, value):
        value = str(value)
        for secret in sorted(self.secrets, key=len, reverse=True):
            value = value.replace(secret, "[redacted]")
        value = re.sub(r"https?://[^\s]+", "[url omitted]", value)
        value = re.sub(r"(?i)(password|token|secret|authorization)\s*[:=]\s*[^\s,;]+", r"\1=[redacted]", value)
        return value[:2000]

    def restore(self):
        with self.lock:
            try:
                for path in [*[self.directory / f"activity.jsonl.{i}" for i in range(self.backups, 0, -1)], self.path]:
                    if not path.exists():
                        continue
                    # Read bounded tails, even if an old file is unexpectedly large.
                    with path.open("rb") as source:
                        size = source.seek(0, 2)
                        source.seek(max(0, size - self.max_bytes))
                        if size > self.max_bytes:
                            source.readline()
                        for line in source:
                            try:
                                event = json.loads(line)
                                if all(k in event for k in ("id", "timestamp", "level", "event_type", "message")):
                                    restored = {k: event[k] for k in ("id", "timestamp", "level", "event_type", "message")}
                                    restored["message"] = self.redact(restored["message"])
                                    if re.fullmatch(r"[a-f0-9]{32}", str(event.get("run_id", ""))):
                                        restored["run_id"] = event["run_id"]
                                    if type(event.get("thread_index")) is int and 1 <= event["thread_index"] <= 100:
                                        restored["thread_index"] = event["thread_index"]
                                    self.events.append(restored)
                            except (ValueError, TypeError):
                                continue
            except OSError:
                self.persistence_ok = False

    def attach(self, loop):
        self.loop = loop

    def history(self):
        with self.lock:
            return list(self.events)

    def publish(self, payload):
        if self.loop and not self.loop.is_closed():
            try:
                self.loop.call_soon_threadsafe(self._deliver, payload)
            except RuntimeError:
                # A late worker may finish as the server closes its event loop.
                pass

    def _deliver(self, payload):
        for queue in tuple(self.clients):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                # Drop this connection, then let it replay bounded history on reconnect.
                self.clients.discard(queue)
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(None)

    def _write_console(self, event):
        thread = f" [thread {event['thread_index']}]" if 'thread_index' in event else ''
        # Redaction has already run. Flatten controls so an event cannot rewrite CMD output.
        message = re.sub(r"[\x00-\x1f\x7f-\x9f]", " ", event['message'])
        self.console.enqueue(f"{event['timestamp']} [{event['level']}]{thread} {message}")

    def emit(self, level, event_type, message, run_id=None, thread_index=None):
        with self.lock:
            event = {"id": uuid.uuid4().hex,
                     "timestamp": datetime.now(timezone.utc).isoformat(),
                     "level": level, "event_type": event_type, "message": self.redact(message)}
            if run_id:
                event["run_id"] = run_id
            if thread_index is not None:
                event["thread_index"] = thread_index
            self.events.append(event)
            self._write_console(event)
            previous_persistence = self.persistence_ok
            try:
                self.directory.mkdir(parents=True, exist_ok=True)
                data = json.dumps(event, ensure_ascii=False) + "\n"
                if self.path.exists() and self.path.stat().st_size + len(data.encode("utf-8")) > self.max_bytes:
                    for index in range(self.backups, 0, -1):
                        old = self.path if index == 1 else self.directory / f"activity.jsonl.{index - 1}"
                        new = self.directory / f"activity.jsonl.{index}"
                        if old.exists():
                            old.replace(new)
                with self.path.open("a", encoding="utf-8") as target:
                    target.write(data)
                self.persistence_ok = True
            except OSError:
                if self.persistence_ok:
                    warning = dict(event, id=uuid.uuid4().hex, level="WARNING", event_type="log.persistence_failed",
                                   message="Activity could not be saved to disk. Live events remain available.")
                    self.events.append(warning)
                    self._write_console(warning)
                    self.publish({"type": "event", "event": warning})
                self.persistence_ok = False
            self.publish({"type": "event", "event": event})
            if previous_persistence != self.persistence_ok and self.on_persistence_change:
                self.on_persistence_change()
            return event
