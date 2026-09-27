# Frontend makeover

Updated 2026-09-26. The sidebar has three tabs: Threads, Settings, and Credits. Threads contains the run controls, flat editable rows, and collapsed Activity. Account and interval settings have their own page.

The interface uses Segoe UI on Windows with system fallbacks, a neutral gray palette, and rectangular controls. Thread rows have no card background or rounded border. URL and message fields sit side by side on wide screens and stack at 1,000px and below. Mobile navigation uses visible text tabs. Remove, Save, Start, Stop, and activity actions use text labels. Color is reserved for run states and feedback.

The editable [Figma file](https://www.figma.com/design/axpJ0YsZQHycgvZXlrTZLp) keeps the same six desktop/mobile frames, reusable form controls, shared colors, and navigation links. It uses Arimo/Cousine because the remote font inventory lacks Segoe UI/Consolas. Imported controls retain their 40px input and 80px textarea minimums; the app uses smaller desktop fields. Figma is an editable reference, with these differences recorded here.

## Behavior

Tabs and browser history preserve unsaved edits. Save validates both account and thread fields across tabs. Start requires saved credentials and at least one thread. A blank password preserves the saved value. Mobile tab changes return to the top so navigation stays visible; the keyboard skip link focuses the workspace without changing tabs.

Activity starts collapsed with event and error counts. Expanded history keeps search, severity filters, copying, JSON export, clearing, and following within a 280px viewport. Events also appear in CMD. A bounded background console sink prevents a stalled terminal from blocking disk or dashboard delivery. Disk failures and recovery update the warning independently of run state.

Credits contains the requested /hyperpop link, Penderdrill acknowledgment, and optional support link. The README now uses the actual UI labels and explains local plaintext credentials, configuration, rotated logs, temporary Chrome profiles, and browser-library result files. It links directly to the source and distinguishes local storage from live requests to OGU.

## Verification

The utility pass reran all 22 backend tests, lint, and the production build. Browser checks covered the changed row controls, saving and browser history, all four run states, mobile Activity, credit links, and widths from 320px to 1440px. Unchanged validation and export behavior retain the earlier checks and limits listed below.

| Check | Result |
| --- | --- |
| Backend | All 22 simulated tests pass, including password responses, redaction, persistence failures, lifecycle races, and stalled console output. |
| Frontend | Lint and production build pass. |
| Navigation | Settings, Credits, browser back, unsaved interval preservation, and keyboard skip checked in the disposable demo. Mobile route changes leave navigation at the top. |
| Editing | Explicit save, missing username, invalid interval, invalid thread URL from Settings, add/remove, empty list, and disabled Start while dirty checked. |
| Run controls | Demo displayed Starting, Running, Stopping, and Idle; Start/Stop availability matched each state. |
| Activity | Collapse/expand, visible error count, ERROR filter, and wrapping checked in the utility pass. Copy reports success, but the browser clipboard bridge did not return the expected text in this repeat check. Copy and export functions are unchanged from earlier checks; the earlier repeat export observer timed out. |
| Responsive layout | Utility layout inspected at 1440px desktop and 390px mobile, with additional width checks at 320px and 900px. Document scroll width does not exceed client width, including expanded mobile history. |
| Figma | Same six screens updated to flat rows, neutral colors and text navigation. Visual inspection caught mobile URL wrapping and tab alignment; fixed with single-line truncation and selected-tab underlines. Font and imported-control limits are disclosed above. |
| README storage claims | Config/API/log behavior checked against project source; temporary profiles and result output checked against the installed browser dependency. |
| Config integrity | Original config hash remains unchanged. Browser edits used temporary demo settings. |
| Browser console | No errors in the desktop demo check. |

These checks cover local UI and API behavior. Live forum authentication, current selectors, publication, and Chrome cleanup during a real run remain unverified. Screenshots contain simulated settings and events. No real posting or deployment occurred.
