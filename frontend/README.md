# OGU Autobumper frontend

The sidebar has three tabs: Threads, Settings, and Credits. Threads holds the run controls and reply forms. Settings holds the account and interval. Tabs and browser back preserve unsaved changes. Each tab also has a direct link.

Start requires saved credentials and at least one thread. A blank password keeps the existing saved value. Account changes apply after restarting; saved thread and interval changes apply next cycle.

Activity starts collapsed with event and error counts. Expand it to search, filter by level, copy, export, or clear the page's events. Scrolling up pauses following within the 280px log viewport. New events don't scroll the page.

The frontend uses system fonts, neutral controls, and flat thread rows. Desktop puts the URL and message side by side; smaller windows stack them. Mobile navigation spells out each tab. Activity stays collapsed until opened. The editable [Figma file](https://www.figma.com/design/axpJ0YsZQHycgvZXlrTZLp) contains desktop and mobile versions of all three tabs.

## Development

Start the Python API or offline demo on port 8000, then run:

```sh
npm ci
npm run dev
```

Vite proxies `/api` and its WebSocket to `http://127.0.0.1:8000`. `npm run lint` checks the source; `npm run build` creates the files FastAPI serves from `dist`.

See the [project README](../README.md) for setup, local credential storage, logs, and troubleshooting.
