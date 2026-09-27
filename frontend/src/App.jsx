import { useCallback, useEffect, useMemo, useRef, useState } from 'react'

const DEFAULT_CONFIG = { username: '', password_set: false, interval: 31, threads: [] }
const LEVELS = ['ALL', 'INFO', 'WARNING', 'ERROR', 'DEBUG']

function normalizeConfig(value = {}) {
  return {
    username: value.username ?? '',
    password_set: Boolean(value.password_set),
    interval: Number(value.interval ?? 31),
    threads: Array.isArray(value.threads)
      ? value.threads.map((thread) => ({ url: thread.url ?? '', message: thread.message ?? '' }))
      : [],
  }
}

function configSignature(value) {
  return JSON.stringify({
    username: value.username,
    interval: Number(value.interval),
    threads: value.threads,
  })
}

function stateLabel(state) {
  return ({ Offline: 'Idle', Starting: 'Starting', Active: 'Running', Stopping: 'Stopping', Error: 'Needs attention' })[state] ?? 'Connecting'
}

function formatTime(value) {
  if (!value) return '—'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  return new Intl.DateTimeFormat(undefined, { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(date)
}

function safeError(payload, fallback) {
  const detail = typeof payload?.detail === 'string' ? payload.detail : payload?.error
  return typeof detail === 'string' ? detail : fallback
}

async function request(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: { ...(options.body ? { 'Content-Type': 'application/json' } : {}), ...options.headers },
  })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(safeError(payload, `Request failed (${response.status})`))
  return payload
}

function useSystemEvents() {
  const [events, setEvents] = useState([])
  const [connection, setConnection] = useState('connecting')
  const [status, setStatus] = useState({ state: 'Offline', status: 'Offline', is_running: false, demo: false })
  const seenIds = useRef(new Set())
  const hasWebSocketStatus = useRef(false)
  const statusRevision = useRef({ serverId: null, version: -1 })

  const addEvent = useCallback((event) => {
    if (!event || typeof event !== 'object') return
    if (event.id != null && seenIds.current.has(event.id)) return
    if (event.id != null) {
      seenIds.current.add(event.id)
      if (seenIds.current.size > 1000) seenIds.current.delete(seenIds.current.values().next().value)
    }
    setEvents((current) => {
      if (event.id != null && current.some((item) => item.id === event.id)) return current
      return [...current, event].slice(-500)
    })
  }, [])

  const applyStatus = useCallback((value, fromWebSocket = false) => {
    if (!value || typeof value !== 'object') return
    const serverId = typeof value.server_id === 'string' ? value.server_id : null
    const version = Number.isInteger(value.status_version) ? value.status_version : null
    const currentRevision = statusRevision.current
    if (serverId && version !== null) {
      if (currentRevision.serverId === serverId && version < currentRevision.version) return
      if (currentRevision.serverId && currentRevision.serverId !== serverId && !fromWebSocket) return
      statusRevision.current = { serverId, version }
    }
    if (fromWebSocket) hasWebSocketStatus.current = true
    else if (hasWebSocketStatus.current && version === null) return
    setStatus((current) => ({ ...current, ...value, state: value.state ?? value.status ?? current.state }))
  }, [])

  useEffect(() => {
    let socket
    let retryTimer
    let stopped = false
    let retryCount = 0
    const connect = () => {
      if (stopped) return
      const scheme = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      socket = new WebSocket(`${scheme}//${window.location.host}/api/ws`)
      socket.onopen = () => { retryCount = 0; setConnection('connected') }
      socket.onmessage = (message) => {
        try {
          const data = JSON.parse(message.data)
          if (data.type === 'status') applyStatus(data, true)
          if (data.type === 'history' && Array.isArray(data.events)) data.events.forEach(addEvent)
          if (data.type === 'event') addEvent(data.event)
        } catch { /* Ignore malformed frames and keep the dashboard connected. */ }
      }
      socket.onerror = () => socket.close()
      socket.onclose = () => {
        setConnection('reconnecting')
        if (!stopped) {
          retryCount += 1
          retryTimer = window.setTimeout(connect, Math.min(1000 * (2 ** Math.min(retryCount, 5)), 15000))
        }
      }
    }
    connect()
    return () => { stopped = true; window.clearTimeout(retryTimer); socket?.close() }
  }, [addEvent, applyStatus])

  useEffect(() => {
    let alive = true
    request('/api/status').then((value) => { if (alive) applyStatus(value) }).catch(() => {})
    return () => { alive = false }
  }, [applyStatus])

  return { events, setEvents, connection, status, applyStatus, addEvent }
}

