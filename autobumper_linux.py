"""Local control API. Importing this module never opens a browser or starts a bot."""
import asyncio
from contextlib import asynccontextmanager, suppress
import json
import os
from pathlib import Path
import tempfile
import threading
from urllib.parse import urlsplit
import uuid

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from activity import ActivityLog

ROOT = Path(__file__).resolve().parent


class ThreadModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: str = Field(min_length=1, max_length=2048)
    message: str = Field(min_length=1, max_length=10000)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value):
        value = value.strip()
        try:
            parsed = urlsplit(value)
            valid = parsed.scheme in ("http", "https") and parsed.hostname and not parsed.username and not parsed.password
            _ = parsed.port
        except ValueError:
            valid = False
        if not valid or any(char.isspace() for char in value):
            raise ValueError("Use a valid http or https forum URL without credentials.")
        return value

    @field_validator("message")
    @classmethod
    def validate_message(cls, value):
        if not value.strip():
            raise ValueError("A reply message is required.")
        return value


class ConfigModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(max_length=200)
    password: str | None = Field(default=None, max_length=1000)
    interval: int = Field(strict=True, ge=1, le=1440)
    threads: list[ThreadModel] = Field(max_length=100)


class ConfigStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self):
        if not self.path.exists():
            return {"username": "", "password": "", "interval": 31, "threads": []}
        try:
            config = ConfigModel.model_validate_json(self.path.read_text(encoding="utf-8"))
            return config.model_dump()
        except (OSError, ValueError):
            raise HTTPException(500, "Settings could not be read. Check config.json before saving.") from None

    @staticmethod
    def public(config):
        return {k: v for k, v in config.items() if k != "password"} | {"password_set": bool(config.get("password"))}

    def save(self, config):
        previous = self.load()
        data = config.model_dump()
        if not data.get("password"):
            data["password"] = previous.get("password") or ""
        temp_path = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=self.path.parent, delete=False) as target:
                temp_path = Path(target.name)
                json.dump(data, target, indent=2, ensure_ascii=False)
                target.flush()
                os.fsync(target.fileno())
            os.replace(temp_path, self.path)
        except OSError:
            raise HTTPException(500, "Settings could not be saved. The previous file is unchanged.") from None
        finally:
            if temp_path and temp_path.exists():
                with suppress(OSError):
                    temp_path.unlink()
        return data


