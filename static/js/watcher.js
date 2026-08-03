/**
 * watcher.js — Tool Suggestion + Analysis tab for cyber-agentflow
 *
 * Two analysis modes:
 *   ⏱  Periodic       — analyzes a selected CyberAgentFlow data window on a cadence
 *   📡 Network Stream — processes normalized network telemetry continuously
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
  let _isNwRunning = false;
  let _sessionMeta = null;
  let _unseenCount = 0;
  let _statusPollInterval = null;
  let _nwStatusPollInterval = null;
  let _nwInteractionRevision = null;
  let _modelSsmCompatibility = new Map();
  let _suricataStatus = null;
  let _currentMode = 'periodic'; // 'periodic' | 'network'
  let _cyberAgentFlowDataAvailable = false;

  // ─── Storage ─────────────────────────────────────────────────────────────
  const SETTINGS_KEY = 'watcher_form_settings_v1';

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

  const DEFAULT_PROMPTS = {
    periodic: `You are an expert MCP tooling analyst reviewing a penetration-testing agent session log.
Your job has two parts:

1. ANALYSIS NOTE — Write a concise 2-4 sentence summary of what the agent has been doing in the log window, highlighting any patterns or inefficiencies.

2. TOOL SUGGESTIONS — Identify up to 2 small MCP tools that would meaningfully reduce friction based on what you observed. Do NOT suggest existing tools.

Respond ONLY with valid JSON (no markdown fences, no extra text):
{
  "note": "<2-4 sentence analysis>",
  "tools": [
    {
      "name": "<snake_case_name>",
      "one_line": "<one sentence>",
      "rationale": "<2-3 sentences>",
      "commands": "<shell command(s)>"
    }
  ]
}`,

    network: `You are an anomaly detection SSM watching a live packet stream.
Review the structured packet records: protocol stack, decoded headers, and bounded payloads.
Treat HTTPS payload bytes as encrypted unless the record explicitly contains decoded HTTP data.
If you see plaintext credentials, API keys, sensitive server banners, or anything notable,
state the finding in 2-3 concise sentences. Return only the final observation, with no internal reasoning.
If nothing interesting is found, say that clearly.`
  };

  let _customPrompts = { ...DEFAULT_PROMPTS };

  function _updatePromptField() {
    const promptEl = $('watcher-system-prompt');
    if (!promptEl) return;
    promptEl.value = _customPrompts[_currentMode] || DEFAULT_PROMPTS[_currentMode] || '';
  }

  function _saveFormSettings() {
    try {
      const selectedIfaces = Array.from(document.querySelectorAll('.nw-iface-cb:checked')).map(cb => cb.value);
      const packetFields = Array.from(document.querySelectorAll('.nw-packet-field-cb:checked')).map(cb => cb.value);
      const suricataEventTypes = Array.from(document.querySelectorAll('.nw-suricata-event-cb:checked')).map(cb => cb.value);
      const promptEl = $('watcher-system-prompt');
      if (promptEl) {
        _customPrompts[_currentMode] = promptEl.value;
      }
      const settings = {
        provider: $('watcher-provider-select')?.value,
        url: $('watcher-url-input')?.value,
        apiKey: $('watcher-api-key-input')?.value,
        sslVerify: $('watcher-ssl-toggle')?.checked,
        model: $('watcher-model-select')?.value,
        contextSize: $('watcher-context-size')?.value,
        timeout: $('watcher-timeout-select')?.value,
        mode: _currentMode,
        timerInterval: $('watcher-timer-interval')?.value,
        timerSpan: $('watcher-timer-span')?.value,
        periodicUseCyberAgentFlowData: $('watcher-periodic-use-caf-data')?.checked,
        networkUseCyberAgentFlowData: $('nw-use-caf-data')?.checked,
        selectedInterfaces: selectedIfaces,
        captureSource: $('nw-capture-source')?.value,
        suricataEvePath: $('nw-suricata-eve-path')?.value,
        suricataEventTypes,
        analysisInterval: $('nw-analysis-interval')?.value,
        maxPacketPayloadBytes: $('nw-max-payload-bytes')?.value,
        maxPacketsPerAnalysis: $('nw-max-packets-per-analysis')?.value,
        packetFields,
        analysisEngine: $('nw-analysis-engine')?.value,
        ssmModelPath: $('nw-ssm-model-path')?.value,
        ssmGpuLayers: $('nw-ssm-gpu-layers')?.value,
        ssmContextTokens: $('nw-ssm-context-tokens')?.value,
        ssmMaxFlows: $('nw-ssm-max-flows')?.value,
        ssmAlertThreshold: $('nw-ssm-alert-threshold')?.value,
        ssmAlertCooldown: $('nw-ssm-alert-cooldown')?.value,
        customPrompts: _customPrompts
      };
      localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings));
    } catch (e) {
      console.warn('Failed to save watcher settings:', e);
    }
  }

  function _loadFormSettings() {
    try {
      const raw = localStorage.getItem(SETTINGS_KEY);
      if (!raw) return;
      const settings = JSON.parse(raw);

      if (settings.customPrompts) {
        _customPrompts = { ...DEFAULT_PROMPTS, ...settings.customPrompts };
        if (settings.customPrompts.timer && !settings.customPrompts.periodic) {
          _customPrompts.periodic = settings.customPrompts.timer;
        }
      }

      if (settings.provider && $('watcher-provider-select')) $('watcher-provider-select').value = settings.provider;
      if (settings.url !== undefined && $('watcher-url-input')) $('watcher-url-input').value = settings.url;
      if (settings.apiKey !== undefined && $('watcher-api-key-input')) $('watcher-api-key-input').value = settings.apiKey;
      if (settings.sslVerify !== undefined && $('watcher-ssl-toggle')) $('watcher-ssl-toggle').checked = Boolean(settings.sslVerify);
      if (settings.contextSize && $('watcher-context-size')) $('watcher-context-size').value = settings.contextSize;
      if (settings.timeout && $('watcher-timeout-select')) $('watcher-timeout-select').value = settings.timeout;
      if (settings.timerInterval && $('watcher-timer-interval')) $('watcher-timer-interval').value = settings.timerInterval;
      if (settings.timerSpan && $('watcher-timer-span')) $('watcher-timer-span').value = settings.timerSpan;
      if (settings.periodicUseCyberAgentFlowData !== undefined && $('watcher-periodic-use-caf-data')) $('watcher-periodic-use-caf-data').checked = Boolean(settings.periodicUseCyberAgentFlowData);
      if (settings.networkUseCyberAgentFlowData !== undefined && $('nw-use-caf-data')) $('nw-use-caf-data').checked = Boolean(settings.networkUseCyberAgentFlowData);
      if (settings.analysisInterval && $('nw-analysis-interval')) $('nw-analysis-interval').value = settings.analysisInterval;
      if (settings.maxPacketPayloadBytes && $('nw-max-payload-bytes')) $('nw-max-payload-bytes').value = settings.maxPacketPayloadBytes;
      if (settings.maxPacketsPerAnalysis && $('nw-max-packets-per-analysis')) $('nw-max-packets-per-analysis').value = settings.maxPacketsPerAnalysis;
      if (settings.captureSource && $('nw-capture-source')) $('nw-capture-source').value = settings.captureSource;
      if (settings.suricataEvePath !== undefined && $('nw-suricata-eve-path')) $('nw-suricata-eve-path').value = settings.suricataEvePath;
      if (Array.isArray(settings.suricataEventTypes)) {
        document.querySelectorAll('.nw-suricata-event-cb').forEach((checkbox) => {
          checkbox.checked = settings.suricataEventTypes.includes(checkbox.value);
        });
      }
      if (settings.analysisEngine && $('nw-analysis-engine')) $('nw-analysis-engine').value = settings.analysisEngine;
      if (settings.ssmModelPath !== undefined && $('nw-ssm-model-path')) $('nw-ssm-model-path').value = settings.ssmModelPath;
      if (settings.ssmGpuLayers && $('nw-ssm-gpu-layers')) $('nw-ssm-gpu-layers').value = settings.ssmGpuLayers;
      if (settings.ssmContextTokens && $('nw-ssm-context-tokens')) $('nw-ssm-context-tokens').value = settings.ssmContextTokens;
      if (settings.ssmMaxFlows && $('nw-ssm-max-flows')) $('nw-ssm-max-flows').value = settings.ssmMaxFlows;
      if (settings.ssmAlertThreshold && $('nw-ssm-alert-threshold')) $('nw-ssm-alert-threshold').value = settings.ssmAlertThreshold;
      if (settings.ssmAlertCooldown && $('nw-ssm-alert-cooldown')) $('nw-ssm-alert-cooldown').value = settings.ssmAlertCooldown;
      if (Array.isArray(settings.packetFields)) {
        document.querySelectorAll('.nw-packet-field-cb').forEach((checkbox) => {
          checkbox.checked = settings.packetFields.includes(checkbox.value);
        });
      }

      if (settings.mode) {
        _currentMode = settings.mode === 'continuous' ? 'network' : (settings.mode === 'timer' ? 'periodic' : settings.mode);
        document.querySelectorAll('.watcher-mode-btn').forEach((b) => {
          b.classList.toggle('active', b.dataset.mode === _currentMode);
        });
        if ($('watcher-periodic-settings')) $('watcher-periodic-settings').style.display = _currentMode === 'periodic' ? '' : 'none';
        const nwSettings = $('watcher-network-settings');
        if (nwSettings) {
          nwSettings.style.display = _currentMode === 'network' ? '' : 'none';
          if (_currentMode === 'network') _fetchNetworkInterfaces();
        }
        _updateMetricsView();
      }
      _updatePromptField();
      _updateCaptureSourceUi();
      _updateNetworkEngineUi();

      if (settings.url) {
        _fetchModels().then(() => {
          if (settings.model && $('watcher-model-select')) {
            $('watcher-model-select').value = settings.model;
            const btn = $('watcher-start-btn');
            if (btn) btn.disabled = false;
          }
        }).catch(() => {});
      }
    } catch (e) {
      console.warn('Failed to load watcher settings:', e);
    }
  }

  // ─── DOM ─────────────────────────────────────────────────────────────────
  const $ = (id) => document.getElementById(id);

  function _isLocalSsmEngine() {
    return _currentMode === 'network' && $('nw-analysis-engine')?.value === 'llamacpp_ssm';
  }

  function _isSuricataSource() {
    return _currentMode === 'network' && $('nw-capture-source')?.value === 'suricata_eve';
  }

  function _updateCaptureSourceUi() {
    const suricata = _isSuricataSource();
    const pythonSettings = $('nw-python-source-settings');
    const suricataSettings = $('nw-suricata-source-settings');
    const evePathGroup = $('nw-suricata-eve-path-group');
    if (pythonSettings) pythonSettings.style.display = _currentMode === 'network' && !suricata ? '' : 'none';
    if (suricataSettings) suricataSettings.style.display = _currentMode === 'network' && suricata ? '' : 'none';
    if (evePathGroup) evePathGroup.style.display = _currentMode === 'network' && suricata ? '' : 'none';
    if (_currentMode === 'network' && !suricata) _fetchNetworkInterfaces();
  }

  function _updateCyberAgentFlowDataControls() {
    const available = _cyberAgentFlowDataAvailable;
    [
      ['watcher-periodic-use-caf-data', 'watcher-periodic-caf-data-hint'],
      ['nw-use-caf-data', 'nw-caf-data-hint'],
    ].forEach(([toggleId, hintId]) => {
      const toggle = $(toggleId);
      const hint = $(hintId);
      if (toggle) {
        toggle.disabled = !available;
        if (!available) toggle.checked = false;
      }
      if (hint) {
        hint.textContent = available
          ? 'Uses the active CyberAgentFlow session data.'
          : 'Start Service to enable CyberAgentFlow session data.';
        hint.style.color = available ? 'var(--text-secondary)' : 'var(--text-muted)';
      }
    });
    _updateSessionNotice();
    _updateStartBtnState();
  }

  async function _refreshCyberAgentFlowDataAvailability() {
    try {
      const response = await fetch('/api/session/status');
      const status = await response.json();
      _cyberAgentFlowDataAvailable = status.status === 'running';
    } catch {
      _cyberAgentFlowDataAvailable = Boolean(_sessionMeta);
    }
    _updateCyberAgentFlowDataControls();
  }

  async function _fetchSuricataStatus() {
    const statusEl = $('nw-suricata-availability');
    const option = $('nw-capture-source')?.querySelector('option[value="suricata_eve"]');
    const refresh = $('nw-refresh-suricata-btn');
    if (refresh) refresh.disabled = true;
    try {
      const response = await fetch('/api/network_watcher/suricata/status');
      const status = await response.json();
      _suricataStatus = status;
      if (option) option.disabled = !status.available;
      if (statusEl) {
        const text = document.createElement('span');
        if (status.available) {
          text.textContent = `Suricata ready${status.version ? ` — ${status.version}` : ''}`;
          text.style.color = 'var(--success)';
        } else {
          text.textContent = 'Suricata is not installed on this host. Install it and restart or refresh before enabling EVE JSON mode.';
          text.style.color = 'var(--error)';
          if ($('nw-capture-source')?.value === 'suricata_eve') {
            $('nw-capture-source').value = 'python';
            _updateCaptureSourceUi();
            _saveFormSettings();
          }
        }
        const button = $('nw-refresh-suricata-btn');
        statusEl.replaceChildren(text, button || document.createTextNode(''));
      }
    } catch (error) {
      if (statusEl) {
        const text = document.createElement('span');
        text.textContent = 'Could not verify local Suricata availability.';
        text.style.color = 'var(--error)';
        statusEl.replaceChildren(text, refresh || document.createTextNode(''));
      }
      if (option) option.disabled = true;
    } finally {
      if (refresh) refresh.disabled = false;
    }
  }

  function _updateNetworkEngineUi() {
    const localSsm = _isLocalSsmEngine();
    const networkMode = _currentMode === 'network';
    const engineSettings = $('nw-engine-settings-section');
    const engineSettingsTarget = $('nw-engine-settings-setup-slot');
    const discoverySection = $('watcher-model-discovery-section');
    const discoveryTarget = networkMode ? $('watcher-network-runtime-slot') : $('watcher-model-discovery-setup-slot');
    const remoteSettings = $('watcher-remote-model-settings');
    const heading = $('watcher-model-heading');
    const localSettings = $('nw-local-ssm-settings');
    const remoteNote = $('nw-remote-batch-note');
    const sameModel = $('watcher-same-llm-chip');
    const providerLabel = $('watcher-provider-label');
    const urlLabel = $('watcher-url-label');
    const modelLabel = $('watcher-model-label');
    const providerHint = $('watcher-ssm-provider-hint');
    if (engineSettings && engineSettingsTarget && engineSettings.parentElement !== engineSettingsTarget) {
      engineSettingsTarget.append(engineSettings);
    }
    if (discoverySection && discoveryTarget && discoverySection.parentElement !== discoveryTarget) {
      discoveryTarget.append(discoverySection);
    }
    if (discoverySection) discoverySection.style.display = networkMode && localSsm ? 'none' : '';
    if (remoteSettings) remoteSettings.style.display = !networkMode || !localSsm ? '' : 'none';
    if (heading) heading.innerHTML = networkMode ? '<span>🧠</span> SSM Runtime & Model Discovery' : '<span>🔭</span> Watcher LLM';
    if (providerLabel) providerLabel.textContent = networkMode ? 'SSM provider / discovery endpoint' : 'Provider';
    if (urlLabel) urlLabel.textContent = networkMode ? 'Provider endpoint URL' : 'LLM URL';
    if (modelLabel) modelLabel.textContent = networkMode ? 'Discovered SSM model' : 'Model';
    if (providerHint) {
      providerHint.style.display = networkMode ? '' : 'none';
      providerHint.textContent = localSsm
        ? 'Provider discovery is optional in local mode; the GGUF path below selects the actual local SSM. Compatibility is inferred from returned model metadata.'
        : 'Remote mode requires a persistent SSM service at POST /v1/ssm/events. Fetching a provider model confirms only a likely model family, not stream-state support.';
    }
    if (localSettings) localSettings.style.display = _currentMode === 'network' && localSsm ? '' : 'none';
    if (remoteNote) remoteNote.style.display = _currentMode === 'network' && !localSsm ? '' : 'none';
    if (sameModel && localSsm) sameModel.style.display = 'none';
    _updateStartBtnState();
    _renderSsmCompatibility();
  }

  function _renderSsmCompatibility() {
    const target = $('watcher-ssm-compatibility');
    if (!target) return;
    if (_currentMode !== 'network') { target.style.display = 'none'; return; }
    const modelId = $('watcher-model-select')?.value || '';
    const compatibility = _modelSsmCompatibility.get(modelId);
    if (!modelId || !compatibility) {
      target.textContent = 'Fetch models to inspect any SSM architecture metadata exposed by this provider.';
      target.style.display = '';
      target.style.color = 'var(--text-secondary)';
      return;
    }
    target.textContent = `${compatibility.label}: ${compatibility.detail}`;
    target.style.display = '';
    target.style.color = compatibility.status === 'likely_recurrent' ? 'var(--success)' : (compatibility.status === 'not_ssm' ? 'var(--error)' : 'var(--text-secondary)');
  }

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
    const hasSavedSettings = localStorage.getItem(SETTINGS_KEY) !== null;
    const urlEl = $('watcher-url-input');
    if (urlEl && (!urlEl.value || !hasSavedSettings)) urlEl.value = urlEl.value || _sessionMeta.url || '';
    const sslEl = $('watcher-ssl-toggle');
    if (sslEl && !hasSavedSettings) sslEl.checked = _sessionMeta.ssl_verify !== false;
    const provEl = $('watcher-provider-select');
    if (provEl && !hasSavedSettings && _sessionMeta.provider) provEl.value = _sessionMeta.provider;
  }

  // ─── Mode toggle ─────────────────────────────────────────────────────────
  let _interfacesFetched = false;
  async function _fetchNetworkInterfaces() {
    if (_isSuricataSource()) return;
    if (_interfacesFetched) return;
    const container = $('nw-interface-container');
    if (!container) return;
    try {
      const res = await fetch('/api/network_watcher/interfaces');
      const data = await res.json();
      if (data.success && data.interfaces) {
        let savedIfaces = null;
        try {
          const raw = localStorage.getItem(SETTINGS_KEY);
          if (raw) savedIfaces = JSON.parse(raw).selectedInterfaces;
        } catch {}

        container.innerHTML = data.interfaces.map(iface => {
          const isChecked = savedIfaces ? savedIfaces.includes(iface) : (iface === 'eth0' || iface === 'en0');
          return `
            <label style="display:flex;align-items:center;gap:0.3rem;background:var(--bg-surface-1);padding:0.3rem 0.6rem;border-radius:4px;border:1px solid var(--border-subtle);cursor:pointer;font-size:0.85rem">
              <input type="checkbox" class="nw-iface-cb" value="${_esc(iface)}" ${isChecked ? 'checked' : ''}>
              ${_esc(iface)}
            </label>
          `;
        }).join('');
        _interfacesFetched = true;
        container.querySelectorAll('.nw-iface-cb').forEach(cb => {
          cb.addEventListener('change', _saveFormSettings);
        });
      }
    } catch (e) {
      container.innerHTML = `<div style="color:var(--error);font-size:0.85rem">Failed to load interfaces.</div>`;
    }
  }

  function _initModeToggle() {
    document.querySelectorAll('.watcher-mode-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        _currentMode = btn.dataset.mode;
        document.querySelectorAll('.watcher-mode-btn').forEach((b) => b.classList.remove('active'));
        btn.classList.add('active');
        $('watcher-periodic-settings').style.display = _currentMode === 'periodic' ? '' : 'none';
        const nwSettings = $('watcher-network-settings');
        if (nwSettings) {
          nwSettings.style.display = _currentMode === 'network' ? '' : 'none';
          if (_currentMode === 'network') _updateCaptureSourceUi();
        }
        _updateNetworkEngineUi();
        _updateMetricsView();
        _updatePromptField();
        _saveFormSettings();
      });
    });
  }

  // ─── Mode config collector ────────────────────────────────────────────────
  function _getModeConfig() {
    const maxContext = parseInt($('watcher-context-size')?.value || '64000');
    if (_currentMode === 'network') {
      return {
        watch_mode: 'network',
        capture_source: $('nw-capture-source')?.value || 'python',
        suricata_eve_path: $('nw-suricata-eve-path')?.value?.trim() || '/var/log/suricata/eve.json',
        suricata_event_types: Array.from(document.querySelectorAll('.nw-suricata-event-cb:checked')).map((checkbox) => checkbox.value),
        analysis_engine: $('nw-analysis-engine')?.value || 'llamacpp_ssm',
        analysis_interval_seconds: parseInt($('nw-analysis-interval')?.value || '5'),
        max_packet_payload_bytes: parseInt($('nw-max-payload-bytes')?.value || '384'),
        max_packets_per_analysis: parseInt($('nw-max-packets-per-analysis')?.value || '12'),
        packet_fields: Array.from(document.querySelectorAll('.nw-packet-field-cb:checked')).map((checkbox) => checkbox.value),
        ssm_model_path: $('nw-ssm-model-path')?.value?.trim() || '',
        ssm_gpu_layers: parseInt($('nw-ssm-gpu-layers')?.value || '0'),
        ssm_context_tokens: parseInt($('nw-ssm-context-tokens')?.value || '1024'),
        ssm_max_flows: parseInt($('nw-ssm-max-flows')?.value || '256'),
        ssm_alert_threshold: parseFloat($('nw-ssm-alert-threshold')?.value || '0.72'),
        ssm_alert_cooldown_seconds: parseInt($('nw-ssm-alert-cooldown')?.value || '60'),
        use_cyber_agent_flow_data: Boolean($('nw-use-caf-data')?.checked),
      };
    }
    return {
      watch_mode: 'timer',
      timer_interval: parseInt($('watcher-timer-interval')?.value || '60'),
      timer_span: $('watcher-timer-span')?.value || 'all',
      max_context_chars: maxContext,
      use_cyber_agent_flow_data: Boolean($('watcher-periodic-use-caf-data')?.checked),
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
      _modelSsmCompatibility = new Map();
      sel.innerHTML = data.models.map((m) => {
        const val = typeof m === 'string' ? m : m.id;
        const lbl = typeof m === 'string' ? m : m.label;
        const compatibility = typeof m === 'string' ? null : m.ssm_compatibility;
        if (compatibility) _modelSsmCompatibility.set(val, compatibility);
        const suffix = compatibility ? ` · SSM: ${compatibility.label}` : '';
        return `<option value="${_esc(val)}">${_esc(`${lbl}${suffix}`)}</option>`;
      }).join('');
      sel.disabled = false;
      let savedModel = null;
      try {
        const raw = localStorage.getItem(SETTINGS_KEY);
        if (raw) savedModel = JSON.parse(raw).model;
      } catch {}

      if (savedModel && [...sel.options].some((o) => o.value === savedModel)) {
        sel.value = savedModel;
      } else if (_sessionMeta?.model && [...sel.options].some((o) => o.value === _sessionMeta.model)) {
        sel.value = _sessionMeta.model;
      }
      _saveFormSettings();
      _updateStartBtnState();
      _updateSameLlmIndicator();
      _renderSsmCompatibility();
    } catch (err) {
      if (errEl) { errEl.textContent = err.message; errEl.style.display = ''; }
    } finally {
      btn.disabled = false;
      btn.querySelector('i')?.classList.remove('spin');
    }
  }

  // ─── Status UI updater ──────────────────────────────────────────────────
  function _setStatus(running, overrideMsg = null, meta = null, isNw = false) {
    if (isNw) {
      _isNwRunning = running;
    } else {
      _isRunning = running;
    }

    const btn = $('watcher-start-btn');
    const badge = $('watcher-status-badge');
    const txt = $('watcher-status-text');
    const lbl = $('watcher-start-btn-label');
    const icn = $('watcher-start-btn-icon');

    if (btn) btn.disabled = false;

    // We only show running state if the active mode matches the running watcher type
    const activeIsNw = _currentMode === 'network';
    const showRunning = activeIsNw ? _isNwRunning : _isRunning;

    if (showRunning) {
      if (lbl) lbl.textContent = 'Stop Watcher';
      if (icn) icn.innerHTML = '⏹';
      if (btn) { btn.classList.remove('btn-primary'); btn.classList.add('btn-danger'); }
      if (badge) { badge.classList.remove('watcher-status-idle'); badge.classList.add('watcher-status-active'); }
      if (txt) txt.textContent = overrideMsg || `Watching (${meta?.watching_mode || _currentMode} mode)`;
    } else {
      if (lbl) lbl.textContent = 'Start Watcher';
      if (icn) icn.innerHTML = '▶';
      if (btn) { btn.classList.remove('btn-danger'); btn.classList.add('btn-primary'); }
      if (badge) { badge.classList.remove('watcher-status-active'); badge.classList.add('watcher-status-idle'); }
      if (txt) txt.textContent = overrideMsg || 'Idle — not watching';
    }
  };

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
  function _showWatcherStartError(message, localSsm = false) {
    const error = localSsm ? $('nw-ssm-start-error') : $('watcher-fetch-error');
    if (!error) return;
    error.textContent = message;
    error.style.display = '';
  }

  async function _toggleWatcher() {
    const btn = $('watcher-start-btn');
    if (!btn) return;
    btn.disabled = true;

    const isNwMode = _currentMode === 'network';
    const running = isNwMode ? _isNwRunning : _isRunning;

    if (running) {
      if (isNwMode) {
        try { await fetch('/api/network_watcher/stop', { method: 'POST' }); } catch {}
        _setStatus(false, 'Idle — not watching', null, true);
        _stopNwStatusPoll();
        const nwLiveLog = $('nw-live-log');
        if (nwLiveLog) nwLiveLog.innerHTML += '<div style="color: var(--text-muted);">Watcher stopped.</div>';
        const nwViewSsmBtn = $('nw-view-ssm-btn');
        if (nwViewSsmBtn) nwViewSsmBtn.style.display = 'none';
      } else {
        try { await fetch('/api/watcher/stop', { method: 'POST' }); } catch {}
        _setStatus(false, 'Idle — not watching', null, false);
        _stopStatusPoll();
      }
    } else {
      const url = ($('watcher-url-input')?.value || '').trim();
      const model = $('watcher-model-select')?.value || '';
      const provider = $('watcher-provider-select')?.value || 'ollama_direct';
      const apiKey = $('watcher-api-key-input')?.value?.trim() || '';
      const ssl = $('watcher-ssl-toggle')?.checked !== false;
      const modeConfig = _getModeConfig();

      const localSsm = isNwMode && modeConfig.analysis_engine === 'llamacpp_ssm';
      if (localSsm && !modeConfig.ssm_model_path) { _showWatcherStartError('Enter the local recurrent GGUF model path first.', true); btn.disabled = false; return; }
      if (!localSsm && !model) { _showWatcherStartError('Select a model first.'); btn.disabled = false; return; }
      if (!isNwMode && !modeConfig.use_cyber_agent_flow_data) { _showWatcherStartError('Enable Use CyberAgentFlow data before starting periodic analysis.'); btn.disabled = false; return; }
      const errEl = $('watcher-fetch-error');
      if (errEl) errEl.style.display = 'none';
      const ssmErrEl = $('nw-ssm-start-error');
      if (ssmErrEl) ssmErrEl.style.display = 'none';

      try {
        const isNwMode = _currentMode === 'network';
        const timeout = parseInt($('watcher-timeout-select')?.value || '60');
        const systemPrompt = $('watcher-system-prompt')?.value || '';
        let requestBody = { url, model, provider, api_key: apiKey, ssl_verify: ssl, timeout, system_prompt: systemPrompt, ...modeConfig };
        if (isNwMode) {
          const cbs = document.querySelectorAll('.nw-iface-cb:checked');
          requestBody.interfaces = modeConfig.capture_source === 'python' ? Array.from(cbs).map(cb => cb.value) : [];
        }

        const res = await fetch(isNwMode ? '/api/network_watcher/start' : '/api/watcher/start', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(requestBody),
        });
        const data = await res.json();
        if (!data.success) {
          _showWatcherStartError(data.error || 'Failed to start.', localSsm);
          btn.disabled = false; return;
        }

        if (isNwMode) {
          _setStatus(true, null, { watching_mode: 'network', model: localSsm ? 'Local llama.cpp SSM' : model }, true);
          _startNwStatusPoll();
          const nwLiveLog = $('nw-live-log');
          if (nwLiveLog) nwLiveLog.innerHTML = '<div style="color: var(--text-muted);">Watcher started. Listening for packets...</div>';
          const nwViewSsmBtn = $('nw-view-ssm-btn');
          if (nwViewSsmBtn) nwViewSsmBtn.style.display = 'inline-flex';
        } else {
          _setStatus(true, null, {
            watching_mode: data.watching_mode,
            model: model,
            using_session_llm: data.using_session_llm
          }, false);
          _startStatusPoll();
        }

        // A successful start always opens the live metrics view.
        switchWatcherTab('metrics');
      } catch (err) {
        _showWatcherStartError(err.message, localSsm);
        btn.disabled = false;
      }
    }
  }

  // ─── Status polling ───────────────────────────────────────────────────────
  function _updateBtnUI() {
    const activeIsNw = _currentMode === 'network';
    const running = activeIsNw ? _isNwRunning : _isRunning;
    _setStatus(running, null, null, activeIsNw);
  }

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

  function _formatInteractionTimestamp(timestamp) {
    const date = new Date(timestamp);
    return Number.isNaN(date.getTime()) ? (timestamp || '') : date.toLocaleString();
  }

  function _formattedNwResponse(entry) {
    if (entry.analysis) return entry.analysis;
    if (entry.outcome === 'pending') return 'Awaiting the model response…';
    if (entry.engine === 'llamacpp_ssm' && entry.error) return `SSM runtime failed: ${entry.error}`;
    try {
      const parsed = JSON.parse(entry.response || '{}');
      const content = parsed?.choices?.[0]?.message?.content || parsed?.message?.content;
      if (content) return content;
      const error = parsed?.error?.message || parsed?.message;
      if (error) return `Model request failed: ${error}`;
    } catch {}
    if (entry.error) return `Model request failed: ${entry.error}`;
    return entry.response || 'No findings reported for this packet batch.';
  }

  function _nwFindingEntries(interactions) {
    // A stream produces an observation for every decoded packet. Keep the
    // findings panel useful by retaining its newest observation per flow (and
    // its newest error per flow), while preserving all non-stream findings.
    const entries = Array.isArray(interactions) ? interactions : [];
    const visible = [];
    const streamLatest = new Map();

    entries.forEach((entry, index) => {
      if (entry.outcome === 'pending') return;
      if (entry.engine !== 'llamacpp_ssm') {
        visible.push({ entry, index });
        return;
      }

      const flow = entry.request?.flow || 'unknown flow';
      const kind = entry.outcome === 'success' ? 'observation' : 'error';
      streamLatest.set(`${kind}:${flow}`, { entry, index });
    });

    return visible.concat([...streamLatest.values()])
      .sort((left, right) => left.index - right.index)
      .map(({ entry }) => entry);
  }

  function _renderNwFindings(interactions) {
    const list = $('nw-findings-list');
    const empty = $('nw-findings-empty');
    const count = $('nw-findings-count');
    if (!list || !empty || !count) return;

    const findings = _nwFindingEntries(interactions);
    count.textContent = findings.length ? `(${findings.length})` : '';
    empty.style.display = findings.length ? 'none' : '';
    list.replaceChildren();

    findings.slice().reverse().forEach((entry) => {
      const card = document.createElement('article');
      const isError = entry.outcome !== 'success';
      card.style.cssText = `padding:0.75rem 0.85rem; border:1px solid ${isError ? 'var(--error)' : 'var(--border-subtle)'}; border-left-width:3px; border-radius:6px; background:var(--bg-surface-2);`;

      const header = document.createElement('div');
      header.style.cssText = 'display:flex; justify-content:space-between; gap:0.75rem; flex-wrap:wrap; margin-bottom:0.4rem; font-size:0.78rem; color:var(--text-secondary);';
      const flow = entry.engine === 'llamacpp_ssm' ? entry.request?.flow : null;
      header.textContent = `${_formatInteractionTimestamp(entry.timestamp)} · ${entry.model || 'Unknown model'}${flow ? ` · ${flow}` : ''} · ${entry.elapsed_ms ?? 0} ms${entry.http_status ? ` · HTTP ${entry.http_status}` : ''}`;

      const response = document.createElement('div');
      response.style.cssText = `white-space:pre-wrap; overflow-wrap:anywhere; font-size:0.88rem; line-height:1.5; color:${isError ? 'var(--error)' : 'var(--text-primary)'};`;
      response.textContent = _formattedNwResponse(entry);
      card.append(header, response);
      list.appendChild(card);
    });
  }

  function _renderNwInteractions(interactions) {
    const list = $('nw-interactions-list');
    const empty = $('nw-interactions-empty');
    const count = $('nw-interactions-count');
    if (!list || !empty || !count) return;

    const records = Array.isArray(interactions) ? interactions : [];
    _renderNwFindings(records);
    count.textContent = records.length ? `(${records.length})` : '';
    empty.style.display = records.length ? 'none' : '';
    list.replaceChildren();

    records.slice().reverse().forEach((entry) => {
      const record = document.createElement('article');
      record.style.cssText = 'border:1px solid var(--border-subtle); border-radius:6px; overflow:hidden; background:var(--bg-surface-2);';

      const header = document.createElement('div');
      header.style.cssText = 'padding:0.55rem 0.7rem; font-size:0.78rem; border-bottom:1px solid var(--border-subtle); color:var(--text-secondary);';
      const status = entry.outcome === 'pending' ? 'Sending to model…' : (entry.outcome === 'success' ? 'Completed' : (entry.outcome === 'http_error' ? 'HTTP error' : 'Request failed'));
      const timing = entry.elapsed_ms == null ? 'In progress' : `${entry.elapsed_ms} ms`;
      header.textContent = `${_formatInteractionTimestamp(entry.timestamp)} · ${entry.model || 'Unknown model'} · ${timing} · ${status}${entry.http_status ? ` (${entry.http_status})` : ''}`;

      const { messages, ...requestMeta } = entry.request || {};
      const meta = document.createElement('div');
      meta.style.cssText = 'padding:0.55rem 0.7rem 0; font-family:var(--font-mono); font-size:0.75rem; color:var(--text-secondary); overflow-wrap:anywhere;';
      meta.textContent = `Endpoint: ${entry.endpoint || '—'} · Request: ${JSON.stringify(requestMeta)}`;

      const promptLabel = document.createElement('div');
      promptLabel.style.cssText = 'padding:0.55rem 0.7rem 0.25rem; font-weight:600; font-size:0.8rem;';
      promptLabel.textContent = entry.engine === 'llamacpp_ssm' ? 'Normalized stream event' : 'Prompt';
      const prompt = document.createElement('pre');
      prompt.style.cssText = 'margin:0 0.7rem 0.6rem; max-height:14rem; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; font:0.76rem/1.45 var(--font-mono); color:var(--text-secondary);';
      prompt.textContent = entry.engine === 'llamacpp_ssm' ? JSON.stringify(entry.request || {}, null, 2) : (entry.prompt || '');

      const responseLabel = document.createElement('div');
      responseLabel.style.cssText = 'padding:0 0.7rem 0.25rem; font-weight:600; font-size:0.8rem;';
      responseLabel.textContent = entry.engine === 'llamacpp_ssm' ? (entry.error ? 'Runtime error' : 'Score result') : (entry.error ? 'Response / Error' : 'Raw response');
      const response = document.createElement('pre');
      response.style.cssText = 'margin:0 0.7rem 0.7rem; max-height:14rem; overflow:auto; white-space:pre-wrap; overflow-wrap:anywhere; font:0.76rem/1.45 var(--font-mono); color:var(--text-secondary);';
      response.textContent = entry.response || entry.error || '(empty response)';

      record.append(header, meta, promptLabel, prompt, responseLabel, response);
      list.appendChild(record);
    });
  }

  async function _refreshNwInteractions(revision, force = false) {
    if (!force && revision === _nwInteractionRevision) return;
    try {
      const data = await fetch('/api/network_watcher/interactions').then((r) => r.json());
      _nwInteractionRevision = data.revision;
      _renderNwInteractions(data.interactions);
    } catch (e) { console.error('NW interaction history error', e); }
  }

  async function _fetchNwStatus() {
    try {
      const res = await fetch('/api/network_watcher/status');
      const data = await res.json();
      if (data.metrics) {
        _refreshNwInteractions(data.interaction_revision);
        const cpu = $('nw-metric-cpu'); if (cpu) cpu.textContent = `${(data.metrics.cpu_percent || 0).toFixed(1)}%`;
        const mem = $('nw-metric-mem'); if (mem) mem.textContent = `${data.metrics.mem_used_mb || 0} / ${(data.metrics.mem_used_mb || 0) + (data.metrics.mem_free_mb || 0)} MB`;
        const pkts = $('nw-metric-packets'); if (pkts) pkts.textContent = (data.metrics.packets_captured || 0).toLocaleString();
        const analyzed = $('nw-metric-analyzed'); if (analyzed) analyzed.textContent = (data.metrics.packets_analyzed || 0).toLocaleString();
        const suricataSource = data.configuration?.capture_source === 'suricata_eve';
        const capturedLabel = $('nw-metric-captured-label'); if (capturedLabel) capturedLabel.textContent = suricataSource ? 'EVE Events Seen' : 'Packets Sniffed';
        const bytesLabel = $('nw-metric-bytes-label'); if (bytesLabel) bytesLabel.textContent = suricataSource ? 'EVE Data Ingested' : 'Payload Extracted';

        const bytesEl = $('nw-metric-bytes');
        if (bytesEl) {
          const b = data.metrics.bytes_extracted || 0;
          bytesEl.textContent = b < 1024 ? `${b} B` : (b < 1048576 ? `${(b/1024).toFixed(1)} KB` : `${(b/1048576).toFixed(2)} MB`);
        }

        const tokensEl = $('nw-metric-tokens'); if (tokensEl) tokensEl.textContent = (data.metrics.total_tokens || 0).toLocaleString();
        const inf = $('nw-metric-inference'); if (inf) inf.textContent = `${data.metrics.avg_inference_sec || 0} s`;
        const alertsEl = $('nw-metric-alerts'); if (alertsEl) alertsEl.textContent = data.metrics.alerts_emitted || 0;
        const runtime = data.ssm_runtime || {};
        const flowsEl = $('nw-metric-flows'); if (flowsEl) flowsEl.textContent = runtime.active_flows ?? 0;
        const scoreEl = $('nw-metric-score'); if (scoreEl) scoreEl.textContent = runtime.last_score == null ? '--' : Number(runtime.last_score).toFixed(3);

        const pulseDot = $('nw-pulse-dot');
        const statusText = $('nw-status-banner-text');
        const ifaceLabel = $('nw-status-interface-label');
        if (ifaceLabel) {
          ifaceLabel.textContent = data.configuration?.capture_source === 'suricata_eve'
            ? `Suricata EVE: ${data.configuration?.suricata_eve_path || 'eve.json'}`
            : `Interface: ${data.interface || 'en0'}`;
        }

        const bpfAlert = $('nw-bpf-alert');
        if (data.bpf_permission_ok === false || data.capture_error) {
          if (bpfAlert) bpfAlert.style.display = 'block';
        } else if (bpfAlert) {
          bpfAlert.style.display = 'none';
        }

        const isRunning = Boolean(data.running);
        _setStatus(isRunning, isRunning ? 'Watching network packets...' : 'Idle — not watching', null, true);
        if (isRunning) {
          if (pulseDot) { pulseDot.style.background = 'var(--success)'; pulseDot.style.boxShadow = '0 0 8px var(--success)'; }
          if (statusText) statusText.textContent = 'Watching Network Packets';
          const nwViewSsmBtn = $('nw-view-ssm-btn');
          if (nwViewSsmBtn) nwViewSsmBtn.style.display = 'inline-flex';
        } else {
          if (pulseDot) { pulseDot.style.background = 'var(--text-muted)'; pulseDot.style.boxShadow = 'none'; }
          if (statusText) statusText.textContent = 'Network Watcher Idle';
        }
      }
    } catch (e) { console.error('NW Polling error', e); }
  }

  function _startNwStatusPoll() {
    if (_nwStatusPollInterval) return;
    _fetchNwStatus();
    _nwStatusPollInterval = setInterval(_fetchNwStatus, 1500);
  }
  function _stopNwStatusPoll() {
    if (_nwStatusPollInterval) { clearInterval(_nwStatusPollInterval); _nwStatusPollInterval = null; }
    const cpu = $('nw-metric-cpu'); if (cpu) cpu.textContent = '--%';
    const mem = $('nw-metric-mem'); if (mem) mem.textContent = '-- / -- MB';
    const pkts = $('nw-metric-packets'); if (pkts) pkts.textContent = '0';
    const analyzed = $('nw-metric-analyzed'); if (analyzed) analyzed.textContent = '0';
    const bytesEl = $('nw-metric-bytes'); if (bytesEl) bytesEl.textContent = '0 KB';
    const tokensEl = $('nw-metric-tokens'); if (tokensEl) tokensEl.textContent = '0';
    const inf = $('nw-metric-inference'); if (inf) inf.textContent = '-- s';
    const alertsEl = $('nw-metric-alerts'); if (alertsEl) alertsEl.textContent = '0';
    const flowsEl = $('nw-metric-flows'); if (flowsEl) flowsEl.textContent = '0';
    const scoreEl = $('nw-metric-score'); if (scoreEl) scoreEl.textContent = '--';
    const pulseDot = $('nw-pulse-dot'); if (pulseDot) { pulseDot.style.background = 'var(--text-muted)'; pulseDot.style.boxShadow = 'none'; }
    const statusText = $('nw-status-banner-text'); if (statusText) statusText.textContent = 'Network Watcher Idle';
    _nwInteractionRevision = null;
  }

  function _updateSessionNotice() {
    const notice = $('watcher-no-session-notice');
    if (!notice) return;
    if (_currentMode === 'network') {
      notice.style.display = 'none';
    } else {
      notice.style.display = _cyberAgentFlowDataAvailable ? 'none' : '';
    }
  }

  function _updateStartBtnState() {
    const btn = $('watcher-start-btn');
    const model = $('watcher-model-select')?.value;
    if (!btn) return;
    if (_currentMode === 'network') {
      btn.disabled = _isLocalSsmEngine() ? !($('nw-ssm-model-path')?.value || '').trim() : !model;
    } else {
      btn.disabled = !model || !_cyberAgentFlowDataAvailable || !$('watcher-periodic-use-caf-data')?.checked;
    }
  }

  function _updateMetricsView() {
    const isNw = _currentMode === 'network';
    const suggestionsView = $('watcher-view-suggestions');
    const networkView = $('watcher-view-network');

    if (suggestionsView) suggestionsView.style.display = isNw ? 'none' : 'block';
    if (networkView) {
        networkView.style.display = isNw ? 'flex' : 'none';
    }
    _updateSessionNotice();
    _updateStartBtnState();
  }

  // ─── Tab active tracking ──────────────────────────────────────────────────
  function switchWatcherTab(target) {
    const setupTabBtn = $('watcher-setup-tab-btn');
    const metricsTabBtn = $('watcher-metrics-tab-btn');
    const setupPanel = $('watcher-setup-panel');
    const metricsPanel = $('watcher-metrics-panel');

    if (!setupTabBtn || !metricsTabBtn || !setupPanel || !metricsPanel) {
      console.warn('Watcher tab elements missing:', {setupTabBtn, metricsTabBtn, setupPanel, metricsPanel});
      return;
    }

    // Toggle tab button active state
    setupTabBtn.classList.toggle('active', target === 'setup');
    metricsTabBtn.classList.toggle('active', target !== 'setup');

    // Toggle panel active class — CSS rules control display via .watcher-subtab-panel / .watcher-subtab-panel.active
    setupPanel.classList.toggle('active', target === 'setup');
    metricsPanel.classList.toggle('active', target !== 'setup');

    // Remove any leftover inline display styles that could conflict with CSS class rules
    setupPanel.style.removeProperty('display');
    metricsPanel.style.removeProperty('display');

    if (target !== 'setup') {
        _updateMetricsView();
    }
  }

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
    _cyberAgentFlowDataAvailable = true;
    _prefillFromSession();
    _updateSameLlmIndicator();
    _updateSessionNotice();
    _updateStartBtnState();
    _updateCyberAgentFlowDataControls();
  }

  function handleSessionStopped() {
    if (_isRunning) { _setStatus(false, 'Idle — session ended'); _stopStatusPoll(); }
    _sessionMeta = null;
    _cyberAgentFlowDataAvailable = false;
    _updateSessionNotice();
    _updateStartBtnState();
    _updateCyberAgentFlowDataControls();
  }

  // ─── Init ────────────────────────────────────────────────────────────────
  function init() {
    _load();
    _initModeToggle();

    $('watcher-setup-tab-btn')?.addEventListener('click', () => switchWatcherTab('setup'));
    $('watcher-metrics-tab-btn')?.addEventListener('click', () => switchWatcherTab('metrics'));

    const ssmModalOverlay = $('nw-ssm-modal-overlay');
    const ssmTriggerBtn = $('nw-view-ssm-btn');
    const ssmCloseBtn = $('close-nw-ssm-btn');

    if (ssmTriggerBtn) {
        ssmTriggerBtn.addEventListener('click', () => {
            window.open('/network_watcher/live_results', 'LiveSSMResults', 'width=960,height=650,resizable=yes,scrollbars=yes');
        });
    }
    if (ssmCloseBtn && ssmModalOverlay) {
        ssmCloseBtn.addEventListener('click', () => ssmModalOverlay.style.display = 'none');
    }

    $('nw-clear-interactions-btn')?.addEventListener('click', async (event) => {
      // The button lives in a <summary>; keep clearing it from toggling the
      // collapsed diagnostics panel.
      event.preventDefault();
      event.stopPropagation();
      try {
        const data = await fetch('/api/network_watcher/interactions', { method: 'POST' }).then((r) => r.json());
        _nwInteractionRevision = data.revision;
        _renderNwInteractions(data.interactions);
      } catch (e) { console.error('Could not clear NW interaction history', e); }
    });

    $('watcher-fetch-models-btn')?.addEventListener('click', _fetchModels);
    $('watcher-url-input')?.addEventListener('input', () => {
      _updateSameLlmIndicator();
      _saveFormSettings();
    });
    $('watcher-system-prompt')?.addEventListener('input', _saveFormSettings);
    $('watcher-reset-prompt-btn')?.addEventListener('click', () => {
      _customPrompts[_currentMode] = DEFAULT_PROMPTS[_currentMode];
      _updatePromptField();
      _saveFormSettings();
    });
    $('watcher-api-key-input')?.addEventListener('input', _saveFormSettings);
    $('watcher-ssl-toggle')?.addEventListener('change', _saveFormSettings);
    $('watcher-context-size')?.addEventListener('change', _saveFormSettings);
    $('watcher-timeout-select')?.addEventListener('change', _saveFormSettings);
    $('watcher-timer-interval')?.addEventListener('change', _saveFormSettings);
    $('watcher-timer-span')?.addEventListener('change', _saveFormSettings);
    $('watcher-periodic-use-caf-data')?.addEventListener('change', () => { _updateStartBtnState(); _saveFormSettings(); });
    $('nw-use-caf-data')?.addEventListener('change', _saveFormSettings);
    $('nw-analysis-interval')?.addEventListener('change', _saveFormSettings);
    $('nw-max-payload-bytes')?.addEventListener('change', _saveFormSettings);
    $('nw-max-packets-per-analysis')?.addEventListener('change', _saveFormSettings);
    document.querySelectorAll('.nw-packet-field-cb').forEach((checkbox) => {
      checkbox.addEventListener('change', _saveFormSettings);
    });
    $('nw-capture-source')?.addEventListener('change', () => {
      if ($('nw-capture-source')?.value === 'suricata_eve' && !_suricataStatus?.available) {
        $('nw-capture-source').value = 'python';
      }
      _updateCaptureSourceUi();
      _saveFormSettings();
    });
    $('nw-refresh-suricata-btn')?.addEventListener('click', _fetchSuricataStatus);
    $('nw-suricata-eve-path')?.addEventListener('input', _saveFormSettings);
    document.querySelectorAll('.nw-suricata-event-cb').forEach((checkbox) => {
      checkbox.addEventListener('change', _saveFormSettings);
    });
    $('nw-analysis-engine')?.addEventListener('change', () => { _updateNetworkEngineUi(); _saveFormSettings(); });
    ['nw-ssm-model-path', 'nw-ssm-gpu-layers', 'nw-ssm-context-tokens', 'nw-ssm-max-flows', 'nw-ssm-alert-threshold', 'nw-ssm-alert-cooldown'].forEach((id) => {
      $(id)?.addEventListener(id === 'nw-ssm-model-path' ? 'input' : 'change', () => { _updateStartBtnState(); _saveFormSettings(); });
    });
    $('watcher-model-select')?.addEventListener('change', () => {
      _updateSameLlmIndicator();
      _renderSsmCompatibility();
      _updateStartBtnState();
      _saveFormSettings();
    });
    $('watcher-provider-select')?.addEventListener('change', () => {
      _updateSameLlmIndicator();
      _saveFormSettings();
    });
    $('watcher-start-btn')?.addEventListener('click', _toggleWatcher);
    $('watcher-clear-all-btn')?.addEventListener('click', _clearAll);

    // Restore saved form settings
    _loadFormSettings();
    _updateNetworkEngineUi();
    _fetchSuricataStatus();
    _refreshCyberAgentFlowDataAvailability();

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

    _updateSessionNotice();
    _updateStartBtnState();

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