function viewForHash(hash) {
  if (hash === '#credits') return 'credits'
  return ['#settings', '#account', '#schedule'].includes(hash) ? 'settings' : 'threads'
}

function App() {
  const system = useSystemEvents()
  const [view, setView] = useState(() => viewForHash(window.location.hash))
  useEffect(() => {
    const syncView = () => setView(viewForHash(window.location.hash))
    window.addEventListener('hashchange', syncView)
    return () => window.removeEventListener('hashchange', syncView)
  }, [])
  useEffect(() => {
    window.scrollTo({ top: 0 })
  }, [view])
  const [config, setConfig] = useState(DEFAULT_CONFIG)
  const [baseline, setBaseline] = useState(DEFAULT_CONFIG)
  const [password, setPassword] = useState('')
  const [configState, setConfigState] = useState('loading')
  const [formError, setFormError] = useState('')
  const [saveNotice, setSaveNotice] = useState('')
  const [activityNotice, setActivityNotice] = useState('')
  const [busyAction, setBusyAction] = useState('')
  const [search, setSearch] = useState('')
  const [level, setLevel] = useState('ALL')
  const [followTail, setFollowTail] = useState(true)
  const [activityOpen, setActivityOpen] = useState(false)
  const logViewportRef = useRef(null)
  const configLoadSequence = useRef(0)

  const loadConfig = useCallback(async () => {
    const sequence = ++configLoadSequence.current
    setConfigState('loading')
    setFormError('')
    try {
      const value = normalizeConfig(await request('/api/config'))
      if (sequence !== configLoadSequence.current) return
      setConfig(value)
      setBaseline(value)
      setPassword('')
      setConfigState('ready')
    } catch (error) {
      if (sequence !== configLoadSequence.current) return
      setConfigState('error')
      setFormError(`Settings could not load. ${error.message}`)
    }
  }, [])

  useEffect(() => { loadConfig() }, [loadConfig])

  const dirty = configSignature(config) !== configSignature(baseline) || password.length > 0
  const active = ['Starting', 'Active', 'Stopping'].includes(system.status.state)
  const hasEventFilters = Boolean(search.trim()) || level !== 'ALL'
  const visibleEvents = useMemo(() => system.events.filter((event) => {
    const matchesLevel = level === 'ALL' || event.level === level
    const query = search.trim().toLowerCase()
    const haystack = `${event.message ?? ''} ${event.event_type ?? ''} ${event.thread_index ?? ''}`.toLowerCase()
    return matchesLevel && (!query || haystack.includes(query))
  }), [system.events, level, search])

  const latestEventId = visibleEvents.at(-1)?.id
  useEffect(() => {
    const viewport = logViewportRef.current
    if (activityOpen && followTail && viewport) viewport.scrollTop = viewport.scrollHeight
  }, [latestEventId, visibleEvents.length, followTail, activityOpen])

  function patchConfig(patch) {
    setConfig((current) => ({ ...current, ...patch }))
    setSaveNotice('')
    setFormError('')
  }

  function patchThread(index, patch) {
    const threads = config.threads.map((thread, currentIndex) => currentIndex === index ? { ...thread, ...patch } : thread)
    patchConfig({ threads })
  }

  function validate() {
    if (!config.username.trim()) return 'Enter a username in Settings.'
    if (!Number.isInteger(Number(config.interval)) || Number(config.interval) < 1 || Number(config.interval) > 1440) return 'Set an interval of 1 to 1,440 whole minutes in Settings.'
    for (const [index, thread] of config.threads.entries()) {
      if (!thread.url.trim() || !thread.message.trim()) return `Thread ${index + 1} needs both a URL and a reply message.`
      try {
        const url = new URL(thread.url)
        if (!['http:', 'https:'].includes(url.protocol)) throw new Error('scheme')
      } catch { return `Thread ${index + 1} needs a valid http or https URL.` }
    }
    return ''
  }

  async function saveConfig(event) {
    event.preventDefault()
    const problem = validate()
    if (problem) { setFormError(problem); setSaveNotice(''); return }
    setBusyAction('save')
    setFormError('')
    setSaveNotice('')
    const payload = {
      username: config.username.trim(),
      interval: Number(config.interval),
      threads: config.threads.map((thread) => ({ url: thread.url.trim(), message: thread.message })),
    }
    if (password.length > 0) payload.password = password
    try {
      const result = await request('/api/config', { method: 'POST', body: JSON.stringify(payload) })
      const saved = normalizeConfig(result.config ?? { ...config, password_set: true })
      setConfig(saved)
      setBaseline(saved)
      setPassword('')
      setSaveNotice('Saved.')
    } catch (error) {
      setFormError(`Settings were not saved. ${error.message}`)
    } finally { setBusyAction('') }
  }

  async function runAction(action) {
    setBusyAction(action)
    setFormError('')
    setSaveNotice('')
    try {
      const result = await request(`/api/${action}`, { method: 'POST' })
      system.applyStatus(result)
      if (result.message) system.addEvent({
        id: `local-${Date.now()}`,
        timestamp: new Date().toISOString(),
        level: 'INFO',
        event_type: `ui.${action}`,
        message: result.message,
      })
    } catch (error) { setFormError(`Could not ${action}. ${error.message}`) }
    finally { setBusyAction('') }
  }

  async function copyVisible() {
    const text = visibleEvents.map((event) => `${event.timestamp ?? ''} [${event.level ?? 'INFO'}] ${event.message ?? ''}`).join('\n')
    try { await navigator.clipboard.writeText(text); setActivityNotice('Visible events copied.') }
    catch { setActivityNotice('Clipboard access is unavailable in this browser.') }
  }

  function exportVisible() {
    const blob = new Blob([JSON.stringify(visibleEvents, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const anchor = document.createElement('a')
    anchor.href = url
    anchor.download = `autobumper-events-${new Date().toISOString().slice(0, 10)}.json`
    anchor.click()
    URL.revokeObjectURL(url)
  }

  function clearLocalEvents() { system.setEvents([]) }

  const errors = system.events.filter((event) => event.level === 'ERROR').length
  const startHint = configState !== 'ready' ? 'Load your settings before starting.' : dirty ? 'Save your changes first.' : !config.username.trim() || !config.password_set ? 'Add your account in Settings.' : config.threads.length === 0 ? 'Add a thread first.' : system.status.state === 'Stopping' ? 'Waiting for the browser to close.' : ''

  const connected = system.connection === 'connected'
  const disabled = configState !== 'ready' || busyAction !== ''

  return (
    <div className="app-shell">
      <a className="skip-link" href="#workspace" onClick={(event) => { event.preventDefault(); const workspace = document.getElementById('workspace'); workspace?.focus(); workspace?.scrollIntoView({ block: 'start' }) }}>Skip to workspace</a>
      <aside className="sidebar" aria-label="Navigation">
        <a className="brand" href="#threads" onClick={() => setView('threads')}>OGU<span>Autobumper</span></a>
        <nav className="side-nav">
          <a className={view === 'threads' ? 'current' : ''} href="#threads" aria-current={view === 'threads' ? 'page' : undefined}>Threads</a>
          <a className={view === 'settings' ? 'current' : ''} href="#settings" aria-current={view === 'settings' ? 'page' : undefined}>Settings</a>
          <a className={view === 'credits' ? 'current' : ''} href="#credits" aria-current={view === 'credits' ? 'page' : undefined}>Credits</a>
        </nav>
        <a className="maker-link" href="https://oguser.com/member.php?action=profile&uid=435047" target="_blank" rel="noopener noreferrer">Made by /hyperpop</a>
      </aside>

      <main className="workspace" id="workspace" tabIndex={-1}>
        <header className="page-header">
          <h1 id={view}>{view === 'credits' ? 'Credits' : view === 'settings' ? 'Settings' : 'Threads'}</h1>
          {view !== 'credits' && <div className="header-actions">
            {dirty && <span className="save-state">Unsaved</span>}
            <button className="button secondary" form="run-settings" type="submit" disabled={disabled || !dirty}>{busyAction === 'save' ? 'Saving…' : 'Save'}</button>
          </div>}
        </header>
        {system.status.demo && <p className="demo-banner" role="status">Demo · No replies are posted.</p>}
        {!connected && <p className="feedback warning" role="status">{system.connection === 'connecting' ? 'Connecting to the server…' : 'Connection lost. Status may be out of date. Reconnecting…'}</p>}
        {system.status.log_persistence_ok === false && <p className="feedback warning" role="alert">Logs could not be saved to disk. Events are still available in this page.</p>}
        {formError && <p className="feedback error" role="alert">{formError}</p>}
        {saveNotice && view !== 'credits' && <p className="feedback success" role="status">{saveNotice}</p>}
        {configState !== 'ready' && view !== 'credits' && <div className="load-notice" role="status">
          <span>{configState === 'loading' ? 'Loading settings…' : 'Settings could not load.'}</span>
          {configState === 'error' && <button type="button" className="button secondary" onClick={loadConfig}>Retry</button>}
        </div>}

        <section className="run-bar" hidden={view !== 'threads'} aria-label="Run controls">
          <div className="run-status"><span className={`status-dot status-${system.status.state.toLowerCase()}`} /><span role="status">{connected ? stateLabel(system.status.state) : 'Disconnected'}</span><span className="interval-summary">Every {baseline.interval} min</span></div>
          <div className="run-actions">
            <button className="button primary" type="button" disabled={disabled || !connected || active || dirty || !config.username.trim() || !config.password_set || config.threads.length === 0} onClick={() => runAction('start')}>{busyAction === 'start' ? 'Starting…' : 'Start'}</button>
            <button className="button secondary" type="button" disabled={system.status.state !== 'Active' && system.status.state !== 'Starting' || busyAction !== ''} onClick={() => runAction('stop')}>{busyAction === 'stop' || system.status.state === 'Stopping' ? 'Stopping…' : 'Stop'}</button>
          </div>
          {startHint && <p className="run-hint">{startHint}</p>}
        </section>

        <form id="run-settings" onSubmit={saveConfig} noValidate hidden={view === 'credits'}>
          <fieldset disabled={disabled}>
            <legend className="sr-only">Threads and settings</legend>
            <section hidden={view !== 'threads'} aria-label="Thread replies">
              <div className="list-toolbar"><span>{config.threads.length} {config.threads.length === 1 ? 'thread' : 'threads'}</span><button className="button secondary" type="button" disabled={config.threads.length >= 100} onClick={() => patchConfig({ threads: [...config.threads, { url: '', message: '' }] })}>Add thread</button></div>
              <div className="thread-list">
                {config.threads.length === 0 && <p className="empty-state">No threads yet. Add a URL and message to get started.</p>}
                {config.threads.map((thread, index) => <article className="thread-row" key={`thread-${index}`}>
                  <div className="thread-heading"><h2>Thread {index + 1}</h2><button className="remove-button" type="button" aria-label={`Remove thread ${index + 1}`} onClick={() => patchConfig({ threads: config.threads.filter((_, currentIndex) => currentIndex !== index) })}>Remove</button></div>
                  <div className="thread-fields">
                    <div><label className="field-label" htmlFor={`thread-url-${index}`}>URL<span className="sr-only"> for thread {index + 1}</span></label>
                    <input id={`thread-url-${index}`} className="text-input url-input" type="url" inputMode="url" value={thread.url} onChange={(event) => patchThread(index, { url: event.target.value })} placeholder="https://ogu.gg/…" /></div>
                    <div><label className="field-label" htmlFor={`thread-message-${index}`}>Message<span className="sr-only"> for thread {index + 1}</span></label>
                    <textarea id={`thread-message-${index}`} className="text-input message-input" rows="2" maxLength={10000} value={thread.message} onChange={(event) => patchThread(index, { message: event.target.value })} placeholder="Your reply" /></div>
                  </div>
                </article>)}
              </div>
            </section>

            <section className="settings-form" hidden={view !== 'settings'} aria-label="Account and schedule">
              <label className="field-label" htmlFor="username">Username</label>
              <input id="username" className="text-input" autoComplete="username" value={config.username} onChange={(event) => patchConfig({ username: event.target.value })} placeholder="OGU username" />
              <div className="label-row"><label className="field-label" htmlFor="password">Password</label>{config.password_set && <span className="field-hint">Saved</span>}</div>
              <input id="password" className="text-input" type="password" autoComplete="new-password" value={password} onChange={(event) => { setPassword(event.target.value); setSaveNotice('') }} placeholder={config.password_set ? 'Saved password' : 'Password'} />
              {config.password_set && <p className="field-hint">Leave blank to keep it.</p>}
              <label className="field-label" htmlFor="interval">Interval (minutes)</label>
              <input id="interval" className="text-input interval-input" type="number" min="1" max="1440" step="1" inputMode="numeric" value={config.interval} onChange={(event) => patchConfig({ interval: event.target.value })} />
              <p className="field-hint">1–1,440 minutes between cycles.</p>
              <p className="settings-note">Saved threads and intervals apply next cycle. Restart to use new account details.</p>
            </section>
          </fieldset>
        </form>

        <section className="activity-panel" id="activity" hidden={view !== 'threads'} aria-label="Activity">
          <button className="activity-disclosure" type="button" aria-expanded={activityOpen} aria-controls={activityOpen ? 'activity-content' : undefined} onClick={() => setActivityOpen((value) => !value)}>
            <span>Activity <span className="event-count">{system.events.length}</span>{errors > 0 && <span className="error-count">{errors} {errors === 1 ? 'error' : 'errors'}</span>}</span><span className="disclosure-action">{activityOpen ? 'Hide' : 'Show'}</span>
          </button>
          {activityOpen && <div id="activity-content">
            <div className="activity-tools"><label className="search-box"><span className="sr-only">Search events</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search" /></label><label className="sr-only" htmlFor="level-filter">Level</label><select id="level-filter" value={level} onChange={(event) => setLevel(event.target.value)}>{LEVELS.map((item) => <option key={item} value={item}>{item === 'ALL' ? 'All levels' : item}</option>)}</select></div>
            <div className="log-viewport" ref={logViewportRef} aria-label="Activity events" tabIndex={0} onScroll={(event) => { const node = event.currentTarget; if (node.scrollHeight - node.scrollTop - node.clientHeight > 32) setFollowTail(false) }}>
              {visibleEvents.length === 0 ? <p className="empty-state">{hasEventFilters ? 'No matching events.' : 'No events yet.'}</p> : <ol className="event-list">{visibleEvents.map((event, index) => <li className="event-row" key={event.id ?? `${event.timestamp}-${index}`}><time dateTime={event.timestamp ?? undefined}>{formatTime(event.timestamp)}</time><span className={`level-name level-${(event.level ?? 'INFO').toLowerCase()}`}>{event.level ?? 'INFO'}</span><span className="event-message">{event.message ?? event.event_type ?? 'Event'}{event.thread_index != null && <small>Thread {Number(event.thread_index)}</small>}</span></li>)}</ol>}
            </div>
            {activityNotice && <p className="activity-notice" role="status">{activityNotice}</p>}
            <div className="activity-footer"><button type="button" className={followTail ? 'selected' : ''} aria-pressed={followTail} onClick={() => setFollowTail((value) => !value)}>Follow latest</button><div className="log-actions"><button type="button" onClick={copyVisible} disabled={!visibleEvents.length}>Copy</button><button type="button" onClick={exportVisible} disabled={!visibleEvents.length}>Export</button><button type="button" onClick={clearLocalEvents} disabled={!system.events.length} title="Clear this view. Saved logs remain.">Clear view</button></div></div>
          </div>}
        </section>

        {view === 'credits' && <section className="credits-view" aria-label="Project credits">
          <a className="maker-heading" href="https://oguser.com/member.php?action=profile&uid=435047" target="_blank" rel="noopener noreferrer">Made by /hyperpop</a>
          <p>Penderdrill made the original premise before he quit. I chose to keep it going and maintain it myself.</p>
          <a className="support-link" href="https://oguser.com/member.php?action=profile&uid=435047" target="_blank" rel="noopener noreferrer">Show support if you want</a>
        </section>}
      </main>
    </div>
  )
}

export default App