class BotRuntime:
    def __init__(self, store, events, worker, demo=False):
        self.store, self.events, self.worker, self.demo = store, events, worker, demo
        self.state = "Offline"
        self.status_version = 0
        self.server_id = uuid.uuid4().hex
        self.run_id = None
        self.task = None
        self.stop_event = threading.Event()
        self.loop = None
        self.shutting_down = False
        self.shutdown_timeout = 10
        self.events.on_persistence_change = self.refresh_status

    def refresh_status(self):
        def update():
            self.status_version += 1
            self.events.publish({"type": "status", **self.snapshot()})
        if self.loop and not self.loop.is_closed():
            with suppress(RuntimeError):
                self.loop.call_soon_threadsafe(update)

    def snapshot(self):
        return {"state": self.state, "status": self.state, "is_running": self.task is not None,
                "status_version": self.status_version, "server_id": self.server_id,
                "run_id": self.run_id, "demo": self.demo, "log_persistence_ok": self.events.persistence_ok}

    def set_state(self, state):
        self.state = state
        self.status_version += 1
        self.events.publish({"type": "status", **self.snapshot()})

    def emit(self, level, kind, message, **context):
        return self.events.emit(level, kind, message, run_id=self.run_id, **context)

    def active(self):
        def update():
            if self.state == "Starting" and not self.stop_event.is_set():
                self.set_state("Active")
        self.loop.call_soon_threadsafe(update)

    async def start(self):
        if self.shutting_down or self.task is not None:
            raise HTTPException(409, "A run is still starting, active, or stopping.")
        config = self.store.load()
        if not config["username"].strip() or not config.get("password") or not config["threads"]:
            raise HTTPException(400, "Save a username, password, and at least one thread before starting.")
        self.events.set_secrets(config)
        self.stop_event = threading.Event()
        self.run_id = uuid.uuid4().hex
        self.task = asyncio.create_task(self._run(config))
        self.set_state("Starting")
        self.emit("INFO", "run.starting", "Run starting. Waiting for browser and login verification.")
        return self.snapshot()

    async def stop(self):
        if self.task is None:
            raise HTTPException(409, "There is no running task to stop.")
        if not self.stop_event.is_set():
            self.stop_event.set()
            self.set_state("Stopping")
            self.emit("INFO", "run.stop_requested", "Stop requested. Waiting for the browser worker to finish cleanup.")
        return self.snapshot()

    async def _run(self, config):
        # A daemon thread cannot prevent API shutdown forever if a driver call hangs.
        # Its completion remains tracked; cancellation never permits a second worker.
        finished = self.loop.create_future()

        def complete(result):
            if not finished.done():
                finished.set_result(result)

        def execute():
            try:
                result = self.worker(self, config)
            except Exception:
                self.emit("ERROR", "run.worker_failed", "Browser worker failed. Check browser availability and saved settings.")
                result = "failed"
            if not self.loop.is_closed():
                with suppress(RuntimeError):
                    self.loop.call_soon_threadsafe(complete, result)

        threading.Thread(target=execute, name="autobumper-worker", daemon=True).start()
        try:
            while True:
                try:
                    result = await asyncio.shield(finished)
                    break
                except asyncio.CancelledError:
                    self.stop_event.set()
                    if self.shutting_down:
                        self.state = "Error"
                        self.emit("WARNING", "shutdown.pending", "Server shutdown timed out waiting for browser cleanup. Close the owned browser if necessary.")
                        return
                    self.set_state("Stopping")
            if result == "stopped" and self.stop_event.is_set():
                self.state = "Offline"
                self.emit("INFO", "run.stopped", "Browser worker finished. Run stopped.")
            else:
                self.state = "Error"
                self.emit("ERROR", "run.failed", "Run ended without a clean requested stop. Review the preceding activity.")
        finally:
            self.task = None
            self.status_version += 1
            self.events.publish({"type": "status", **self.snapshot()})


def browser_worker(runtime, config):
    """Cooperative driver worker; no page dumps, screenshots or protection bypasses."""
    try:
        from botasaurus.browser import browser
    except ImportError:
        runtime.emit("ERROR", "browser.dependencies_missing", "Browser dependencies are unavailable. Install requirements-bot.txt.")
        return "failed"

    @browser(create_error_logs=False, close_on_crash=True, headless=False)
    def task(driver, data):
        try:
            return run_browser_session(driver, runtime, config)
        except Exception:
            runtime.emit("ERROR", "browser.failed", "Browser operation failed. No successful post has been confirmed.")
            return "failed"

    return task()


LOGIN_WAIT_SECONDS = 90
LOGIN_FORM_SCRIPT = """
    const visible = el => el && !el.disabled && el.getClientRects().length > 0
        && getComputedStyle(el).visibility !== 'hidden';
    const login = Array.from(document.forms).map(form => {
        const user = Array.from(form.querySelectorAll("input[name='username'], input[placeholder*='Username']"))
            .find(el => el.form === form && visible(el));
        const pass = Array.from(form.querySelectorAll("input[name='password'], input[type='password']"))
            .find(el => el.form === form && visible(el));
        const submit = Array.from(form.querySelectorAll('button, input'))
            .find(el => el.form === form && ['submit', 'image'].includes(el.type) && visible(el));
        return {form, user, pass, submit};
    }).find(candidate => candidate.user && candidate.pass);
"""


def authenticated(driver):
    try:
        return bool(driver.select("a[href*='action=logout']", wait=0))
    except Exception:
        # The document may be transitioning after a submit or manual verification.
        return False


