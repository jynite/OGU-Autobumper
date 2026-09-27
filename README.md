# OGU Autobumper

Run scheduled replies to your OGU threads from a local dashboard. Add your account, thread URLs, and messages, then choose when to start.

The dashboard opens at **http://127.0.0.1:8000**. Opening it doesn't start posting.

## Setup

You'll need Python 3.10+, Node.js 22.12+ with npm, and Google Chrome. Python and npm must be available in your terminal.

On Windows, open **run.bat**. It installs the dependencies, builds the frontend, and starts the server. Keep that terminal open while using the app.

Or run these commands from the project folder:

```powershell
python -m pip install -r requirements-bot.txt
cd frontend
npm ci
npm run build
cd ..
python autobumper_linux.py
```

## Use it

1. Open **Settings** and enter your OGU username and password. Leave the password blank to keep an existing saved password.
2. Set the interval to 1–1,440 whole minutes. This is the wait between completed cycles.
3. Open **Threads**, choose **Add thread**, and enter its URL and reply message.
4. Choose **Save**, then **Start**. Threads run in the order shown, once per cycle.
5. Choose **Stop** to end the run. Wait for **Idle**, then press **Ctrl+C** in the terminal to close the server.

Start is disabled while changes are unsaved or required settings are missing. You can save up to 100 threads, with messages up to 10,000 characters each. Switching tabs keeps unsaved changes.

Saved threads and intervals take effect next cycle. Stop and start again to use new account details.

Login uses the visible account form. If OGU asks for a two-factor code or an access check, complete it in the Chrome window the bot opens. It waits up to 90 seconds for login confirmation before attempting any replies. **Stop** also works during this wait.

A submit click is logged as **publication unconfirmed**. Check the forum to confirm the reply appeared. Stop can stay pending while a browser action finishes; server shutdown waits up to 10 seconds. If cleanup times out, close that run's browser window before restarting.

## What's stored on your PC

**Your login details and settings are saved locally in `config.json` in this project folder. The password is plaintext, not encrypted.** The file also contains your username, thread URLs, reply messages, and interval. Keep it private. [config.example.json](config.example.json) shows the format.

The local API sends the dashboard a saved-password indicator instead of returning the stored password. `config.json` and the `logs/` folder are excluded from Git by [.gitignore](.gitignore).

Activity is saved locally in `logs/activity.jsonl`, with three rotating backups at roughly 1 MB each. Known credentials, configured reply text, and URLs are redacted from events. The app doesn't save automatic page dumps or screenshots.

Chrome uses a temporary profile under your system's temp folder in `bota/`. It can contain session cookies and cache. The browser library tries to remove it on close; crashes or failed cleanup can leave files behind. It can also write the run's result, such as `stopped` or `failed`, to `output/task.json`. That folder is excluded from Git too.

There is no hosted dashboard service. The server listens on your PC at `127.0.0.1`. **A live run still sends your credentials to OGU to log in and sends your saved messages to the thread URLs you entered.** Local storage doesn't mean the bot works offline.

This is open source, so you can check those claims yourself: [autobumper_linux.py](autobumper_linux.py) handles saving, password responses, and browser requests; [activity.py](activity.py) handles redaction and log files.

## Activity

CMD shows run events. **Activity** stays collapsed on the Threads page, with event and error counts visible. Open it to search, filter, copy, or export events. You don't need to keep a live feed open.

- Up to 500 recent events return after reloading or reconnecting.
- **Copy** and **Export** use the filtered results.
- Scrolling up pauses following; **Follow latest** resumes it.
- **Clear view** clears this page only. Reload to restore saved history.

The same redacted events go to CMD, the dashboard, and disk. A stalled terminal can skip console lines without blocking the other logs. If disk writing fails, the dashboard warns you and keeps events in memory.

## Troubleshooting

| Problem | Check |
| --- | --- |
| `python` or `npm` isn't found | Install it, check PATH, and reopen the terminal. |
| Setup fails | Read the first error in the terminal; try the matching setup command above. |
| Dashboard won't open | Keep the server running and open `http://127.0.0.1:8000`. |
| Start is disabled | Save an account with a password and at least one thread; wait for the server connection. |
| Settings won't load | Fix malformed `config.json`, then choose **Retry**. Invalid files aren't overwritten. |
| Login or reply fails | Check CMD or Activity. Forum controls may have changed; resolve access challenges manually. |
| Logs won't save | Check free space and write access to the project folder. |

## Offline demo and development

The demo uses temporary settings and a simulated worker. It doesn't contact OGU or need Chrome. Stop any existing server, install the development dependencies, build the frontend using the steps above, then run:

```powershell
python -m pip install -r requirements-dev.txt
python scripts/demo_server.py
```

Open the local dashboard and look for **Demo**. Ctrl+C removes its temporary settings and logs.

For frontend development, keep the API or demo running and use `npm run dev` inside `frontend/`. Vite proxies `/api` to port 8000.

Checks:

```powershell
python -m unittest discover -s tests -v
cd frontend
npm run lint
npm run build
```

Tests use temporary files and simulated workers. They don't verify live forum login or published replies. See [frontend/README.md](frontend/README.md) for UI behavior and [FRONTEND_MAKEOVER.md](FRONTEND_MAKEOVER.md) for design and verification notes.

The optional login-form regression uses local Chrome and a fixture with search and hidden login forms. Install `playwright`, set `OGU_BROWSER_TESTS=1`, then run the tests above to include it. It uses dummy credentials and doesn't contact OGU.

## Credits

Made by [/hyperpop](https://oguser.com/member.php?action=profile&uid=435047).

Penderdrill made the original premise before he quit. I chose to keep it going and maintain it myself.

[Show support if you want](https://oguser.com/member.php?action=profile&uid=435047).
