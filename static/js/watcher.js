/**
 * watcher.js — Tool Suggestion + Analysis tab for agentflow
 *
 * Two analysis modes:
 *   📡 Continuous — delta-polls every N seconds, surfaces suggestions as they come
 *   ⏱  Timer      — fires a full analysis at a set interval over a configurable span
 *
 * Both modes push two SSE event types:
 *   tool_suggestion      → rendered as a suggestion card
 *   watcher_analysis_note → rendered as an inline analysis entry
 *
 * Public API (called by main.js):
 *   window.watcherAddSuggestion(event)
 *   window.watcherAddAnalysisNote(event)
 *   window.watcherClearSuggestions()
 *   window.watcherSetSessionMeta(meta)
 *   window.watcherHandleSessionStopped()
 */

(function () {
  'use strict';

  // ─── State ───────────────────────────────────────────────────────────────
  const STORAGE_KEY = 'watcher_suggestions_v3';
  let suggestions = [];
  let analysisNotes = [];
  let _isRunning = false;
  let _sessionMeta = null;
  let _unseenCount = 0;
  let _statusPollInterval = null;
  let _currentMode = 'continuous'; // 'continuous' | 'timer'

  // ─── Storage ─────────────────────────────────────────────────────────────
  function _load() {
    try {
      const d = JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '{}');
      suggestions = d.suggestions || [];
      analysisNotes = d.notes || [];
    } catch { suggestions = []; analysisNotes = []; }
  }
  function _save() {
    try { sessionStorage.setItem(STORAGE_KEY, JSON.stringify({ suggestions, notes: analysisNotes })); } catch {}
  }
  function _clearStorage() {
    suggestions = []; analysisNotes = [];
    sessionStorage.removeItem(STORAGE_KEY);
  }

  // ─── DOM ─────────────────────────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);

  // ─── Same-LLM indicator ───────────────────────────────────────────────────
  function _updateSameLlmIndicator() {
    const chip = $('watcher-same-llm-chip');
    if (!chip || !_sessionMeta) { if (chip) chip.style.display = 'none'; return; }
    const wUrl = ($('watcher-url-input')?.value || '').trim().replace(/\/$/, '');
    const wModel = $('watcher-model-select')?.value || '';
    const sUrl = (_sessionMeta.url || '').trim().replace(/\/$/, '');
    const sModel = _sessionMeta.model || '';
    chip.style.display = (wUrl && wModel && wUrl === sUrl && wModel === sModel) ? 'flex' : 'none';
  }

  // ─── Pre-fill from session ────────────────────────────────────────────────
  function _prefillFromSession() {
    if (!_sessionMeta) return;
    const urlEl = $('watcher-url-input');
    if (urlEl && !urlEl.value) urlEl.value = _sessionMeta.url || '';
    const sslEl = $('watcher-ssl-toggle');
    if (sslEl) sslEl.checked = _sessionMeta.ssl_verify !== false;
    const provEl = $('watcher-provider-select');
    if (provEl && _sessionMeta.provider) provEl.value = _sessionMeta.provider;
  }

  // ─── Mode toggle ─────────────────────────────────────────────────────────
  function _initModeToggle() {
    document.querySelectorAll('.watcher-mode-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        _currentMode = btn.dataset.mode;
        document.querySelectorAll('.watcher-mode-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        $('watcher-continuous-settings').style.display = _currentMode === 'continuous' ? '' : 'none';
        $('watcher-timer-settings').style.display = _currentMode === 'timer' ? '' : 'none';
      });
    });
  }

  // ─── Range slider live labels ─────────────────────────────────────────────
  function _initRangeSliders() {
    const poll = $('watcher-poll-interval');
    const pollVal = $('watcher-poll-interval-val');
    if (poll && pollVal) {
      poll.addEventListener('input', () => { pollVal.textContent = `${poll.value} s`; });
    }
    const lines = $('watcher-min-lines');
    const linesVal = $('watcher-min-lines-val');
    if (lines && linesVal) {
      lines.addEventListener('input', () => { linesVal.textContent = lines.value; });
    }
  }

  // ─── Mode config collector ────────────────────────────────────────────────
  function _getModeConfig() {
    const maxContext = parseInt($('watcher-context-size')?.value || '64000');
    if (_currentMode === 'continuous') {
      return {
        watch_mode: 'continuous',
        poll_interval: parseInt($('watcher-poll-interval')?.value || '10'),
        min_new_lines: parseInt($('watcher-min-lines')?.value || '3'),
        max_context_chars: maxContext,
      };
    }
    return {
      watch_mode: 'timer',
      timer_interval: parseInt($('watcher-timer-interval')?.value || '60'),
      timer_span: $('watcher-timer-span')?.value || 'all',
      max_context_chars: maxContext,
    };
  }

  // ─── Fetch models ─────────────────────────────────────────────────────────
  async function _fetchModels() {
    const btn = $('watcher-fetch-models-btn');
    const sel = $('watcher-model-select');
    const errEl = $('watcher-fetch-error');
    const urlEl = $('watcher-url-input');
    const provEl = $('watcher-provider-select');
    if (!btn || !sel) return;
    const url = (urlEl?.value || '').trim();
    if (!url) { if (errEl) { errEl.textContent = 'Enter LLM URL first.'; errEl.style.display = ''; } return; }
    if (errEl) errEl.style.display = 'none';
    btn.disabled = true;
    btn.querySelector('i')?.classList.add('spin');
    try {
      const res = await fetch('/api/models', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url, provider: provEl?.value || 'ollama_direct',
          api_key: $('watcher-api-key-input')?.value?.trim() || '',
          ssl_verify: $('watcher-ssl-toggle')?.checked !== false,
        }),
      });
      const data = await res.json();
      if (!data.success || !data.models?.length) throw new Error(data.error || 'No models found.');
      sel.innerHTML = data.models.map((m) => {
        const val = typeof m === 'string' ? m : m.id;
        const lbl = typeof m === 'string' ? m : m.label;
        return `<option value="${_esc(val)}">${_esc(lbl)}</option>`;
      }).join('');
      sel.disabled = false;
      if (_sessionMeta?.model && [...sel.options].some((o) => o.value === _sessionMeta.model)) {
        sel.value = _sessionMeta.model;
      }
      $('watcher-start-btn').disabled = false;
      _updateSameLlmIndicator();
    } catch (err) {
      if (errEl) { errEl.textContent = err.message; errEl.style.display = ''; }
    } finally {
      btn.disabled = false;
      btn.querySelector('i')?.classList.remove('spin');
    }
  }

  // ─── Status badge ─────────────────────────────────────────────────────────
  function _setStatus(running, label, modeData = null) {
    _isRunning = running;
    const badge = $('watcher-status-badge');
    const text = $('watcher-status-text');
    const btn = $('watcher-start-btn');
    const icon = $('watcher-start-btn-icon');
    const lbl = $('watcher-start-btn-label');
    if (badge) badge.className = 'watcher-status-badge ' + (running ? 'watcher-status-running' : 'watcher-status-idle');
    
    if (label) {
      if (text) text.textContent = label;
    } else if (running && modeData) {
      let mLabel = 'Watching…';
      if (modeData.watching_mode === 'continuous-live') mLabel = '📡 Live (watchdog)';
      else if (modeData.watching_mode === 'continuous-poll') mLabel = '📡 Polling';
      else if (modeData.watching_mode === 'timer') mLabel = '⏱ Timer';
      const sameStr = modeData.using_session_llm ? ' ⚠️ same LLM' : '';
      if (text) text.textContent = `${mLabel} · ${modeData.model || ''}${sameStr}`;
    } else {
      if (text) text.textContent = running ? 'Watching…' : 'Idle — not watching';
    }

    if (btn) {
      if (icon) icon.textContent = running ? '⏹' : '▶';
      if (lbl) lbl.textContent = running ? 'Stop Watcher' : 'Start Watcher';
      btn.className = 'btn ' + (running ? 'btn-danger' : 'btn-primary');
      btn.disabled = false;
    }
  }

  // ─── Nav badge ────────────────────────────────────────────────────────────
  function _updateNavBadge() {
    const navBadge = $('watcher-nav-badge');
    const countBadge = $('watcher-count-badge');
    if (navBadge) { navBadge.textContent = _unseenCount; navBadge.style.display = _unseenCount > 0 ? '' : 'none'; }
    if (countBadge) { countBadge.textContent = suggestions.length; countBadge.style.display = suggestions.length > 0 ? '' : 'none'; }
  }

  function _incrementUnseen() {
    const pane = $('watcher-pane');
    if (!pane?.classList.contains('active')) { _unseenCount++; _updateNavBadge(); }
  }
  function _resetUnseen() { _unseenCount = 0; _updateNavBadge(); }

  // ─── Analysis notes ───────────────────────────────────────────────────────
  function _renderNotes() {
    const container = $('watcher-notes-container');
    if (!container) return;
    if (!analysisNotes.length) { container.innerHTML = ''; container.style.display = 'none'; return; }
    container.style.display = '';
    container.innerHTML = '<div class="watcher-notes-header">🔍 Analysis Notes</div>' +
      analysisNotes.slice().reverse().map((n) => {
        const modeIcon = n.source_mode === 'timer' ? '⏱' : '📡';
        const ts = n.timestamp ? new Date(n.timestamp).toLocaleTimeString() : '';
        const span = n.span_label ? ` <span class="watcher-note-span">${_esc(n.span_label)}</span>` : '';
        return `<div class="watcher-note-entry">
          <div class="watcher-note-meta">${modeIcon}${span}<span class="watcher-card-ts">${ts}</span></div>
          <p class="watcher-note-text">${_esc(n.note)}</p>
        </div>`;
      }).join('');
  }

  // ─── Suggestion cards ─────────────────────────────────────────────────────
  function _renderCards() {
    const container = $('watcher-cards-container');
    const empty = $('watcher-empty-state');
    if (!container) return;
    if (!suggestions.length) {
      container.innerHTML = '';
      if (empty) empty.style.display = '';
      return;
    }
    if (empty) empty.style.display = 'none';
    container.innerHTML = '';
    suggestions.slice().reverse().forEach((s) => {
      const card = document.createElement('div');
      card.className = 'watcher-card';
      card.dataset.slug = s.slug;
      const ts = s.timestamp ? new Date(s.timestamp).toLocaleTimeString() : '';
      const modeIcon = s.source_mode === 'timer' ? '⏱' : '📡';
      card.innerHTML = `
        <div class="watcher-card-header">
          <span class="watcher-tool-name">${_esc(s.name)}</span>
          <span class="watcher-card-ts">${modeIcon} ${ts}</span>
        </div>
        <p class="watcher-one-line">${_esc(s.one_line)}</p>
        <p class="watcher-rationale">${_esc(s.rationale)}</p>
        ${s.commands ? `<p class="watcher-commands"><code>${_esc(s.commands)}</code></p>` : ''}
        <div class="watcher-card-actions">
          <button class="btn btn-primary watcher-btn-view" data-slug="${s.slug}" style="font-size:0.8rem;padding:0.28rem 0.7rem;width:auto">View Scaffold</button>
          <button class="watcher-btn-ghost watcher-btn-dismiss" data-slug="${s.slug}">Dismiss</button>
        </div>
      `;
      container.appendChild(card);
    });
    container.querySelectorAll('.watcher-btn-view').forEach((btn) => btn.addEventListener('click', () => _viewScaffold(btn.dataset.slug)));
    container.querySelectorAll('.watcher-btn-dismiss').forEach((btn) => btn.addEventListener('click', () => _dismiss(btn.dataset.slug)));
    _updateNavBadge();
  }

  function _esc(s) {
    return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  // ─── Scaffold modal ────────────────────────────────────────────────────────
  function _viewScaffold(slug) {
    const s = suggestions.find((x) => x.slug === slug);
    if (!s) return;
    $('watcher-modal-title').textContent = `🔧 ${s.name}`;
    $('watcher-modal-meta').innerHTML = `<strong>${_esc(s.one_line)}</strong><br><span style="opacity:0.8">${_esc(s.rationale)}</span>`;
    $('watcher-modal-code').textContent = s.scaffold_code || '# Scaffold not available';
    $('watcher-modal-overlay').style.display = 'flex';
  }

  function _dismiss(slug) {
    suggestions = suggestions.filter((s) => s.slug !== slug);
    _save(); _renderCards();
  }

  function _clearAll() {
    _clearStorage(); _unseenCount = 0;
    _renderCards(); _renderNotes(); _updateNavBadge();
  }

  // ─── Start / Stop ─────────────────────────────────────────────────────────
  async function _toggleWatcher() {
    const btn = $('watcher-start-btn');
    if (!btn) return;
    btn.disabled = true;

    if (_isRunning) {
      try { await fetch('/api/watcher/stop', { method: 'POST' }); } catch {}
      _setStatus(false);
      _stopStatusPoll();
    } else {
      const url = ($('watcher-url-input')?.value || '').trim();
      const model = $('watcher-model-select')?.value || '';
      const provider = $('watcher-provider-select')?.value || 'ollama_direct';
      const apiKey = $('watcher-api-key-input')?.value?.trim() || '';
      const ssl = $('watcher-ssl-toggle')?.checked !== false;
      const modeConfig = _getModeConfig();

      if (!model) { alert('Select a model first.'); btn.disabled = false; return; }
      const errEl = $('watcher-fetch-error');
      if (errEl) errEl.style.display = 'none';

      try {
        const res = await fetch('/api/watcher/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ url, model, provider, api_key: apiKey, ssl_verify: ssl, ...modeConfig }),
        });
        const data = await res.json();
        if (!data.success) {
          if (errEl) { errEl.textContent = data.error || 'Failed to start.'; errEl.style.display = ''; }
          btn.disabled = false; return;
        }
        _setStatus(true, null, {
          watching_mode: data.watching_mode,
          model: model,
          using_session_llm: data.using_session_llm
        });
        _startStatusPoll();
      } catch (err) {
        if (errEl) { errEl.textContent = err.message; errEl.style.display = ''; }
        btn.disabled = false;
      }
    }
  }

  // ─── Status polling ───────────────────────────────────────────────────────
  function _startStatusPoll() {
    _stopStatusPoll();
    _statusPollInterval = setInterval(async () => {
      try {
        const data = await fetch('/api/watcher/status').then((r) => r.json());
        if (!data.running && _isRunning) { _setStatus(false, 'Idle — session ended'); _stopStatusPoll(); }
        else if (data.running && _isRunning) {
           _setStatus(true, null, { watching_mode: data.watching_mode, model: $('watcher-model-select')?.value });
        }
      } catch {}
    }, 8000);
  }
  function _stopStatusPoll() {
    if (_statusPollInterval) { clearInterval(_statusPollInterval); _statusPollInterval = null; }
  }

  // ─── Tab active tracking ──────────────────────────────────────────────────
  function _onTabSwitch(targetPaneId) {
    if (targetPaneId === 'watcher-pane') _resetUnseen();
  }

  // ─── Public API ───────────────────────────────────────────────────────────
  function addSuggestion(event) {
    const slug = event.slug;
    if (!slug || suggestions.some((s) => s.slug === slug)) return;
    suggestions.push({
      slug, name: event.name || slug, one_line: event.one_line || '',
      rationale: event.rationale || '', commands: event.commands || '',
      scaffold_code: event.scaffold_code || '',
      timestamp: event.timestamp || new Date().toISOString(),
      source_mode: event.source_mode || 'continuous',
    });
    _save(); _renderCards(); _incrementUnseen();
  }

  // Live streaming notes dictionary: note_id -> { DOM element, text }
  const _liveNotes = {};

  function noteStart(event) {
    const container = $('watcher-notes-container');
    if (!container) return;
    container.style.display = '';
    
    // Create header if missing
    if (!container.querySelector('.watcher-notes-header')) {
      container.innerHTML = '<div class="watcher-notes-header">🔍 Analysis Notes</div>';
    }

    const ts = event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : '';
    const entry = document.createElement('div');
    entry.className = 'watcher-note-entry watcher-note-live';
    entry.id = `watcher-live-note-${event.note_id}`;
    entry.innerHTML = `
      <div class="watcher-note-meta">📡<span class="watcher-card-ts">${ts}</span></div>
      <p class="watcher-note-text"><span class="live-text"></span><span class="watcher-note-cursor"></span></p>
    `;
    
    // Insert right after header (top of list)
    const header = container.querySelector('.watcher-notes-header');
    if (header && header.nextSibling) {
      container.insertBefore(entry, header.nextSibling);
    } else {
      container.appendChild(entry);
    }

    _liveNotes[event.note_id] = { el: entry.querySelector('.live-text'), text: '' };
    _incrementUnseen();
  }

  function noteToken(event) {
    const live = _liveNotes[event.note_id];
    if (!live || !live.el) return;
    live.text += event.token || '';
    live.el.textContent = live.text;
  }

  function noteComplete(event) {
    const live = _liveNotes[event.note_id];
    if (!live) return;
    
    // Remove the cursor and the live pulse
    const entry = $(`watcher-live-note-${event.note_id}`);
    if (entry) {
      entry.classList.remove('watcher-note-live');
      const cursor = entry.querySelector('.watcher-note-cursor');
      if (cursor) cursor.remove();
    }
    
    // Save to persistent array
    analysisNotes.push({
      note: live.text,
      timestamp: new Date().toISOString(),
      source_mode: 'continuous',
      span_label: '',
    });
    if (analysisNotes.length > 20) analysisNotes = analysisNotes.slice(-20);
    _save();
    
    delete _liveNotes[event.note_id];
  }

  function addAnalysisNote(event) {
    if (!event.note) return;
    analysisNotes.push({
      note: event.note,
      timestamp: event.timestamp || new Date().toISOString(),
      source_mode: event.source_mode || 'continuous',
      span_label: event.span_label || '',
    });
    // Keep only last 20 notes
    if (analysisNotes.length > 20) analysisNotes = analysisNotes.slice(-20);
    _save(); _renderNotes(); _incrementUnseen();
  }

  function clearSuggestions() { _clearAll(); }

  function setSessionMeta(meta) {
    _sessionMeta = meta;
    _prefillFromSession();
    _updateSameLlmIndicator();
    const notice = $('watcher-no-session-notice');
    if (notice) notice.style.display = meta ? 'none' : '';
    if ($('watcher-model-select')?.value && meta) {
      const btn = $('watcher-start-btn');
      if (btn) btn.disabled = false;
    }
  }

  function handleSessionStopped() {
    if (_isRunning) { _setStatus(false, 'Idle — session ended'); _stopStatusPoll(); }
    _sessionMeta = null;
    const notice = $('watcher-no-session-notice');
    if (notice) notice.style.display = '';
  }

  // ─── Init ────────────────────────────────────────────────────────────────
  function init() {
    _load();
    _initModeToggle();
    _initRangeSliders();

    $('watcher-fetch-models-btn')?.addEventListener('click', _fetchModels);
    $('watcher-url-input')?.addEventListener('input', _updateSameLlmIndicator);
    $('watcher-model-select')?.addEventListener('change', () => {
      _updateSameLlmIndicator();
      const btn = $('watcher-start-btn');
      if (btn) btn.disabled = !$('watcher-model-select').value;
    });
    $('watcher-provider-select')?.addEventListener('change', _updateSameLlmIndicator);
    $('watcher-start-btn')?.addEventListener('click', _toggleWatcher);
    $('watcher-clear-all-btn')?.addEventListener('click', _clearAll);

    // Scaffold modal
    $('watcher-modal-close')?.addEventListener('click', () => { $('watcher-modal-overlay').style.display = 'none'; });
    $('watcher-modal-dismiss')?.addEventListener('click', () => { $('watcher-modal-overlay').style.display = 'none'; });
    $('watcher-modal-overlay')?.addEventListener('click', (e) => { if (e.target === $('watcher-modal-overlay')) $('watcher-modal-overlay').style.display = 'none'; });
    $('watcher-modal-copy')?.addEventListener('click', () => {
      const code = $('watcher-modal-code')?.textContent || '';
      navigator.clipboard.writeText(code).catch(() => {});
      const btn = $('watcher-modal-copy');
      if (btn) { btn.textContent = 'Copied!'; setTimeout(() => { btn.textContent = 'Copy Scaffold'; }, 2000); }
    });

    // Tab switch unseen reset
    document.querySelectorAll('[data-target]').forEach((btn) => {
      btn.addEventListener('click', () => _onTabSwitch(btn.dataset.target));
    });

    // No-session notice
    const notice = $('watcher-no-session-notice');
    if (notice) notice.style.display = _sessionMeta ? 'none' : '';

    _renderCards();
    _renderNotes();

    fetch('/api/watcher/status').then((r) => r.json()).then((d) => {
      if (d.running) _setStatus(true, null, { watching_mode: d.watching_mode, model: $('watcher-model-select')?.value });
    }).catch(() => {});

    // Expose public API
    window.watcherAddSuggestion = addSuggestion;
    window.watcherAddAnalysisNote = addAnalysisNote;
    window.watcherNoteStart = noteStart;
    window.watcherNoteToken = noteToken;
    window.watcherNoteComplete = noteComplete;
    window.watcherClearSuggestions = clearSuggestions;
    window.watcherSetSessionMeta = setSessionMeta;
    window.watcherHandleSessionStopped = handleSessionStopped;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