def login_browser_session(driver, runtime, config):
    """Authenticate without entering the posting loop; access checks remain manual."""
    stop = runtime.stop_event
    emit = runtime.emit
    if stop.is_set():
        return "stopped"
    driver.get("https://oguser.com/login")
    emit("INFO", "login.waiting", "Waiting for login controls. Access challenges require manual resolution.")
    ready = False
    for _ in range(LOGIN_WAIT_SECONDS):
        if stop.is_set():
            return "stopped"
        if authenticated(driver):
            emit("INFO", "login.verified", "Authenticated session verified by the logout control.")
            return "authenticated"
        try:
            ready = driver.run_js(LOGIN_FORM_SCRIPT + "return Boolean(login);")
            if ready:
                break
        except Exception:
            pass
        if stop.wait(1):
            return "stopped"
    if not ready:
        emit("ERROR", "login.controls_missing", "A visible login form did not become available within 90 seconds.")
        return "failed"
    if stop.is_set():
        return "stopped"
    # JSON literals preserve quotes/newlines without allowing script injection.
    values = json.dumps([config["username"], config["password"]])
    marker = uuid.uuid4().hex
    try:
        inserted = driver.run_js("const credentials = " + values + ";\n" + LOGIN_FORM_SCRIPT + """
            if (!login) return 'controls_missing';
            if (!login.submit) return 'submit_missing';
            login.user.value = credentials[0]; login.pass.value = credentials[1];
            [login.user, login.pass].forEach(el => {
                el.dispatchEvent(new Event('input', {bubbles:true}));
                el.dispatchEvent(new Event('change', {bubbles:true}));
            });
            login.submit.setAttribute('data-autobumper-login-submit', """ + json.dumps(marker) + """);
            return 'filled';
        """)
    except Exception:
        inserted = "controls_missing"
    if inserted == "submit_missing":
        emit("ERROR", "login.submit_missing", "No submit control was found inside the visible login form.")
        return "failed"
    if inserted != "filled":
        emit("ERROR", "login.fill_failed", "Login controls could not be filled.")
        return "failed"
    if stop.is_set():
        return "stopped"
    try:
        submit = driver.select(f'[data-autobumper-login-submit="{marker}"]', wait=0)
        if not submit:
            emit("ERROR", "login.submit_missing", "The login form's submit control became unavailable.")
            return "failed"
        submit.click()
    except Exception:
        emit("ERROR", "login.submit_failed", "The login form could not be submitted. Check the open browser.")
        return "failed"
    emit("INFO", "login.submitted", "Login form submitted. Complete any two-factor or access check in the open browser.")
    for _ in range(LOGIN_WAIT_SECONDS):
        if stop.is_set():
            return "stopped"
        if authenticated(driver):
            emit("INFO", "login.verified", "Authenticated session verified by the logout control.")
            return "authenticated"
        if stop.wait(1):
            return "stopped"
    emit("ERROR", "login.unverified", "Login was not verified within 90 seconds. Check account details and complete any two-factor or access check. No replies were attempted.")
    return "failed"


def run_browser_session(driver, runtime, config):
    result = login_browser_session(driver, runtime, config)
    if result != "authenticated":
        return result
    stop = runtime.stop_event
    emit = runtime.emit
    runtime.active()
    while not stop.is_set():
        live = runtime.store.load()
        runtime.events.set_secrets(live)
        for index, thread in enumerate(live["threads"], start=1):
            if stop.is_set():
                return "stopped"
            emit("INFO", "thread.opening", f"Opening thread {index}.", thread_index=index)
            try:
                driver.get(thread["url"])
                if stop.wait(4):
                    return "stopped"
                reply = driver.select("a[href*='newreply.php']")
                if reply:
                    reply.click()
                    if stop.wait(4):
                        return "stopped"
                message = json.dumps(thread["message"])
                filled = driver.run_js(f"""
                    const box = document.querySelector("#message, textarea[name='message']");
                    if (!box) return false;
                    const value = {message};
                    if (window.jQuery) {{
                        try {{ const editor = window.jQuery(box).sceditor('instance'); if (editor) editor.val(value); }} catch(e) {{}}
                    }}
                    box.value = value;
                    box.dispatchEvent(new Event('input', {{bubbles:true}}));
                    box.dispatchEvent(new Event('change', {{bubbles:true}}));
                    return box.value === value;
                """)
                if not filled:
                    emit("ERROR", "reply.editor_missing", f"Thread {index}: reply editor was unavailable or could not be filled.", thread_index=index)
                    continue
                if stop.is_set():
                    return "stopped"
                buttons = driver.select_all("input[name='submit'], input[value*='Post Reply']")
                if not buttons:
                    emit("ERROR", "reply.control_missing", f"Thread {index}: no Post Reply control was found.", thread_index=index)
                    continue
                buttons[0].click()
                emit("WARNING", "reply.submitted_unconfirmed", f"Thread {index}: reply submitted; publication has not been confirmed.", thread_index=index)
            except Exception:
                emit("ERROR", "reply.failed", f"Thread {index}: reply attempt failed; no publication confirmed.", thread_index=index)
            if stop.wait(10):
                return "stopped"
        emit("INFO", "cycle.waiting", f"Cycle finished. Waiting {live['interval']} minutes before the next cycle.")
        if stop.wait(live["interval"] * 60):
            return "stopped"
    return "stopped"


