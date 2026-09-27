"""Disposable offline fixture. Never imports or invokes a browser driver."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autobumper_linux import create_app
import uvicorn


def demo_worker(runtime, config):
    runtime.emit("INFO", "demo.starting", "DEMO: simulating browser startup. No website is contacted.")
    if runtime.stop_event.wait(2):
        return "stopped"
    runtime.active()
    runtime.emit("INFO", "demo.active", "DEMO: simulated session active. Nothing is posted.")
    runtime.emit("WARNING", "demo.unconfirmed", "DEMO thread 1: simulated reply submitted; publication is unconfirmed.", thread_index=1)
    runtime.emit("ERROR", "demo.editor_missing", "DEMO thread 2: simulated reply editor missing. This example error demonstrates filters and readable wrapping on narrow screens; no real reply was attempted.", thread_index=2)
    while not runtime.stop_event.wait(4):
        runtime.emit("INFO", "demo.heartbeat", "DEMO: simulated worker waiting for the next cycle.")
    runtime.emit("INFO", "demo.cleanup", "DEMO: simulated browser cleanup in progress.")
    import time
    time.sleep(1)
    return "stopped"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    options = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="ogu-demo-") as directory:
        root = Path(directory)
        config = root / "config.json"
        config.write_text(json.dumps({"username": "example-account", "password": "demo-only-password",
            "interval": 31, "threads": [{"url": "https://example.com/forum/thread/one", "message": "Example reply for the offline demo."},
                                        {"url": "https://example.com/forum/thread/two", "message": "Another example reply."}]}), encoding="utf-8")
        app = create_app(config, root / "logs", worker=demo_worker, demo=True)
        print("DEMO ONLY: temporary settings, simulated events, no website calls.", flush=True)
        uvicorn.run(app, host="127.0.0.1", port=options.port)


if __name__ == "__main__":
    main()
