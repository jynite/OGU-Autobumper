# Phase 1: reliable controls and activity

Status: complete for the local UI, API and logging contract on 2026-09-26. Real forum acceptance remains unverified.

An initial audit and independent verification guided this implementation. [IMPROVEMENTS.md](IMPROVEMENTS.md) contains the ranked review. This record describes the first release of the controls and logging changes; [FRONTEND_MAKEOVER.md](FRONTEND_MAKEOVER.md) covers the subsequent dashboard redesign.

## Acceptance contract

- Authored frontend source; reproducible production build and lint.
- Responsive controls and accessible forms; explicit save, pending and API failure feedback.
- Same-origin API/WebSocket connections and visible reconnect state.
- One lifecycle with guarded starts, stop during startup and cleanup after completion/failure.
- Timestamped structured activity with severity/search filtering, bounded history replay and rotating local files.
- Write-only password updates preserving an existing password when omitted; atomic validated configuration writes.
- Honest submission outcomes; automatic raw HTML/screenshot diagnostics disabled.
- Local mocked regression tests and actual browser checks against a separate no-network demo.

## Implemented result

The restored React dashboard has editable thread rows, explicit saves, a saved-password indicator, responsive process controls, connection feedback, and a searchable activity panel. Copy/export operate on visible filtered events. Clear removes the current page view; subsequent events continue appearing and reload restores retained server history. Event times remain stable.

The backend uses one guarded lifecycle, monotonic status revisions, safe worker-to-async delivery, per-client queues, 500-event replay and rotated JSONL files. Config updates validate before atomic replacement; password reads are omitted and blank/omitted password updates preserve the saved value. Existing config was validated and its SHA256 remained identical to the initial checkout after all tests.

Logs rotate at approximately 1 MB with three backups (about 4 MB total). Restored events retain run/thread context. Operational messages omit raw URLs, configured secrets/messages and raw exception text. A disk failure reports a live warning while retaining in-memory events. Automatic raw HTML and screenshot diagnostics are disabled. Missing controls and failed clicks are errors; a click that works is an explicitly unconfirmed submission.

Independent review found and verified repairs for shutdown cancellation, credential serialization, restored event context, React StrictMode event/config races, view clearing, status-response ordering, WebSocket development proxy and following events at the 500-row limit. The static/mocked contract passed review; separate browser checks covered the rendered app.

## Verification evidence

| Check | Acceptance evidence |
| --- | --- |
| Build and lint | `npm run lint` and `npm run build` pass on the final source; Vite transforms 29 modules. |
| Backend regression suite | `python -m unittest discover -s tests -v`: 18 passed. Includes config privacy/atomicity, corrupt and failed saves, startup stop/restart exclusion, fatal/login failures, cancellation/shutdown, replay/rotation/redaction/backpressure and submission honesty. |
| Password preservation and config integrity | Tests cover blank and omitted preservation, error responses without echoed secrets; the user's original file remains byte-for-byte unchanged. |
| Fresh UI/config loading | Browser loads the disposable demo with two editable example threads and saved-password indicator. Independent review verified initial-load sequencing and disabled edits until success. |
| Explicit save and invalid input feedback | Interval 0 rejected with native validation; interval 32 explicitly saved in the demo; dirty settings prevent Start. |
| Start, startup stop, restart, failure | Browser immediately starts/stops before simulated activation, returns Offline and can restart. Active stop shows Stopping until cleanup. With the demo server unavailable, failed Start shows an error and stays Offline. |
| Fixed event timestamps and severity/search filters | Existing timestamp strings stay unchanged as new events arrive and after reload. ERROR/ WARNING filters and combined text search select the expected rows; filtered-empty feedback names the filter state. |
| Copy and export | Browser reports Copy success. Exported JSON was read back: one filtered WARNING event with timestamp/run/thread context, no password field. In-app download-event waiting did not fire, but the actual saved file was verified. |
| Clear and replay | Clear empties the view; stop/cleanup events appear afterwards. Reload replays 33 retained events, including the original timestamp strings. |
| Reconnect | Stopping/restarting the disposable server shows Reconnecting then Live link; final source prevents old HTTP responses overwriting newer WebSocket status. |
| Narrow and desktop layout, labels/focus | Tested 382px and 1280px viewport overrides. Document scroll width equals client width (367px and 1265px with scrollbars), including the long error row. Labels/buttons have accessible names; add/remove and pause-follow controls work. |
| Independent review | PASS after all identified blockers were repaired; build/lint and 18 backend tests independently rerun. |

Screenshots show the offline demo with simulated warning/error events:

- [Desktop screenshot](C:/Users/sajit/.codex/visualizations/2026/09/26/01a0df33-0357-7c00-beb5-4146a2bc555d/ogu-phase1-desktop.png)
- [Mobile screenshot](C:/Users/sajit/.codex/visualizations/2026/09/26/01a0df33-0357-7c00-beb5-4146a2bc555d/ogu-phase1-mobile.png)

## Proof boundaries

Acceptance is local. Tests must not log in to the real service, post replies, or launch a real forum worker. The user's existing `config.json` must remain unchanged by verification. Clicking a submit button is an unconfirmed submission, never proof of a posted reply.

OS-backed credential storage, advanced per-thread scheduling and real forum acceptance are subsequent improvements. The local config still stores its password as plaintext. Browser-library navigation may block: ordinary Stop remains pending until that call returns, and server shutdown stops waiting after 10 seconds. Closing that run's browser may be necessary; a process-isolated worker is later work. See [IMPROVEMENTS.md](IMPROVEMENTS.md) for the remaining priorities.

## Preservation and handoff

The initial checkout had a modified README and untracked app/frontend/launchers, config, diagnostic HTML and `.serena`. Original application/README/launchers and compiled dashboard were backed up locally under `.codex/phase1-baseline`; credentials and captured HTML were not copied into that backup. Private/runtime files are ignored. Existing `kill.bat` is unchanged and outside the phase commit; supported instructions use Stop and Ctrl+C.

The local branch is `codex/ogu-ui-logging-phase1`. No push, publication, real login or forum posting occurred. Demo/test processes are stopped after acceptance; `run.bat` or `python scripts/demo_server.py` can start the selected local workflow again.