def create_app(config_path=None, log_dir=None, worker=None, demo=False):
    store = ConfigStore(config_path or ROOT / "config.json")
    events = ActivityLog(log_dir or ROOT / "logs")
    try:
        events.set_secrets(store.load())
    except HTTPException:
        pass
    events.restore()
    runtime = BotRuntime(store, events, worker or browser_worker, demo)

    @asynccontextmanager
    async def lifespan(app):
        runtime.loop = asyncio.get_running_loop()
        events.attach(runtime.loop)
        events.emit("INFO", "server.started", "DEMO server ready. All activity is simulated." if demo else "Local control server ready.")
        yield
        runtime.shutting_down = True
        if runtime.task:
            closing_task = runtime.task
            await runtime.stop()
            try:
                await asyncio.wait_for(asyncio.shield(closing_task), timeout=runtime.shutdown_timeout)
            except asyncio.TimeoutError:
                closing_task.cancel()
                await closing_task

    app = FastAPI(lifespan=lifespan)
    app.state.runtime = runtime
    app.state.store = store
    app.state.events = events
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request: Request, error):
        # Pydantic's default response echoes input values, including passwords.
        return JSONResponse(status_code=422, content={"detail": "Settings are invalid. Check interval (1–1440), forum URLs, and nonempty messages (up to 10,000 characters)."})

    @app.get("/api/config")
    async def get_config():
        return store.public(store.load())

    @app.post("/api/config")
    async def post_config(config: ConfigModel):
        data = store.save(config)
        events.set_secrets(data)
        events.emit("INFO", "config.saved", "Settings saved. New settings apply at the next cycle; credentials apply on the next run.")
        return {"status": "success", "config": store.public(data)}

    @app.get("/api/status")
    async def status():
        return runtime.snapshot()

    @app.post("/api/start")
    async def start():
        return await runtime.start()

    @app.post("/api/stop")
    async def stop_run():
        return await runtime.stop()

    @app.websocket("/ws")
    @app.websocket("/api/ws")
    async def websocket_endpoint(ws: WebSocket):
        origin = ws.headers.get("origin")
        allowed = {"http://localhost:5173", "http://127.0.0.1:5173", f"http://{ws.headers.get('host')}", f"https://{ws.headers.get('host')}"}
        if origin and origin not in allowed:
            await ws.close(code=1008)
            return
        await ws.accept()
        queue = asyncio.Queue(maxsize=128)
        # No await between subscription and snapshot: events cannot fall into a gap.
        events.clients.add(queue)
        initial = [{"type": "status", **runtime.snapshot()}, {"type": "history", "events": events.history()}]

        async def send():
            for payload in initial:
                await asyncio.wait_for(ws.send_json(payload), 3)
            while True:
                payload = await queue.get()
                if payload is None:
                    await ws.close(code=1013)
                    return
                await asyncio.wait_for(ws.send_json(payload), 3)

        async def receive():
            while True:
                await ws.receive_text()

        tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (WebSocketDisconnect, RuntimeError, OSError, asyncio.TimeoutError, asyncio.CancelledError):
            pass
        finally:
            events.clients.discard(queue)
            for task in tasks:
                task.cancel()
            with suppress(asyncio.CancelledError):
                await asyncio.gather(*tasks, return_exceptions=True)

    build = ROOT / "frontend" / "dist"
    if build.exists():
        app.mount("/", StaticFiles(directory=build, html=True), name="frontend")
    else:
        @app.get("/")
        async def fallback():
            return {"message": "Build frontend with npm ci and npm run build in frontend/."}
    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
