# OGU Autobumper improvement review

Reviewed 2026-09-26, with an independent check of the findings. This review describes the initial checkout, before the controls/logging implementation and dashboard makeover.

## Highest priorities

| Priority | Observed problem | User impact | Recommended improvement |
| --- | --- | --- | --- |
| P1 | Only compiled frontend assets exist; `frontend/src` is missing. A fresh build fails resolving `/src/main.jsx`. | The dashboard cannot be maintained or reproduced. | Restore authored React source and make build/lint repeatable. |
| P1 | Backend never enters `Active`, ends as `Stopped`, and does not reliably clear its running flag. Frontend only starts `Offline`/`Error` and stops `Active`. | Start/Stop gets stuck; a quick restart can overlap a worker that is still exiting. | One shared lifecycle, stop during startup, guarded start, cleanup in `finally`, and honest failure states. |
| P1 | Most worker activity uses `print` rather than WebSocket events. No history, event timestamps, severity, or persistent logs. | The dashboard misses the activity needed to understand a failure. Refresh loses the evidence. | One structured event stream, bounded replay, rotating local JSONL files, safe thread-to-async delivery. |
| P1 | Log timestamps are created while rendering each row. | Old entries change time when a new entry appears. | Capture event time once on the server and render that timestamp. |
| P1 | Config/save/start/stop ignore request errors; config-load failure leaves editable empty defaults. | The UI can falsely show a saved/running state or overwrite saved settings after a failed load. | Explicit save with inline validation, pending/success/error feedback, and settings disabled until loaded. |
| P1 | `GET /api/config` returns the saved password; server listens on all interfaces. | Credentials are unnecessarily exposed through an otherwise local control API. | Write-only password updates, a `password_set` indicator, loopback by default, restricted development origins. |
| P1 | “Bump successful” is printed even if no submit button exists or no click succeeds. | Users are told a post succeeded without evidence. | Distinguish failed submission, submitted/unconfirmed, and independently confirmed posting. |
| P2 | API/WS URLs hardcode localhost; WS cleanup schedules more reconnects. | The dashboard breaks on another port and can accumulate connections. | Same-origin URLs, a Vite proxy, and cancellable reconnect with visible connection status. |
| P2 | The header control clips outside the page at a narrow viewport. Form labels are not associated with controls; icon buttons are unnamed. | Mobile operation and keyboard/assistive navigation suffer. | Wrapping controls, responsive layout, proper labels and visible focus. |
| P2 | Interval, URL, and message inputs lack constraints; strings are interpolated into JavaScript. | Invalid schedules and ordinary quotes/newlines can break the worker. | Shared validation and JSON-encoded text insertion. |
| P2 | Full page HTML and screenshots are captured automatically. | Sensitive page content can accumulate in the app folder. | Disable automatic raw diagnostics and plan deliberate, bounded diagnostic capture separately. |
| P2 | README describes source-edited credentials; `kill.bat` kills every Python process. | Setup instructions are inaccurate and cleanup can stop unrelated tools. | Current setup/operation documentation; exclude the broad kill script from the supported workflow. |

Backend evidence in the original `autobumper_linux.py`: config models 57–65; logging/status 80–103; browser output/diagnostics 123–195; message insertion 229–256; unconditional success 260–287; lifecycle 310–324; config API 328–337; start/stop 343–369; WebSocket 371–386; public bind 400. The compiled dashboard's `qE` component provided the frontend behavior evidence. A local static browser inspection confirmed the narrow header overflow.

## Phase 1: reliable controls and activity

The first phase groups the dependencies needed for a usable UI and logging system:

- Restore frontend source and reproducible build/lint.
- Improve responsive layout, accessible controls, explicit save and request feedback.
- Implement coherent run states and safe start/stop behavior.
- Add server-timestamped activity, history replay, severity/search filters, and bounded persistent logs.
- Preserve existing config and credentials while removing password reads from the API.
- Validate config, save atomically, encode inserted text safely, and disable automatic raw diagnostics.
- Add local mocked verification and a separate demo for browser acceptance.

See [PHASE1.md](PHASE1.md) for implemented scope and verification evidence. No real forum login or post is part of this phase's acceptance checks.

## Subsequent improvements

These remain useful after the core controls and logging are reliable:

1. **Confirm actual forum outcomes.** Establish robust authentication and post-confirmation evidence on the real service, including failure/unknown outcomes and duplicate prevention. Clicking is not confirmation.
2. **OS credential storage.** Migrate saved passwords to an operating-system credential vault, with explicit migration and recovery behavior.
3. **Per-thread operation.** Add thread editing, individual enable/pause, last result, scheduling and cooldown controls, then retry/backoff policies that respect service limits.
4. **Run summaries and diagnostic bundles.** Count confirmed/submitted/failed/unknown outcomes per run, expose next-run timing, and create intentional redacted diagnostic exports.
5. **Lifecycle isolation.** If real driver shutdown remains unreliable, move the worker into a managed child process so termination can be bounded without killing unrelated Python/Chrome processes.

Independent review clarified that the original config labels were visible but weren't associated with inputs. Usernames can remain editable in the local settings form. Submitting a reply must remain explicitly unconfirmed until the service provides verifiable evidence; omitted password updates must preserve the saved value.
