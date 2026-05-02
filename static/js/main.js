document.addEventListener('DOMContentLoaded', () => {
    // ---------------------------------------------------------------
    // DOM References
    // ---------------------------------------------------------------
    const fetchBtn = document.getElementById('fetch-models-btn');
    const progressModal = document.getElementById('progress-modal-overlay');
    const progressTitle = document.getElementById('progress-title');
    const progressMsg = document.getElementById('progress-message');
    const ollamaFetchError = document.getElementById('ollama-fetch-error');
    const analysisConfigModalOverlay = document.getElementById('analysis-config-modal-overlay');
    const analysisConfigTitle = document.getElementById('analysis-config-title');
    const analysisConfigDescription = document.getElementById('analysis-config-description');
    const analysisOllamaUrlInput = document.getElementById('analysis-ollama-url');
    const analysisProviderSelect = document.getElementById('analysis-provider-select');
    const providerHelpText = document.getElementById('provider-help-text');
    const providerUrlHelpText = document.getElementById('provider-url-help-text');
    const providerApiKeyHelpText = document.getElementById('provider-api-key-help-text');
    const analysisProviderHelpText = document.getElementById('analysis-provider-help-text');
    const analysisProviderUrlHelpText = document.getElementById('analysis-provider-url-help-text');
    const analysisProviderApiKeyHelpText = document.getElementById('analysis-provider-api-key-help-text');
    const analysisApiKeyGroup = document.getElementById('analysis-api-key-group');
    const analysisModelSelect = document.getElementById('analysis-model-select');
    const analysisSpanGroup = document.getElementById('analysis-span-group');
    const analysisSpanSelect = document.getElementById('analysis-span-select');
    const analysisOutputCheckboxes = document.querySelectorAll('.analysis-output-checkbox');
    const analysisFetchBtn = document.getElementById('analysis-fetch-models-btn');
    const analysisFetchError = document.getElementById('analysis-fetch-error');
    const confirmAnalysisConfigBtn = document.getElementById('confirm-analysis-config-btn');
    const cancelAnalysisConfigBtn = document.getElementById('cancel-analysis-config-btn');
    const closeAnalysisConfigBtn = document.getElementById('close-analysis-config-btn');
    const clearSavedKeyBtn = document.getElementById('clear-saved-key-btn');
    const tokenVisibilityToggles = document.querySelectorAll('.input-visibility-toggle');
    const startBtn = document.getElementById('start-service-btn');
    const modelSelect = document.getElementById('model-select');
    const providerSelect = document.getElementById('provider-select');
    const ollamaUrlInput = document.getElementById('ollama-url');
    const sslVerifyToggle = document.getElementById('ssl-verify-toggle');
    const apiKeyGroup = document.getElementById('api-key-group');
    const apiKeyInput = document.getElementById('api-key');
    const analysisSslVerifyToggle = document.getElementById('analysis-ssl-verify-toggle');
    const analysisApiKeyInput = document.getElementById('analysis-api-key');
    const maxTurnsInput = document.getElementById('max-turns');
    const policyTargetsInput = document.getElementById('policy-targets');
    const policyEntryHint = document.getElementById('policy-entry-hint');
    const policyEntryTypeInputs = document.querySelectorAll('input[name="policy-entry-type"]');

    const kaliCommandType = document.getElementById('kali-command-type');
    const toolsConfigSection = document.getElementById('tools-config-section');
    const toolsConfigEmpty = document.getElementById('tools-config-empty');
    const configToolsTabBtn = document.getElementById('config-tools-tab-btn');

    // Keylogger references
    const keyloggerEnableToggle = document.getElementById('keylogger-enable-toggle');
    const extendedMsfPromptToggle = document.getElementById('extended-msf-prompt-toggle');
    const configSubtabBtns = document.querySelectorAll('.config-subtab-btn');
    const configSubtabPanels = document.querySelectorAll('.config-subtab-panel');

    const statusBadge = document.getElementById('status-badge');
    const statusText = statusBadge.querySelector('.status-text');
    const alertsContainer = document.getElementById('alerts-container');

    const configPanel = document.getElementById('config-panel');
    const liveLogPanel = document.getElementById('live-log-panel');
    const liveLogViewer = document.getElementById('live-log-viewer');
    const toolsBadge = document.getElementById('service-tools-badge');
    const policyBadge = document.getElementById('service-policy-badge');

    // Chat Console UI
    const chatConsoleBar = document.getElementById('chat-console-bar');
    const chatScopeSlider = document.getElementById('chat-scope-slider');
    const chatScopeEnabled = document.getElementById('chat-scope-enabled');
    const chatScopeValue = document.getElementById('chat-scope-value');
    const chatScopeHelp = document.getElementById('chat-scope-help');
    const chatUrgencySlider = document.getElementById('chat-urgency-slider');
    const chatUrgencyEnabled = document.getElementById('chat-urgency-enabled');
    const chatUrgencyValue = document.getElementById('chat-urgency-value');
    const chatUrgencyHelp = document.getElementById('chat-urgency-help');
    const chatPromptInput = document.getElementById('chat-prompt-input');
    const sendPromptBtn = document.getElementById('chat-send-btn');
    const chatTabBar = document.getElementById('chat-tab-bar');
    const chatTabsContent = document.getElementById('chat-tabs-content');
    const mainChatPanel = document.getElementById('chat-tab-main');
    const annotateBtn = document.getElementById('chat-annotate-btn');
    const annotationMenu = document.getElementById('annotation-menu');
    const annotationModalOverlay = document.getElementById('annotation-modal-overlay');
    const annotationPopup = document.getElementById('annotation-popup'); // modal container
    const closeAnnotationBtn = document.getElementById('close-annotation-btn');
    const cancelAnnotationBtn = document.getElementById('cancel-annotation-btn');
    const saveAnnotationBtn = document.getElementById('save-annotation-btn');
    const chatStopBtn = document.getElementById('chat-stop-btn');
    const confirmModalOverlay = document.getElementById('confirm-modal-overlay');
    const confirmStopBtn = document.getElementById('confirm-stop-btn');
    const confirmCancelBtn = document.getElementById('confirm-cancel-btn');
    const postToolReplyModalOverlay = document.getElementById('post-tool-reply-modal-overlay');
    const postToolReplyMessage = document.getElementById('post-tool-reply-message');
    const retryPostToolReplyBtn = document.getElementById('retry-post-tool-reply-btn');
    const cancelPostToolReplyBtn = document.getElementById('cancel-post-tool-reply-btn');
    const dangerousToolModalOverlay = document.getElementById('dangerous-tool-modal-overlay');
    const dangerousToolMessage = document.getElementById('dangerous-tool-message');
    const dangerousToolCommand = document.getElementById('dangerous-tool-command');
    const approveDangerousToolBtn = document.getElementById('approve-dangerous-tool-btn');
    const cancelDangerousToolBtn = document.getElementById('cancel-dangerous-tool-btn');
    const toolTimeoutModalOverlay = document.getElementById('tool-timeout-modal-overlay');
    const toolTimeoutMessage = document.getElementById('tool-timeout-message');
    const toolTimeoutCommand = document.getElementById('tool-timeout-command');
    const waitToolTimeoutBtn = document.getElementById('wait-tool-timeout-btn');
    const killToolTimeoutBtn = document.getElementById('kill-tool-timeout-btn');
    
    const annotationAction = document.getElementById('annotation-action');
    const annotationText = document.getElementById('annotation-text');
    const annotationTextGroup = document.getElementById('annotation-text-group');
    const annotationSpan = document.getElementById('annotation-span');
    const modalTitle = document.getElementById('modal-title');
    
    const chatDownloadBtn = document.getElementById('chat-download-btn');
    const sessionDownloadBtn = document.getElementById('session-download-btn');
    const sessionAnalyzeBtn = document.getElementById('session-analyze-btn');
    const sessionSummaryPanel = document.getElementById('session-summary-panel');
    const tabAnalysis = document.getElementById('tab-analysis');
    const analysisJobsList = document.getElementById('analysis-jobs-list');
    const analysisJobsSummary = document.getElementById('analysis-jobs-summary');
    const clearJobsBtn = document.getElementById('clear-jobs-btn');
    const btnZenMode = document.getElementById('btn-zen-mode');
    
    if (btnZenMode) {
        const svgPathCornersOut = "M152,48a8,8,0,0,1,8-8h56a8,8,0,0,1,8,8v56a8,8,0,0,1-16,0V56H160A8,8,0,0,1,152,48ZM48,104a8,8,0,0,0,16,0V56H104a8,8,0,0,0,0-16H48a8,8,0,0,0-8,8V96A8,8,0,0,0,48,104ZM208,152a8,8,0,0,0-8,8v40H160a8,8,0,0,0,0,16h56a8,8,0,0,0,8-8V160A8,8,0,0,0,208,152ZM104,208H64V160a8,8,0,0,0-16,0v56a8,8,0,0,0,8,8h56a8,8,0,0,0,0-16Z";
        const svgPathCornersIn = "M216,96a8,8,0,0,1-8,8H160a8,8,0,0,1-8-8V40a8,8,0,0,1,16,0V88h40A8,8,0,0,1,216,96ZM96,152H40a8,8,0,0,0,0,16H88v48a8,8,0,0,0,16,0V160A8,8,0,0,0,96,152ZM216,160a8,8,0,0,0-8-8H160a8,8,0,0,0-8,8v56a8,8,0,0,0,16,0V168h40A8,8,0,0,0,216,160ZM88,96V40a8,8,0,0,0-16,0V88H32a8,8,0,0,0,0,16H96a8,8,0,0,0,0-16Z";

        btnZenMode.addEventListener('click', () => {
            document.body.classList.toggle('zen-mode');
            const pathElement = btnZenMode.querySelector('path');
            if (pathElement) {
                if (document.body.classList.contains('zen-mode')) {
                    pathElement.setAttribute('d', svgPathCornersIn);
                } else {
                    pathElement.setAttribute('d', svgPathCornersOut);
                }
            }
        });
    }
    
    let _analysisCache = {};
    let _analysisJobsInterval = null;
    let _openAnalysisJobMenuId = null;
    let _analysisJobPathFilter = 'all';
    let _sessionsById = {};
    let _policyDraft = { allow: ['*'], disallow: [] };
    let _activePolicyEntryType = 'allow';
    const CHAT_SCOPE_LEVELS = [
        {
            id: 'broad',
            label: 'Broad',
            help: 'Maximize coverage. Explore the wider attack surface and identify any meaningful weakness or exposure.'
        },
        {
            id: 'medium-broad',
            label: 'Medium-Broad',
            help: 'Keep good coverage across adjacent surfaces while still prioritizing the strongest leads.'
        },
        {
            id: 'medium',
            label: 'Medium',
            help: 'Balanced breadth and depth. Explore enough surface to avoid blind spots, then follow the strongest path.'
        },
        {
            id: 'medium-narrow',
            label: 'Medium-Narrow',
            help: 'Stay focused on the most promising paths and avoid unnecessary side exploration.'
        },
        {
            id: 'narrow',
            label: 'Narrow',
            help: 'Pursue the most promising route to at least one viable foothold with minimal lateral exploration.'
        }
    ];
    const CHAT_URGENCY_LEVELS = [
        {
            id: 'stealthy',
            label: 'Stealthy',
            help: 'Prefer quieter, lower-noise commands. Bias toward slower timing, smaller batches, and deeper verification before escalating.'
        },
        {
            id: 'methodical',
            label: 'Methodical',
            help: 'Stay cautious and thorough. Keep parallelism limited, avoid aggressive timing unless justified, and validate findings before broadening.'
        },
        {
            id: 'balanced',
            label: 'Balanced',
            help: 'Balanced pace. Trade off stealth, depth, timing, and parallelism without pushing too hard in either direction.'
        },
        {
            id: 'fast',
            label: 'Fast',
            help: 'Bias toward quicker feedback. Use more assertive timing, parallelism, and shallower confirmation when that improves iteration speed.'
        },
        {
            id: 'speed',
            label: 'Speed',
            help: 'Optimize for speed. Prefer aggressive but still safe timing and concurrency to get answers quickly, accepting more noise and less depth.'
        }
    ];

    let _eventSource = null;
    let _serviceRunning = false;
    let _chatBusy = false;
    let _activeToolEntry = null;
    let _logInitialCleared = false;
    let _toolTimelineCounter = 0;

    function getChatScopeIndex() {
        const rawValue = Number.parseInt(chatScopeSlider?.value ?? '2', 10);
        if (Number.isNaN(rawValue)) {
            return 2;
        }
        return Math.max(0, Math.min(CHAT_SCOPE_LEVELS.length - 1, rawValue));
    }

    function getChatScopeConfig() {
        return CHAT_SCOPE_LEVELS[getChatScopeIndex()] || CHAT_SCOPE_LEVELS[2];
    }

    function isChatScopeEnabled() {
        return chatScopeEnabled?.checked !== false;
    }

    function updateChatScopeUi() {
        const scope = getChatScopeConfig();
        const enabled = isChatScopeEnabled();
        const scopeContainer = chatScopeSlider?.closest('.chat-scope-control');
        if (chatScopeValue) {
            chatScopeValue.textContent = enabled ? scope.label : 'Off';
        }
        if (chatScopeHelp) {
            chatScopeHelp.textContent = enabled
                ? scope.help
                : 'Scope guidance is disabled for this prompt. No extra breadth/depth instruction will be appended.';
        }
        if (chatScopeEnabled) {
            const toggleText = chatScopeEnabled.closest('.chat-control-toggle')?.querySelector('span');
            if (toggleText) {
                toggleText.textContent = enabled ? 'On' : 'Off';
            }
            chatScopeEnabled.disabled = !_serviceRunning;
        }
        if (chatScopeSlider) {
            chatScopeSlider.disabled = !_serviceRunning || !enabled;
        }
        if (scopeContainer) {
            scopeContainer.classList.toggle('control-disabled', !enabled);
        }
    }

    function getChatUrgencyIndex() {
        const rawValue = Number.parseInt(chatUrgencySlider?.value ?? '2', 10);
        if (Number.isNaN(rawValue)) {
            return 2;
        }
        return Math.max(0, Math.min(CHAT_URGENCY_LEVELS.length - 1, rawValue));
    }

    function getChatUrgencyConfig() {
        return CHAT_URGENCY_LEVELS[getChatUrgencyIndex()] || CHAT_URGENCY_LEVELS[2];
    }

    function isChatUrgencyEnabled() {
        return chatUrgencyEnabled?.checked !== false;
    }

    function updateChatUrgencyUi() {
        const urgency = getChatUrgencyConfig();
        const enabled = isChatUrgencyEnabled();
        const urgencyContainer = chatUrgencySlider?.closest('.chat-scope-control');
        if (chatUrgencyValue) {
            chatUrgencyValue.textContent = enabled ? urgency.label : 'Off';
        }
        if (chatUrgencyHelp) {
            chatUrgencyHelp.textContent = enabled
                ? urgency.help
                : 'Urgency guidance is disabled for this prompt. No extra timing or tempo instruction will be appended.';
        }
        if (chatUrgencyEnabled) {
            const toggleText = chatUrgencyEnabled.closest('.chat-control-toggle')?.querySelector('span');
            if (toggleText) {
                toggleText.textContent = enabled ? 'On' : 'Off';
            }
            chatUrgencyEnabled.disabled = !_serviceRunning;
        }
        if (chatUrgencySlider) {
            chatUrgencySlider.disabled = !_serviceRunning || !enabled;
        }
        if (urgencyContainer) {
            urgencyContainer.classList.toggle('control-disabled', !enabled);
        }
    }

    function updateChatControlAvailability() {
        updateChatScopeUi();
        updateChatUrgencyUi();
    }
    let _sessionToStopId = null;
    let _currentRunId = null;
    let _awaitingPostToolReplyDecision = false;
    let _awaitingDangerousToolApproval = false;
    let _awaitingToolTimeoutDecision = false;
    let _activeToolState = null;
    let _activeToolTicker = null;
    const LIVE_LOG_STORAGE_PREFIX = 'live-log:';
    const LAST_ACTIVE_RUN_STORAGE_KEY = 'live-log:last-active-run';
    const LAST_SETTINGS_STORAGE_KEY = 'runtime:last-settings:v2';
    const LAST_SETTINGS_SESSION_STORAGE_KEY = 'runtime:last-settings:session:v2';
    const API_KEY_SESSION_STORAGE_KEY = 'runtime:llm-api-key';
    const LEGACY_API_TOKEN_SESSION_STORAGE_KEY = 'runtime:llm-api-token';
    const MAX_PERSISTED_LIVE_LOG_HTML = 200000;
    const MAX_LIVE_LOG_ENTRIES = 25;
    let _analysisConfigResolver = null;
    let _analysisConfigOptions = null;
    const DEFAULT_ANALYSIS_OUTPUTS = ['tooling_assets', 'progress_analysis'];
    const PROVIDERS = {
        OLLAMA_DIRECT: 'ollama_direct',
        LITELLM: 'litellm',
        OPENAI: 'openai',
        CLAUDE: 'claude',
    };
    
    // SVG Templates
    const ICON_SVG = {
        POWER: `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" fill="currentColor" viewBox="0 0 256 256"><path d="M128,24a8,8,0,0,1,8,8v80a8,8,0,0,1-16,0V32A8,8,0,0,1,128,24ZM198.63,62.63a8,8,0,0,0-11.26,11.4c26.46,26.11,26.46,68.63,0,94.74a67,67,0,0,1-94.74,0c-26.46-26.11-26.46-68.63,0-94.74a8,8,0,0,0-11.26-11.4c-32.73,32.31-32.73,84.89,0,117.2a83,83,0,0,0,117.26,0C231.36,147.52,231.36,94.94,198.63,62.63Z"></path></svg>`,
        STOP: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="currentColor" viewBox="0 0 256 256"><path d="M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,128,24Zm0,192a88,88,0,1,1,88-88A88.1,88.1,0,0,1,128,216ZM160,104v48a8,8,0,0,1-8,8H104a8,8,0,0,1-8-8V104a8,8,0,0,1,8-8h48A8,8,0,0,1,160,104Z"></path></svg>`,
        SEND: `<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" fill="currentColor" viewBox="0 0 256 256"><path d="M231.87,114l-168-104A16,16,0,0,0,40.92,37.32L71.55,112H136a8,8,0,0,1,0,16H71.55L40.92,202.68A16,16,0,0,0,63.87,222a15.88,15.88,0,0,0,10-3.51l168-104a16,16,0,0,0,0-27.18Z"></path></svg>`,
        SPINNER: `<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20" fill="currentColor" viewBox="0 0 256 256" class="spinning"><path d="M136,32v40a8,8,0,0,1-16,0V32a8,8,0,0,1,16,0Z"></path><path d="M128,24A104,104,0,1,0,232,128,104.11,104.11,0,0,0,128,24Zm0,192a88,88,0,1,1,88-88A88.1,88.1,0,0,1,128,216Z" opacity="0.3"></path></svg>`
    };

    // ---------------------------------------------------------------
    // Vertical Tab Navigation
    // ---------------------------------------------------------------
    const navBtns = document.querySelectorAll('.nav-btn');
    const tabPanes = document.querySelectorAll('.tab-pane');
    const navChatBtn = document.getElementById('nav-chat-btn');

    function switchTab(targetPaneId) {
        // Update nav buttons
        navBtns.forEach(btn => {
            if (btn.getAttribute('data-target') === targetPaneId) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });
        // Show target pane
        tabPanes.forEach(pane => {
            if (pane.id === targetPaneId) {
                pane.classList.add('active');
            } else {
                pane.classList.remove('active');
            }
        });
    }

    navBtns.forEach(btn => {
        btn.addEventListener('click', () => {
            if (btn.disabled) return;
            const targetId = btn.getAttribute('data-target');
            switchTab(targetId);
            
            // Handle analysis polling
            if (targetId === 'analysis-pane') {
                loadAnalysisJobs();
                startAnalysisJobsPolling();
            } else {
                stopAnalysisJobsPolling();
            }
        });
    });

    function switchConfigSubtab(targetPanelId) {
        configSubtabBtns.forEach(btn => {
            btn.classList.toggle('active', btn.dataset.configTarget === targetPanelId);
        });
        configSubtabPanels.forEach(panel => {
            panel.classList.toggle('active', panel.id === targetPanelId);
        });
    }

    configSubtabBtns.forEach(btn => {
        btn.addEventListener('click', () => switchConfigSubtab(btn.dataset.configTarget));
    });

    // Toggle tools config visibility
    kaliCommandType.addEventListener('change', (e) => {
        const usesApt = e.target.value === 'apt';
        toolsConfigSection.style.display = usesApt ? 'none' : 'flex';
        toolsConfigEmpty.style.display = usesApt ? 'flex' : 'none';
        configToolsTabBtn.classList.toggle('config-subtab-btn-muted', usesApt);
    });
    kaliCommandType.dispatchEvent(new Event('change'));

    // ---------------------------------------------------------------
    // Utility Alerts & Status
    // ---------------------------------------------------------------
    const showAlert = (message, type = 'error') => {
        const alertEl = document.createElement('div');
        alertEl.className = `alert alert-${type}`;
        const icon = type === 'error' ? 'ph-warning-circle' : 'ph-check-circle';
        alertEl.innerHTML = `<i class="ph ${icon}"></i> <span>${message}</span>`;
        alertsContainer.innerHTML = '';
        alertsContainer.appendChild(alertEl);
        setTimeout(() => {
            alertEl.style.opacity = '0';
            setTimeout(() => alertEl.remove(), 300);
        }, 5000);
    };

    const updateStatus = (state, message) => {
        statusBadge.classList.remove('hidden', 'success', 'error', 'running');
        if (state === 'success') {
            statusBadge.classList.add('success');
            statusText.textContent = message || 'Completed';
        } else if (state === 'error') {
            statusBadge.classList.add('error');
            statusText.textContent = message || 'Error';
        } else if (state === 'running') {
            statusBadge.classList.add('running');
            statusText.textContent = message || 'Running…';
        } else {
            statusText.textContent = message || 'Idle';
        }
    };

    // ---------------------------------------------------------------
    // Tools Config JSON
    // ---------------------------------------------------------------
    const toolCheckboxes = document.querySelectorAll('.tool-checkbox');
    const shellExtendedCheckbox = document.querySelector('.tool-checkbox[value="shell_extended"]');
    const shellSequenceCheckbox = document.querySelector('.tool-checkbox[value="shell_sequence"]');
    const toolsJsonArea = document.getElementById('kali-tools-json');

    function buildSelectedToolsConfig() {
        const selectedTools = [];
        const shellExtendedEnabled = Boolean(shellExtendedCheckbox?.checked);

        toolCheckboxes.forEach(cb => {
            if (!cb.checked) {
                return;
            }

            const name = cb.value;
            const cmd = cb.dataset.cmd;
            let toolDefinition;

            if (name === 'msf_search') {
                toolDefinition = {
                    name: "msf_search",
                    description: "Search for Metasploit modules by keyword (e.g., 'jboss').",
                    command: "msfconsole",
                    base_args: ["-q", "-x", "search {args}; exit"],
                    allow_args: true
                };
            } else if (name === 'msf_run') {
                toolDefinition = {
                    name: "msf_run",
                    description: "Execute a Metasploit command sequence in batch mode. Example: 'use auxiliary/scanner/http/jboss_vulnscan; set RHOSTS 10.0.2.2; run'. Exploit modules get a short default WfsDelay and preserved interactive-session handling when a real session opens, unless you override the workflow manually.",
                    command: "msfconsole",
                    base_args: ["-q", "-x", "{args}; exit"],
                    timeout_seconds: 90,
                    interactive_capable: true,
                    allow_args: true
                };
            } else if (name === 'proxychains') {
                toolDefinition = {
                    name: 'proxychains',
                    description: 'Run a network command through proxychains. Example args: "nmap -sT scanme.nmap.org" or "curl http://example.com".',
                    command: cmd,
                    args: ['{args}'],
                    allow_args: true
                };
            } else if (name === 'ssh') {
                toolDefinition = {
                    name: 'ssh',
                    description: 'Open an SSH client connection or run a remote command. Example args: "user@host" or "user@host uname -a".',
                    command: cmd,
                    args: ['{args}'],
                    allow_args: true
                };
            } else if (name === 'shell') {
                toolDefinition = {
                    name: 'shell',
                    description: 'Run an allowlisted local shell command for host inspection. Allowed commands: ls, cat, grep, docker, ip, ss, ps, uname, id, pwd, whoami, find.',
                    command: cmd,
                    args: ['{args}'],
                    allow_args: true
                };
            } else if (name === 'shell_extended') {
                toolDefinition = {
                    name: 'shell_extended',
                    description: 'Run an extended allowlisted shell command for read-oriented network inspection. Allowed commands: curl, dig, host, nslookup, openssl s_client, tracepath, traceroute, ping. curl is restricted to read-only HTTP(S) requests, openssl is limited to s_client, and ping is count-limited.',
                    command: cmd,
                    args: ['{args}'],
                    timeout_seconds: 90,
                    allow_args: true
                };
            } else if (name === 'shell_sequence') {
                if (!shellExtendedEnabled) {
                    return;
                }
                toolDefinition = {
                    name: 'shell_sequence',
                    description: 'Run up to 3 shell_extended-compatible commands in sequence without a shell interpreter. Args must be either a JSON array of command strings or newline-separated commands. Each command is validated under shell_extended rules before execution.',
                    command: cmd,
                    args: ['{args}'],
                    timeout_seconds: 120,
                    allow_args: true
                };
            } else if (name === 'shell_dangerous') {
                toolDefinition = {
                    name: 'shell_dangerous',
                    description: 'Run a much less restricted shell command for advanced workflows, including file edits, redirection, and multi-step shell logic. Every execution requires explicit user approval before the command is run.',
                    command: cmd,
                    args: ['{args}'],
                    timeout_seconds: 120,
                    allow_args: true
                };
            } else if (name === 'interactive_session_list') {
                toolDefinition = {
                    name: "interactive_session_list",
                    description: "List preserved interactive sessions created by prior tool calls, such as a Meterpreter or Metasploit console session.",
                    command: "builtin"
                };
            } else if (name === 'interactive_session_read') {
                toolDefinition = {
                    name: "interactive_session_read",
                    description: "Read newly available output from a preserved interactive session.",
                    command: "builtin",
                    allow_args: true
                };
            } else if (name === 'interactive_session_write') {
                toolDefinition = {
                    name: "interactive_session_write",
                    description: "Send a command to a preserved interactive session and return any resulting output.",
                    command: "builtin",
                    allow_args: true
                };
            } else if (name === 'interactive_session_close') {
                toolDefinition = {
                    name: "interactive_session_close",
                    description: "Terminate a preserved interactive session and return any final buffered output.",
                    command: "builtin",
                    allow_args: true
                };
            } else {
                toolDefinition = { name: name, command: cmd, args: ["{args}"], allow_args: true };
            }

            selectedTools.push(toolDefinition);
        });

        return { tools: selectedTools };
    }

    function persistLastSettings() {
        try {
            syncPolicyDraftFromEditor();
            const selectedModelOption = modelSelect?.selectedOptions?.[0] || null;
            const toolCheckboxStates = {};
            toolCheckboxes.forEach(cb => {
                toolCheckboxStates[cb.value] = Boolean(cb.checked);
            });

            const payload = {
                provider: normalizeProvider(providerSelect?.value),
                url: ollamaUrlInput?.value.trim() || '',
                sslVerify: Boolean(sslVerifyToggle?.checked ?? true),
                model: modelSelect?.value || '',
                modelLabel: selectedModelOption?.textContent || '',
                contextWindow: document.getElementById('context-window')?.value || '8192',
                maxTurns: maxTurnsInput?.value || '20',
                kaliCommandType: kaliCommandType?.value || 'python',
                policyEntryType: getSelectedPolicyEntryType(),
                policyDraft: normalizePolicy(_policyDraft),
                toolCheckboxStates,
                toolsJson: toolsJsonArea?.value || '',
                extendedMsfPrompt: Boolean(extendedMsfPromptToggle?.checked),
                activeConfigSubtab: document.querySelector('.config-subtab-btn.active')?.dataset.configTarget || 'config-runtime-panel',
                savedAt: Date.now(),
            };

            const encodedPayload = JSON.stringify(payload);
            try {
                safeLocalStorageSet(LAST_SETTINGS_STORAGE_KEY, encodedPayload);
                sessionStorage.removeItem(LAST_SETTINGS_SESSION_STORAGE_KEY);
            } catch (err) {
                if (!isStorageQuotaError(err)) {
                    throw err;
                }
                sessionStorage.setItem(LAST_SETTINGS_SESSION_STORAGE_KEY, encodedPayload);
            }
        } catch (err) {
            console.warn('Failed to persist last-used settings:', err);
        }
    }

    function restoreLastSettings() {
        try {
            const raw = localStorage.getItem(LAST_SETTINGS_STORAGE_KEY)
                || sessionStorage.getItem(LAST_SETTINGS_SESSION_STORAGE_KEY);
            if (!raw) {
                return false;
            }

            const payload = JSON.parse(raw);
            if (!payload || typeof payload !== 'object') {
                return false;
            }

            const restoredProvider = normalizeProvider(payload.provider);
            if (providerSelect) {
                providerSelect.value = restoredProvider;
                providerSelect.dataset.previousProvider = restoredProvider;
            }

            if (ollamaUrlInput && payload.url) {
                ollamaUrlInput.value = String(payload.url);
            }

            if (sslVerifyToggle && typeof payload.sslVerify === 'boolean') {
                sslVerifyToggle.checked = payload.sslVerify;
            }

            const contextWindowSelect = document.getElementById('context-window');
            if (contextWindowSelect && payload.contextWindow) {
                contextWindowSelect.value = String(payload.contextWindow);
            }

            if (maxTurnsInput && payload.maxTurns) {
                maxTurnsInput.value = String(payload.maxTurns);
            }

            if (kaliCommandType && payload.kaliCommandType) {
                kaliCommandType.value = payload.kaliCommandType === 'apt' ? 'apt' : 'python';
                kaliCommandType.dispatchEvent(new Event('change'));
            }

            if (extendedMsfPromptToggle && typeof payload.extendedMsfPrompt === 'boolean') {
                extendedMsfPromptToggle.checked = payload.extendedMsfPrompt;
            }

            const toolCheckboxStates = payload.toolCheckboxStates;
            if (toolCheckboxStates && typeof toolCheckboxStates === 'object') {
                toolCheckboxes.forEach(cb => {
                    if (Object.prototype.hasOwnProperty.call(toolCheckboxStates, cb.value)) {
                        cb.checked = Boolean(toolCheckboxStates[cb.value]);
                    }
                });
            }

            updateShellSequenceDependency();

            if (toolsJsonArea) {
                if (typeof payload.toolsJson === 'string' && payload.toolsJson.trim()) {
                    toolsJsonArea.value = payload.toolsJson;
                } else {
                    updateToolsJson();
                }
            }

            if (payload.policyDraft && typeof payload.policyDraft === 'object') {
                _policyDraft = normalizePolicy(payload.policyDraft);
            }

            const policyEntryType = payload.policyEntryType === 'disallow' ? 'disallow' : 'allow';
            policyEntryTypeInputs.forEach(input => {
                input.checked = input.value === policyEntryType;
            });
            updatePolicyEntryEditor();

            if (payload.model && modelSelect) {
                const restoredOption = document.createElement('option');
                restoredOption.value = String(payload.model);
                restoredOption.textContent = String(payload.modelLabel || payload.model);
                restoredOption.selected = true;
                modelSelect.innerHTML = '';
                modelSelect.appendChild(restoredOption);
                modelSelect.disabled = false;
                startBtn.disabled = false;
            }

            if (payload.activeConfigSubtab) {
                switchConfigSubtab(payload.activeConfigSubtab);
            }

            return true;
        } catch (err) {
            console.warn('Failed to restore last-used settings:', err);
            return false;
        }
    }

    function updateShellSequenceDependency() {
        if (!shellSequenceCheckbox) {
            return;
        }

        const shellExtendedEnabled = Boolean(shellExtendedCheckbox?.checked);
        shellSequenceCheckbox.disabled = !shellExtendedEnabled;
        if (shellExtendedEnabled) {
            shellSequenceCheckbox.removeAttribute('title');
        } else {
            shellSequenceCheckbox.checked = false;
            shellSequenceCheckbox.title = 'Enable shell_extended first';
        }
    }

    function updateToolsJson() {
        const generatedConfig = buildSelectedToolsConfig();
        try {
            const currentJson = JSON.parse(toolsJsonArea.value || '{"tools": []}');
            currentJson.tools = generatedConfig.tools;
            toolsJsonArea.value = JSON.stringify(currentJson, null, 2);
        } catch (e) {
            toolsJsonArea.value = JSON.stringify(generatedConfig, null, 2);
        }
    }
    shellExtendedCheckbox?.addEventListener('change', () => {
        updateShellSequenceDependency();
        updateToolsJson();
        persistLastSettings();
    });
    toolCheckboxes.forEach(cb => cb.addEventListener('change', () => {
        updateToolsJson();
        persistLastSettings();
    }));
    updateShellSequenceDependency();
    updateToolsJson();

    function parsePolicyList(rawValue, defaultValue = []) {
        const lines = String(rawValue || '')
            .split(/\r?\n/)
            .map(line => line.trim())
            .filter(Boolean);
        return lines.length ? lines : defaultValue;
    }

    function normalizeProvider(value) {
        if (value === PROVIDERS.LITELLM) return PROVIDERS.LITELLM;
        if (value === PROVIDERS.OPENAI) return PROVIDERS.OPENAI;
        if (value === PROVIDERS.CLAUDE) return PROVIDERS.CLAUDE;
        return PROVIDERS.OLLAMA_DIRECT;
    }

    function providerUsesApiKey(provider) {
        return normalizeProvider(provider) !== PROVIDERS.OLLAMA_DIRECT;
    }

    function providerRequiresApiKey(provider) {
        const normalized = normalizeProvider(provider);
        return normalized === PROVIDERS.OPENAI || normalized === PROVIDERS.CLAUDE;
    }

    function formatProviderLabel(provider) {
        const normalized = normalizeProvider(provider);
        if (normalized === PROVIDERS.LITELLM) return 'LiteLLM';
        if (normalized === PROVIDERS.OPENAI) return 'OpenAI';
        if (normalized === PROVIDERS.CLAUDE) return 'Claude';
        return 'Ollama (direct)';
    }

    function providerDefaultUrl(provider) {
        const normalized = normalizeProvider(provider);
        if (normalized === PROVIDERS.LITELLM) return 'https://your-litellm-host';
        if (normalized === PROVIDERS.OPENAI) return 'https://api.openai.com';
        if (normalized === PROVIDERS.CLAUDE) return 'https://api.anthropic.com';
        return 'http://localhost:11434';
    }

    function providerHelpContent(provider) {
        const normalized = normalizeProvider(provider);
        if (normalized === PROVIDERS.OPENAI) {
            return {
                provider: 'Connect directly to the OpenAI API. Use your OpenAI API key and fetch from the public model catalog available to your account.',
                url: 'Base URL for OpenAI. In most cases use https://api.openai.com.',
                apiKey: 'Required. Use your OpenAI API key. It is sent only with model discovery and chat requests.',
            };
        }
        if (normalized === PROVIDERS.CLAUDE) {
            return {
                provider: 'Connect directly to Anthropic for Claude models. Use your Anthropic API key and fetch the Claude models available to your account.',
                url: 'Base URL for Anthropic. In most cases use https://api.anthropic.com.',
                apiKey: 'Required. Use your Anthropic API key. It is sent only with model discovery and chat requests.',
            };
        }
        if (normalized === PROVIDERS.LITELLM) {
            return {
                provider: 'Connect through a LiteLLM proxy that exposes an OpenAI-compatible API surface.',
                url: 'Base URL for your LiteLLM deployment, for example https://your-litellm-host.',
                apiKey: 'Usually required. Use the LiteLLM or proxy API key expected by that deployment.',
            };
        }
        return {
            provider: 'Connect directly to a local or remote Ollama instance.',
            url: 'Base URL for Ollama. In most cases use http://localhost:11434.',
            apiKey: 'Usually not required for direct Ollama. If your endpoint is protected, provide the API key expected by that gateway.',
        };
    }

    function updateProviderUi() {
        const provider = normalizeProvider(providerSelect?.value);
        const showApiKey = providerUsesApiKey(provider);
        const help = providerHelpContent(provider);

        if (apiKeyGroup) {
            apiKeyGroup.style.display = showApiKey ? 'flex' : 'none';
        }

        if (providerHelpText) {
            providerHelpText.textContent = help.provider;
        }

        if (providerUrlHelpText) {
            providerUrlHelpText.textContent = help.url;
        }

        if (providerApiKeyHelpText) {
            providerApiKeyHelpText.textContent = help.apiKey;
        }

        if (ollamaUrlInput) {
            ollamaUrlInput.placeholder = providerDefaultUrl(provider);
        }
    }

    function updateAnalysisProviderUi() {
        const provider = normalizeProvider(analysisProviderSelect?.value);
        const showApiKey = providerUsesApiKey(provider);
        const help = providerHelpContent(provider);

        if (analysisApiKeyGroup) {
            analysisApiKeyGroup.style.display = showApiKey ? 'flex' : 'none';
        }

        if (analysisProviderHelpText) {
            analysisProviderHelpText.textContent = help.provider;
        }

        if (analysisProviderUrlHelpText) {
            analysisProviderUrlHelpText.textContent = help.url;
        }

        if (analysisProviderApiKeyHelpText) {
            analysisProviderApiKeyHelpText.textContent = help.apiKey;
        }

        if (analysisOllamaUrlInput) {
            analysisOllamaUrlInput.placeholder = providerDefaultUrl(provider);
        }
    }

    function validateProviderApiKey(provider, apiKey) {
        if (providerRequiresApiKey(provider) && !String(apiKey || '').trim()) {
            showAlert(`Enter an API key for ${formatProviderLabel(provider)}.`, 'error');
            return false;
        }
        return true;
    }

    function saveApiKeyToSessionStorage() {
        if (!apiKeyInput) {
            return;
        }

        try {
            const apiKey = apiKeyInput.value.trim();
            if (apiKey) {
                sessionStorage.setItem(API_KEY_SESSION_STORAGE_KEY, apiKey);
                sessionStorage.removeItem(LEGACY_API_TOKEN_SESSION_STORAGE_KEY);
            } else {
                sessionStorage.removeItem(API_KEY_SESSION_STORAGE_KEY);
                sessionStorage.removeItem(LEGACY_API_TOKEN_SESSION_STORAGE_KEY);
            }
        } catch (err) {
            console.warn('Failed to persist API key in session storage:', err);
        }
    }

    function restoreApiKeyFromSessionStorage() {
        if (!apiKeyInput) {
            return;
        }

        try {
            const apiKey = sessionStorage.getItem(API_KEY_SESSION_STORAGE_KEY) || sessionStorage.getItem(LEGACY_API_TOKEN_SESSION_STORAGE_KEY);
            if (apiKey) {
                apiKeyInput.value = apiKey;
                sessionStorage.setItem(API_KEY_SESSION_STORAGE_KEY, apiKey);
                sessionStorage.removeItem(LEGACY_API_TOKEN_SESSION_STORAGE_KEY);
            }
        } catch (err) {
            console.warn('Failed to restore API key from session storage:', err);
        }
    }

    function updateClearSavedKeyButton() {
        if (!clearSavedKeyBtn || !apiKeyInput) {
            return;
        }

        clearSavedKeyBtn.disabled = !apiKeyInput.value.trim();
    }

    function setTokenVisibility(toggleButton, input, isVisible) {
        if (!toggleButton || !input) {
            return;
        }

        input.type = isVisible ? 'text' : 'password';
        toggleButton.setAttribute('aria-pressed', String(isVisible));
        toggleButton.setAttribute('aria-label', isVisible ? 'Hide API key' : 'Show API key');
        toggleButton.innerHTML = `<i class="ph ${isVisible ? 'ph-eye-slash' : 'ph-eye'}"></i>`;
    }

    apiKeyInput?.addEventListener('input', () => {
        saveApiKeyToSessionStorage();
        updateClearSavedKeyButton();
    });
    restoreApiKeyFromSessionStorage();
    updateClearSavedKeyButton();
    if (providerSelect) {
        providerSelect.dataset.previousProvider = normalizeProvider(providerSelect.value);
    }
    if (analysisProviderSelect) {
        analysisProviderSelect.dataset.previousProvider = normalizeProvider(analysisProviderSelect.value);
    }
    restoreLastSettings();
    _activePolicyEntryType = getSelectedPolicyEntryType();
    updateProviderUi();
    if (fetchBtn) {
        fetchBtn.disabled = false;
    }

    const runtimeSettingElements = [providerSelect, ollamaUrlInput, sslVerifyToggle, modelSelect, maxTurnsInput, kaliCommandType, toolsJsonArea, document.getElementById('context-window')];
    runtimeSettingElements.forEach(el => {
        if (!el) {
            return;
        }
        const eventName = el.tagName === 'SELECT' || el.type === 'checkbox' ? 'change' : 'input';
        el.addEventListener(eventName, persistLastSettings);
    });

    // Keylogger toggle handler
    keyloggerEnableToggle?.addEventListener('change', () => {
        const enabled = keyloggerEnableToggle.checked;
        localStorage.setItem('keylogger:enabled', String(enabled));
        if (enabled) {
            showAlert('Keylogging enabled. Keystrokes will be captured during sessions.', 'success');
        }
    });

    chatScopeSlider?.addEventListener('input', () => {
        updateChatScopeUi();
        localStorage.setItem('chat:scope', getChatScopeConfig().id);
    });

    chatScopeEnabled?.addEventListener('change', () => {
        localStorage.setItem('chat:scope:enabled', String(isChatScopeEnabled()));
        updateChatScopeUi();
    });

    chatUrgencySlider?.addEventListener('input', () => {
        updateChatUrgencyUi();
        localStorage.setItem('chat:urgency', getChatUrgencyConfig().id);
    });

    chatUrgencyEnabled?.addEventListener('change', () => {
        localStorage.setItem('chat:urgency:enabled', String(isChatUrgencyEnabled()));
        updateChatUrgencyUi();
    });

    // Restore keylogger setting from localStorage
    try {
        const keyloggerEnabled = localStorage.getItem('keylogger:enabled');
        if (keyloggerEnabled === 'true') {
            keyloggerEnableToggle.checked = true;
        }
        const savedChatScope = localStorage.getItem('chat:scope');
        const savedScopeIndex = CHAT_SCOPE_LEVELS.findIndex(scope => scope.id === savedChatScope);
        if (chatScopeSlider && savedScopeIndex >= 0) {
            chatScopeSlider.value = String(savedScopeIndex);
        }
        const savedChatScopeEnabled = localStorage.getItem('chat:scope:enabled');
        if (chatScopeEnabled && savedChatScopeEnabled !== null) {
            chatScopeEnabled.checked = savedChatScopeEnabled !== 'false';
        }
        const savedChatUrgency = localStorage.getItem('chat:urgency');
        const savedUrgencyIndex = CHAT_URGENCY_LEVELS.findIndex(level => level.id === savedChatUrgency);
        if (chatUrgencySlider && savedUrgencyIndex >= 0) {
            chatUrgencySlider.value = String(savedUrgencyIndex);
        }
        const savedChatUrgencyEnabled = localStorage.getItem('chat:urgency:enabled');
        if (chatUrgencyEnabled && savedChatUrgencyEnabled !== null) {
            chatUrgencyEnabled.checked = savedChatUrgencyEnabled !== 'false';
        }
    } catch (err) {
        console.warn('Failed to restore keylogger setting:', err);
    }
    updateChatControlAvailability();

    providerSelect?.addEventListener('change', () => {
        const previousProvider = normalizeProvider(providerSelect?.dataset.previousProvider);
        const nextProvider = normalizeProvider(providerSelect?.value);
        const currentUrl = ollamaUrlInput?.value.trim() || '';
        if (ollamaUrlInput && (!currentUrl || currentUrl === providerDefaultUrl(previousProvider))) {
            ollamaUrlInput.value = providerDefaultUrl(nextProvider);
        }
        if (providerSelect) {
            providerSelect.dataset.previousProvider = nextProvider;
        }
        updateProviderUi();
        modelSelect.innerHTML = '<option value="" disabled selected>Click \'Fetch\' to load models</option>';
        modelSelect.disabled = true;
        if (!_serviceRunning) {
            startBtn.disabled = true;
        }
        if (ollamaFetchError) {
            ollamaFetchError.style.display = 'none';
            ollamaFetchError.innerText = '';
        }
        if (fetchBtn) {
            fetchBtn.disabled = false;
        }
        persistLastSettings();
    });

    analysisProviderSelect?.addEventListener('change', () => {
        const previousProvider = normalizeProvider(analysisProviderSelect?.dataset.previousProvider);
        const nextProvider = normalizeProvider(analysisProviderSelect?.value);
        const currentUrl = analysisOllamaUrlInput?.value.trim() || '';
        if (analysisOllamaUrlInput && (!currentUrl || currentUrl === providerDefaultUrl(previousProvider))) {
            analysisOllamaUrlInput.value = providerDefaultUrl(nextProvider);
        }
        if (analysisProviderSelect) {
            analysisProviderSelect.dataset.previousProvider = nextProvider;
        }
        updateAnalysisProviderUi();
        analysisModelSelect.innerHTML = '<option value="" disabled selected>Fetch models to load options</option>';
        analysisModelSelect.disabled = true;
        if (analysisFetchError) {
            analysisFetchError.style.display = 'none';
            analysisFetchError.innerText = '';
        }
    });

    tokenVisibilityToggles.forEach(toggleButton => {
        const targetId = toggleButton.getAttribute('data-target-input');
        const input = targetId ? document.getElementById(targetId) : null;
        if (!(input instanceof HTMLInputElement)) {
            return;
        }

        setTokenVisibility(toggleButton, input, false);
        toggleButton.addEventListener('click', () => {
            const isVisible = input.type !== 'password';
            setTokenVisibility(toggleButton, input, !isVisible);
        });
    });

    clearSavedKeyBtn?.addEventListener('click', () => {
        if (!apiKeyInput) {
            return;
        }

        apiKeyInput.value = '';
        saveApiKeyToSessionStorage();
        updateClearSavedKeyButton();

        const runtimeToggle = document.querySelector('[data-target-input="api-key"]');
        if (runtimeToggle instanceof HTMLButtonElement) {
            setTokenVisibility(runtimeToggle, apiKeyInput, false);
        }

        showAlert('Saved API key cleared from this browser session.', 'success');
    });

    function getSelectedPolicyEntryType() {
        const selected = Array.from(policyEntryTypeInputs).find(input => input.checked);
        return selected?.value === 'disallow' ? 'disallow' : 'allow';
    }

    function updatePolicyEntryEditor() {
        if (!policyTargetsInput) {
            return;
        }

        const entryType = getSelectedPolicyEntryType();
        const values = Array.isArray(_policyDraft[entryType]) ? _policyDraft[entryType] : [];
        const defaultValue = entryType === 'allow' ? ['*'] : [];
        const textValue = (values.length ? values : defaultValue).join('\n');

        policyTargetsInput.value = textValue;
        policyTargetsInput.placeholder = entryType === 'allow' ? '*' : 'Leave blank for none';

        if (policyEntryHint) {
            policyEntryHint.innerHTML = entryType === 'allow'
                ? 'Editing the <strong>allow list</strong>. One entry per line. Supports <strong>*</strong>, IPs, CIDRs, hostnames, and URLs. Default is <strong>*</strong> to allow anything.'
                : 'Editing the <strong>deny list</strong>. One entry per line. Deny rules override allow rules.';
        }
    }

    function syncPolicyDraftFromEditor(entryTypeOverride = null) {
        if (!policyTargetsInput) {
            return;
        }

        const entryType = entryTypeOverride === 'disallow' ? 'disallow' : (entryTypeOverride === 'allow' ? 'allow' : getSelectedPolicyEntryType());
        const defaultValue = entryType === 'allow' ? ['*'] : [];
        _policyDraft[entryType] = parsePolicyList(policyTargetsInput.value, defaultValue);
    }

    policyEntryTypeInputs.forEach(input => {
        input.addEventListener('change', () => {
            syncPolicyDraftFromEditor(_activePolicyEntryType);
            _activePolicyEntryType = getSelectedPolicyEntryType();
            updatePolicyEntryEditor();
            persistLastSettings();
        });
    });

    policyTargetsInput?.addEventListener('input', () => {
        syncPolicyDraftFromEditor();
        _activePolicyEntryType = getSelectedPolicyEntryType();
        persistLastSettings();
    });
    updatePolicyEntryEditor();

    // ---------------------------------------------------------------
    // Fetch Models
    // ---------------------------------------------------------------
    async function fetchModelsIntoSelect({ url, provider = PROVIDERS.OLLAMA_DIRECT, apiKey = '', sslVerify = true, button, errorLabel, selectElement, progressTitleText, successMessage, onSuccess, onFailure }) {
        if (!url) {
            showAlert('Please enter an instance URL');
            return false;
        }

        button.disabled = true;
        if (errorLabel) {
            errorLabel.style.display = 'none';
            errorLabel.innerText = '';
        }

        progressTitle.innerText = progressTitleText || 'Fetching Models';
        progressMsg.innerText = `Connecting to ${url}...`;
        progressModal.style.display = 'flex';

        try {
            const response = await fetch('/api/models', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url, provider, api_key: apiKey, ssl_verify: sslVerify })
            });
            const data = await response.json();

            if (!data.success) {
                throw new Error(data.error || 'Failed to fetch models');
            }

            selectElement.innerHTML = '';
            if (!data.models.length) {
                selectElement.innerHTML = '<option value="" disabled selected>No models found</option>';
                selectElement.disabled = true;
                if (onFailure) onFailure();
                showAlert('No models found in the specified provider instance.', 'error');
                return false;
            }

            data.models.forEach(model => {
                const option = document.createElement('option');
                option.value = typeof model === 'string' ? model : model.id;
                option.textContent = typeof model === 'string' ? model : model.label;
                selectElement.appendChild(option);
            });

            selectElement.disabled = false;
            if (onSuccess) onSuccess(data.models);
            showAlert(successMessage || `Successfully fetched ${data.models.length} models.`, 'success');
            return true;
        } catch (error) {
            showAlert(error.message, 'error');
            if (errorLabel) {
                errorLabel.innerText = `❌ ${error.message}`;
                errorLabel.style.display = 'block';
            }
            selectElement.innerHTML = '<option value="" disabled selected>Failed to load models</option>';
            selectElement.disabled = true;
            if (onFailure) onFailure(error);
            return false;
        } finally {
            button.disabled = false;
            progressModal.style.display = 'none';
        }
    }

    fetchBtn.addEventListener('click', async () => {
        const url = ollamaUrlInput.value.trim();
        const provider = normalizeProvider(providerSelect?.value);
        const apiKey = providerUsesApiKey(provider) ? (apiKeyInput?.value.trim() || '') : '';
        const sslVerify = Boolean(sslVerifyToggle?.checked ?? true);
        const currentSelectedModel = modelSelect.value;
        if (!validateProviderApiKey(provider, apiKey)) {
            return;
        }
        await fetchModelsIntoSelect({
            url,
            provider,
            apiKey,
            sslVerify,
            button: fetchBtn,
            errorLabel: ollamaFetchError,
            selectElement: modelSelect,
            progressTitleText: 'Fetching Models',
            onSuccess: models => {
                const normalizedModels = Array.isArray(models)
                    ? models.map(model => typeof model === 'string' ? model : model.id)
                    : [];
                if (currentSelectedModel && normalizedModels.includes(currentSelectedModel)) {
                    modelSelect.value = currentSelectedModel;
                }
                startBtn.disabled = false;
                persistLastSettings();
            },
            onFailure: () => {
                if (!_serviceRunning) {
                    startBtn.disabled = true;
                }
            },
        });
    });

    function closeAnalysisConfigModal(result = null) {
        analysisConfigModalOverlay.style.display = 'none';
        _analysisConfigOptions = null;
        if (_analysisConfigResolver) {
            _analysisConfigResolver(result);
            _analysisConfigResolver = null;
        }
    }

    async function openAnalysisConfigModal({
        suggestedUrl = '',
        suggestedProvider = PROVIDERS.OLLAMA_DIRECT,
        suggestedApiKey = '',
        suggestedSslVerify = true,
        suggestedModel = '',
        title = 'Analysis Configuration',
        description = 'Choose which provider, instance, and model should be used for this analysis job.',
        confirmLabel = 'Run Analysis',
        includeSpan = false,
        defaultSpan = 'Entire Session',
        fixedSpan = null,
        selectedOutputs = DEFAULT_ANALYSIS_OUTPUTS,
    } = {}) {
        if (_analysisConfigResolver) {
            closeAnalysisConfigModal(null);
        }

        _analysisConfigOptions = { includeSpan, fixedSpan };
        analysisConfigTitle.innerHTML = `<i class="ph ph-brain"></i> ${escapeHtml(title)}`;
        analysisConfigDescription.textContent = description;
        confirmAnalysisConfigBtn.textContent = confirmLabel;
        analysisProviderSelect.value = normalizeProvider(suggestedProvider);
        analysisOllamaUrlInput.value = suggestedUrl || ollamaUrlInput.value.trim() || providerDefaultUrl(suggestedProvider);
        analysisApiKeyInput.value = suggestedApiKey || apiKeyInput?.value.trim() || '';
        if (analysisSslVerifyToggle) {
            analysisSslVerifyToggle.checked = suggestedSslVerify;
        }
        analysisFetchError.style.display = 'none';
        analysisFetchError.innerText = '';
        analysisSpanGroup.style.display = includeSpan ? 'flex' : 'none';
        analysisSpanSelect.value = defaultSpan;
        const selectedOutputSet = new Set(Array.isArray(selectedOutputs) && selectedOutputs.length ? selectedOutputs : DEFAULT_ANALYSIS_OUTPUTS);
        analysisOutputCheckboxes.forEach(checkbox => {
            checkbox.checked = selectedOutputSet.has(checkbox.value);
        });
        analysisModelSelect.innerHTML = suggestedModel
            ? `<option value="${escapeHtml(suggestedModel)}" selected>${escapeHtml(suggestedModel)}</option>`
            : '<option value="" disabled selected>Fetch models to load options</option>';
        analysisModelSelect.disabled = !suggestedModel;
        updateAnalysisProviderUi();
        analysisConfigModalOverlay.style.display = 'flex';

        return new Promise(resolve => {
            _analysisConfigResolver = resolve;
        });
    }

    analysisFetchBtn.addEventListener('click', async () => {
        const url = analysisOllamaUrlInput.value.trim();
        const provider = normalizeProvider(analysisProviderSelect?.value);
        const apiKey = providerUsesApiKey(provider) ? (analysisApiKeyInput?.value.trim() || '') : '';
        const sslVerify = Boolean(analysisSslVerifyToggle?.checked ?? true);
        const currentSelectedModel = analysisModelSelect.value;
        if (!validateProviderApiKey(provider, apiKey)) {
            return;
        }

        await fetchModelsIntoSelect({
            url,
            provider,
            apiKey,
            sslVerify,
            button: analysisFetchBtn,
            errorLabel: analysisFetchError,
            selectElement: analysisModelSelect,
            progressTitleText: 'Fetching Analysis Models',
            successMessage: 'Analysis models fetched successfully.',
            onSuccess: models => {
                if (currentSelectedModel && models.includes(currentSelectedModel)) {
                    analysisModelSelect.value = currentSelectedModel;
                }
            },
        });
    });

    confirmAnalysisConfigBtn.addEventListener('click', () => {
        const ollamaUrl = analysisOllamaUrlInput.value.trim();
        const provider = normalizeProvider(analysisProviderSelect?.value);
        const apiKey = providerUsesApiKey(provider) ? (analysisApiKeyInput?.value.trim() || '') : '';
        const sslVerify = Boolean(analysisSslVerifyToggle?.checked ?? true);
        const model = analysisModelSelect.value;
        const span = _analysisConfigOptions?.includeSpan
            ? analysisSpanSelect.value
            : (_analysisConfigOptions?.fixedSpan || 'Entire Session');
        const analysis_outputs = Array.from(analysisOutputCheckboxes)
            .filter(checkbox => checkbox.checked)
            .map(checkbox => checkbox.value);

        if (!ollamaUrl) {
            showAlert('Please enter an instance URL', 'error');
            return;
        }
        if (!validateProviderApiKey(provider, apiKey)) {
            return;
        }
        if (!model) {
            showAlert('Fetch models and select one before running analysis.', 'error');
            return;
        }

        closeAnalysisConfigModal({ ollama_url: ollamaUrl, provider, api_key: apiKey, ssl_verify: sslVerify, model, span, analysis_outputs });
    });

    cancelAnalysisConfigBtn.addEventListener('click', () => closeAnalysisConfigModal(null));
    closeAnalysisConfigBtn.addEventListener('click', () => closeAnalysisConfigModal(null));
    analysisConfigModalOverlay.addEventListener('click', (e) => {
        if (e.target === analysisConfigModalOverlay) {
            closeAnalysisConfigModal(null);
        }
    });

    // ---------------------------------------------------------------
    // Log Helpers
    // ---------------------------------------------------------------
    function getLiveLogStorageKey(runId = _currentRunId) {
        return runId ? `${LIVE_LOG_STORAGE_PREFIX}${runId}` : null;
    }

    function isStorageQuotaError(err) {
        return err instanceof DOMException && (
            err.name === 'QuotaExceededError'
            || err.name === 'NS_ERROR_DOM_QUOTA_REACHED'
            || err.code === 22
            || err.code === 1014
        );
    }

    function trimPersistedLogHtml(html) {
        const text = String(html || '');
        if (text.length <= MAX_PERSISTED_LIVE_LOG_HTML) {
            return text;
        }
        return text.slice(text.length - MAX_PERSISTED_LIVE_LOG_HTML);
    }

    function pruneStoredLiveLogs(excludeRunId = null) {
        const entries = [];
        for (let index = 0; index < localStorage.length; index += 1) {
            const key = localStorage.key(index);
            if (!key || !key.startsWith(LIVE_LOG_STORAGE_PREFIX)) {
                continue;
            }
            const runId = key.slice(LIVE_LOG_STORAGE_PREFIX.length);
            if (excludeRunId && runId === excludeRunId) {
                continue;
            }
            let savedAt = 0;
            try {
                const raw = localStorage.getItem(key);
                const payload = raw ? JSON.parse(raw) : null;
                savedAt = Number(payload?.savedAt || 0);
            } catch (err) {
                savedAt = 0;
            }
            entries.push({ key, savedAt });
        }

        entries.sort((a, b) => a.savedAt - b.savedAt);
        entries.forEach(entry => {
            localStorage.removeItem(entry.key);
        });
        return entries.length;
    }

    function safeLocalStorageSet(key, value, { excludeRunId = null } = {}) {
        try {
            localStorage.setItem(key, value);
            return true;
        } catch (err) {
            if (!isStorageQuotaError(err)) {
                throw err;
            }

            const prunedCount = pruneStoredLiveLogs(excludeRunId);
            if (!prunedCount) {
                throw err;
            }

            localStorage.setItem(key, value);
            return true;
        }
    }

    function persistLiveLog(runId = _currentRunId) {
        const storageKey = getLiveLogStorageKey(runId);
        if (!storageKey) return;

        try {
            safeLocalStorageSet(storageKey, JSON.stringify({
                html: trimPersistedLogHtml(liveLogViewer.innerHTML),
                cleared: _logInitialCleared,
                savedAt: Date.now(),
            }), { excludeRunId: runId });
            safeLocalStorageSet(LAST_ACTIVE_RUN_STORAGE_KEY, runId, { excludeRunId: runId });
        } catch (err) {
            console.warn('Failed to persist live log state:', err);
        }
    }

    function restoreLiveLog(runId = _currentRunId) {
        const storageKey = getLiveLogStorageKey(runId);
        if (!storageKey) return false;

        try {
            const raw = localStorage.getItem(storageKey);
            if (!raw) return false;

            const payload = JSON.parse(raw);
            if (!payload || typeof payload.html !== 'string') return false;

            liveLogViewer.innerHTML = payload.html;
            while (liveLogViewer.children.length > MAX_LIVE_LOG_ENTRIES) {
                liveLogViewer.removeChild(liveLogViewer.firstElementChild);
            }
            _logInitialCleared = Boolean(payload.cleared || payload.html.trim());
            return true;
        } catch (err) {
            console.warn('Failed to restore live log state:', err);
            return false;
        }
    }

    function normalizePolicy(policy) {
        const allow = Array.isArray(policy?.allow) && policy.allow.length ? policy.allow : ['*'];
        const disallow = Array.isArray(policy?.disallow) ? policy.disallow : [];
        return { allow, disallow };
    }

    function policyPreview(entries, emptyLabel) {
        if (!entries.length) return emptyLabel;
        if (entries.length === 1) return entries[0];
        return `${entries[0]} +${entries.length - 1}`;
    }

    function formatPolicyBadge(policy) {
        const normalized = normalizePolicy(policy);
        return `Targets: allow ${policyPreview(normalized.allow, 'none')} | block ${policyPreview(normalized.disallow, 'none')}`;
    }

    function formatPolicyTooltip(policy) {
        const normalized = normalizePolicy(policy);
        const allowText = normalized.allow.length ? normalized.allow.join('\n') : 'None';
        const disallowText = normalized.disallow.length ? normalized.disallow.join('\n') : 'None';
        return `Allowed targets:\n${allowText}\n\nBlocked targets:\n${disallowText}`;
    }

    function setLiveToolsBadge(tools) {
        const toolList = Array.isArray(tools) ? tools : [];
        if (!toolList.length) {
            toolsBadge.style.display = 'none';
            toolsBadge.textContent = '';
            toolsBadge.title = '';
            toolsBadge.classList.remove('tools-badge-warning');
            return;
        }

        const hasDangerousShell = toolList.includes('shell_dangerous');
        toolsBadge.textContent = hasDangerousShell
            ? `${toolList.length} tool(s): ${toolList.join(', ')} | dangerous approval required`
            : `${toolList.length} tool(s): ${toolList.join(', ')}`;
        toolsBadge.title = hasDangerousShell
            ? `${toolList.join('\n')}\n\nWarning: shell_dangerous is enabled and requires explicit user approval before execution.`
            : toolList.join('\n');
        toolsBadge.classList.toggle('tools-badge-warning', hasDangerousShell);
        toolsBadge.style.display = 'inline-block';
    }

    function renderPolicyList(entries, emptyLabel) {
        if (!entries.length) {
            return `<li>${escapeHtml(emptyLabel)}</li>`;
        }
        return entries.map(entry => `<li>${escapeHtml(entry)}</li>`).join('');
    }

    function renderSessionSummary(session) {
        if (!session) {
            sessionSummaryPanel.style.display = 'none';
            sessionSummaryPanel.innerHTML = '';
            return;
        }

        const policy = normalizePolicy(session.network_policy);
        const availableTools = Array.isArray(session.available_tools) ? session.available_tools : [];
        const startTime = session.start_time ? new Date(session.start_time).toLocaleString() : '—';
        const model = session.model || '—';
        const provider = formatProviderLabel(session.llm_provider);
        const ollamaUrl = session.ollama_url || '—';
        const apiAuthEnabled = Boolean(session.llm_auth_enabled);
        const toolCount = session.available_tool_count || availableTools.length || 0;
        const toolSummary = toolCount ? `${toolCount} tool(s)` : 'No tool inventory saved';
        const hasDangerousShell = availableTools.includes('shell_dangerous');
        const dangerousShellSummary = hasDangerousShell ? 'Enabled: user approval required before execution' : 'Not enabled';
        const apiAuthSummary = apiAuthEnabled ? 'Configured' : (providerUsesApiKey(session.llm_provider) ? 'Not configured' : 'Not required');

        sessionSummaryPanel.innerHTML = `
            <div class="session-summary-grid">
                <div class="session-summary-item">
                    <span class="session-summary-label">Run ID</span>
                    <span class="session-summary-value">${escapeHtml(session.run_id || '—')}</span>
                </div>
                <div class="session-summary-item">
                    <span class="session-summary-label">Started</span>
                    <span class="session-summary-value">${escapeHtml(startTime)}</span>
                </div>
                <div class="session-summary-item">
                    <span class="session-summary-label">Provider</span>
                    <span class="session-summary-value">${escapeHtml(provider)}</span>
                </div>
                <div class="session-summary-item">
                    <span class="session-summary-label">Model</span>
                    <span class="session-summary-value">${escapeHtml(model)}</span>
                </div>
                <div class="session-summary-item">
                    <span class="session-summary-label">Instance URL</span>
                    <span class="session-summary-value">${escapeHtml(ollamaUrl)}</span>
                </div>
                <div class="session-summary-item">
                    <span class="session-summary-label">LLM API Key</span>
                    <span class="session-summary-value">${escapeHtml(apiAuthSummary)}</span>
                </div>
                <div class="session-summary-item">
                    <span class="session-summary-label">Tool Inventory</span>
                    <span class="session-summary-value">${escapeHtml(toolSummary)}</span>
                </div>
                <div class="session-summary-item ${hasDangerousShell ? 'session-summary-item-warning' : ''}">
                    <span class="session-summary-label">Dangerous Shell</span>
                    <span class="session-summary-value">${escapeHtml(dangerousShellSummary)}</span>
                </div>
                <div class="session-summary-item">
                    <span class="session-summary-label">Target Policy</span>
                    <span class="session-summary-value">${escapeHtml(formatPolicyBadge(policy))}</span>
                </div>
            </div>
            <div class="session-policy-blocks">
                <div class="session-policy-card">
                    <h4>Allowed Targets</h4>
                    <ul class="session-policy-list">${renderPolicyList(policy.allow, 'None')}</ul>
                </div>
                <div class="session-policy-card">
                    <h4>Blocked Targets</h4>
                    <ul class="session-policy-list">${renderPolicyList(policy.disallow, 'None')}</ul>
                </div>
            </div>
        `;
        sessionSummaryPanel.style.display = 'flex';
    }

    function setLivePolicyBadge(policy) {
        if (!policyBadge) return;
        if (!policy) {
            policyBadge.style.display = 'none';
            policyBadge.textContent = '';
            policyBadge.title = '';
            return;
        }

        policyBadge.textContent = formatPolicyBadge(policy);
        policyBadge.title = formatPolicyTooltip(policy);
        policyBadge.style.display = 'inline-block';
    }

    // ---------------------------------------------------------------
    // Chat Tab Management
    // ---------------------------------------------------------------
    function switchChatTab(tabId) {
        // Update tab buttons
        const tabs = chatTabBar.querySelectorAll('.chat-tab');
        tabs.forEach(t => {
            if (t.dataset.tabId === tabId) {
                t.classList.add('active');
            } else {
                t.classList.remove('active');
            }
        });

        // Update tab panels
        const panels = chatTabsContent.querySelectorAll('.chat-tab-panel');
        panels.forEach(p => {
            if (p.id === `chat-tab-${tabId}`) {
                p.classList.add('active');
            } else {
                p.classList.remove('active');
            }
        });

        // Toggle chat console bar visibility
        // We only show the main chat console for the "main" tab
        if (tabId === 'main') {
            chatConsoleBar.style.display = 'block';
        } else {
            chatConsoleBar.style.display = 'none';
        }
    }

    function createTerminalTab(sessionId, tool = '', argsSummary = '') {
        if (document.querySelector(`.chat-tab[data-tab-id="${sessionId}"]`)) return;

        // Build a descriptive tab label
        let tabLabel = sessionId;
        if (tool) {
            const shortArgs = argsSummary.length > 30 ? argsSummary.substring(0, 30) + '…' : argsSummary;
            tabLabel = `${tool}` + (shortArgs ? ` · ${shortArgs}` : '');
        }

        // Create Tab Button
        const tabBtn = document.createElement('button');
        tabBtn.type = 'button';
        tabBtn.className = 'chat-tab status-active';
        tabBtn.dataset.tabId = sessionId;
        tabBtn.innerHTML = `
            <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" fill="currentColor" viewBox="0 0 256 256" style="flex-shrink:0">
                <path d="M128,128a8,8,0,0,1-3.12.65,8,8,0,0,1-6.94-4A8,8,0,0,1,120.84,116l80-48a8,8,0,0,1,8.32,13.66ZM232,56V200a16,16,0,0,1-16,16H40a16,16,0,0,1-16-16V56A16,16,0,0,1,40,40H216A16,16,0,0,1,232,56ZM216,200V56H40V200Z"></path>
            </svg>
            <span title="${escapeHtml(sessionId)}${tool ? ' — ' + escapeHtml(tool) : ''}">${escapeHtml(tabLabel)}</span>
            <span class="chat-tab-close" title="Close Session">✕</span>
        `;

        tabBtn.addEventListener('click', (e) => {
            if (e.target.classList.contains('chat-tab-close')) {
                closeTerminalTab(sessionId);
            } else {
                switchChatTab(sessionId);
            }
        });

        chatTabBar.appendChild(tabBtn);

        // Build creation context banner
        const now = new Date().toLocaleTimeString();
        let contextHtml = `<strong>${escapeHtml(sessionId)}</strong> created at ${now}`;
        if (tool) {
            contextHtml += ` via <strong>${escapeHtml(tool)}</strong>`;
        }
        if (argsSummary) {
            const safeArgs = escapeHtml(argsSummary.length > 120 ? argsSummary.substring(0, 120) + '…' : argsSummary);
            contextHtml += `<br><span style="color: var(--text-secondary); font-size: 0.75rem;">Args: <code>${safeArgs}</code></span>`;
        }

        // Create Tab Panel
        const tabPanel = document.createElement('div');
        tabPanel.className = 'chat-tab-panel';
        tabPanel.id = `chat-tab-${sessionId}`;
        tabPanel.innerHTML = `
            <div class="isess-log-viewer" id="log-viewer-${sessionId}">
                <div class="log-entry log-status" style="border-left: 3px solid var(--accent-primary); padding-left: 0.6rem; margin-bottom: 0.4rem;">
                    ${contextHtml}
                </div>
                <div class="log-entry log-status">Waiting for output… You can type commands below once the session is ready.</div>
            </div>
            <div class="isess-input-row" id="input-row-${sessionId}">
                <span class="isess-prompt-indicator">></span>
                <input type="text" class="isess-input" id="input-${sessionId}" 
                    placeholder="Waiting for session to initialize..." disabled>
            </div>
        `;

        chatTabsContent.appendChild(tabPanel);

        // Setup input handler
        const inputEl = tabPanel.querySelector('.isess-input');
        inputEl.addEventListener('keydown', async (e) => {
            if (e.key === 'Enter') {
                const val = inputEl.value.trim();
                if (!val) return;
                
                inputEl.value = '';
                appendIsessLog(sessionId, `\n> ${val}\n`, 'log-user-input');
                
                try {
                    const res = await fetch('/api/session/isess/write', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ session_id: sessionId, input: val })
                    });
                    const data = await res.json();
                    if (!data.success) {
                        appendIsessLog(sessionId, `Error: ${data.error || 'Failed to send command.'}\n`, 'log-error-text');
                    } else if (data.content) {
                        // Display the output returned by the write handler
                        appendIsessLog(sessionId, data.content + '\n', 'log-tool-result');
                    }
                } catch (err) {
                    appendIsessLog(sessionId, `Network error: ${err.message}\n`, 'log-error-text');
                }
            }
        });

        // Do NOT auto-switch — keep the user on the main agent tab.
        // Highlight the new tab so the user notices it.
        tabBtn.style.animation = 'tab-pulse 1.5s ease-in-out 3';
    }

    function closeTerminalTab(sessionId) {
        const tab = document.querySelector(`.chat-tab[data-tab-id="${sessionId}"]`);
        const closeEl = tab ? tab.querySelector('.chat-tab-close') : null;
        
        // If it's already closed/dimmed (⏹ icon), clicking again deletes the tab entirely
        if (closeEl && closeEl.textContent === '⏹') {
            const panel = document.getElementById(`chat-tab-${sessionId}`);
            if (tab) tab.remove();
            if (panel) panel.remove();
            
            // Switch back to main if we closed the active tab
            if (tab && tab.classList.contains('active')) {
                switchChatTab('main');
            }
            return;
        }

        if (!confirm(`Are you sure you want to close the interactive session ${sessionId}?`)) return;

        // Call backend to close
        fetch('/api/session/isess/write', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ session_id: sessionId, input: 'exit' })
        });

        markSessionClosed(sessionId);
    }

    function markSessionClosed(sessionId) {
        const panel = document.getElementById(`chat-tab-${sessionId}`);
        if (!panel) return;

        // Remove input row
        const inputRow = panel.querySelector('.isess-input-row');
        if (inputRow) inputRow.remove();

        // Append closed banner
        appendIsessLog(sessionId, `\n— Session ${sessionId} has been closed —`, 'log-status');

        // Dim and color the tab label
        const tab = document.querySelector(`.chat-tab[data-tab-id="${sessionId}"]`);
        if (tab) {
            tab.classList.remove('status-active');
            tab.classList.add('status-closed');
            // Replace close X with a label
            const closeEl = tab.querySelector('.chat-tab-close');
            if (closeEl) closeEl.textContent = '⏹';
        }
    }

    function appendIsessLog(sessionId, text, cssClass = '') {
        const viewer = document.getElementById(`log-viewer-${sessionId}`);
        if (!viewer) return;

        const entry = document.createElement('div');
        entry.className = `log-entry ${cssClass}`;
        entry.style.whiteSpace = 'pre-wrap';
        entry.textContent = text;
        viewer.appendChild(entry);

        // Auto-scroll within the log viewer only (not the outer page)
        requestAnimationFrame(() => {
            viewer.scrollTop = viewer.scrollHeight;
        });
    }

    // Add event listener to main tab
    document.querySelector('.chat-tab[data-tab-id="main"]').addEventListener('click', () => switchChatTab('main'));

    function appendLog(html, cssClass = '') {
        if (!_logInitialCleared) {
            liveLogViewer.innerHTML = '';
            _logInitialCleared = true;
        }
        const entry = document.createElement('div');
        entry.className = `log-entry ${cssClass}`;
        entry.innerHTML = html;
        liveLogViewer.appendChild(entry);
        while (liveLogViewer.children.length > MAX_LIVE_LOG_ENTRIES) {
            const firstChild = liveLogViewer.firstElementChild;
            if (!firstChild) break;
            
            if (_activeToolEntry === firstChild) {
                _activeToolEntry = null;
            }
            
            // Auto drop timeline nodes for removed tool calls
            if (firstChild.id && firstChild.id.startsWith('tool-call-')) {
                const tlRef = document.getElementById(`timeline-ref-${firstChild.id}`);
                if (tlRef) tlRef.remove();
            }
            
            liveLogViewer.removeChild(firstChild);
        }
        liveLogViewer.scrollTop = liveLogViewer.scrollHeight;
        persistLiveLog();
        return entry;
    }

    function formatElapsedDuration(ms) {
        const totalSeconds = Math.max(0, Math.floor((Number(ms) || 0) / 1000));
        const hours = Math.floor(totalSeconds / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);
        const seconds = totalSeconds % 60;
        if (hours > 0) {
            return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
        }
        return `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
    }

    function summarizeToolArgs(args) {
        const raw = JSON.stringify(args || {});
        if (!raw || raw === '{}') {
            return 'Args: (none)';
        }
        const compact = raw.length > 140 ? `${raw.slice(0, 137)}...` : raw;
        return `Args: ${compact}`;
    }

    function renderActiveToolEntry() {
        if (!_activeToolState || !_activeToolEntry) {
            return;
        }

        const elapsedMs = Date.now() - _activeToolState.startedAt;
        const runtime = formatElapsedDuration(elapsedMs);
        let phaseLabel = 'Running';
        let chipClass = 'is-running';
        if (_activeToolState.phase === 'waiting') {
            phaseLabel = 'Awaiting Input';
            chipClass = 'is-waiting';
        } else if (_activeToolState.phase === 'killing') {
            phaseLabel = 'Terminating...';
            chipClass = 'is-waiting';
        }
        
        const argsJson = JSON.stringify(_activeToolState.args || {});
        const note = String(_activeToolState.note || '').trim();

        _activeToolEntry.classList.toggle('log-tool-call-waiting', _activeToolState.phase === 'waiting' || _activeToolState.phase === 'killing');
        _activeToolEntry.innerHTML = `
            <div class="log-tool-call-row">
                <span><span class="log-label">🔧 Tool Call</span> <strong>${escapeHtml(_activeToolState.tool || 'Running tool')}</strong></span>
                <span class="log-tool-runtime-group">
                    <span class="log-tool-runtime-chip ${chipClass}">${phaseLabel} ${runtime}</span>
                    ${(_activeToolState.phase === 'running' && !_activeToolState.stopping) ? `
                        <button class="log-tool-stop-btn" onclick="stopCurrentTool(event)" title="Stop tool and continue analysis from partial output">⏹</button>
                    ` : (_activeToolState.stopping ? `<span class="log-tool-stop-loading">Stopping...</span>` : '')}
                </span>
            </div>
            <div class="log-tool-call-meta">args: <code>${escapeHtml(argsJson)}</code></div>
            ${note ? `<div class="log-tool-call-note">${escapeHtml(note)}</div>` : ''}
        `;

        // Keep the active tool entry fully visible in the log viewer
        liveLogViewer.scrollTop = liveLogViewer.scrollHeight;
    }

    function finalizeActiveToolEntry(note, phaseClass = 'is-complete', phaseLabel = 'Completed', durationMs = null) {
        if (!_activeToolState || !_activeToolEntry) {
            return;
        }

        const effectiveDuration = durationMs == null
            ? (Date.now() - _activeToolState.startedAt)
            : Number(durationMs) || 0;
        const runtime = formatElapsedDuration(effectiveDuration);
        const argsJson = JSON.stringify(_activeToolState.args || {});

        _activeToolEntry.classList.remove('log-tool-call-waiting');
        _activeToolEntry.innerHTML = `
            <div class="log-tool-call-row">
                <span><span class="log-label">🔧 Tool Call</span> <strong>${escapeHtml(_activeToolState.tool || 'Running tool')}</strong></span>
                <span class="log-tool-runtime-chip ${phaseClass}">${phaseLabel} ${runtime}</span>
            </div>
            <div class="log-tool-call-meta">args: <code>${escapeHtml(argsJson)}</code></div>
            <div class="log-tool-call-note">${escapeHtml(note)}</div>
        `;

        // Scroll to show the finalized tool entry fully
        liveLogViewer.scrollTop = liveLogViewer.scrollHeight;
        
        // Update timeline sidebar
        if (_activeToolState.callId) {
            const statusEl = document.getElementById(`timeline-status-${_activeToolState.callId}`);
            if (statusEl) {
                statusEl.textContent = `${phaseLabel} (${runtime})`;
                if (phaseClass.includes('error') || phaseClass.includes('danger')) {
                    statusEl.style.color = '#e74c3c';
                } else if (phaseClass.includes('success') || phaseClass === 'is-complete') {
                    statusEl.style.color = '#2ecc71';
                }
            }
        }

    }

    function stopActiveToolTicker() {
        if (_activeToolTicker) {
            clearInterval(_activeToolTicker);
            _activeToolTicker = null;
        }
    }

    function ensureActiveToolTicker() {
        if (_activeToolTicker || !_activeToolState) {
            return;
        }
        _activeToolTicker = window.setInterval(() => {
            if (!_activeToolState) {
                stopActiveToolTicker();
                return;
            }
            renderActiveToolEntry();
        }, 1000);
    }

    function beginActiveTool(event, entry) {
        _toolTimelineCounter++;
        const callId = `tool-call-${_toolTimelineCounter}`;
        
        _activeToolState = {
            tool: String(event?.tool || 'Running tool'),
            args: event?.args || {},
            startedAt: Date.now(),
            phase: 'running',
            note: '',
            callId: callId
        };
        _activeToolEntry = entry || null;
        if (_activeToolEntry) {
            _activeToolEntry.id = callId;
        }
        
        // Append to timeline sidebar
        const timelineContainer = document.getElementById('timeline-container');
        if (timelineContainer && event?.tool) {
            let previewStr = '';
            if (event.args && Object.keys(event.args).length > 0) {
                const joinedArgs = Object.values(event.args)
                    .map(v => typeof v === 'string' ? v : JSON.stringify(v))
                    .join(' ')
                    .replace(/\s+/g, ' ')
                    .trim();
                if (joinedArgs) {
                    previewStr = joinedArgs.length > 28 ? ` ${joinedArgs.slice(0, 25)}...` : ` ${joinedArgs}`;
                }
            }
            
            const tlItem = document.createElement('div');
            tlItem.className = 'timeline-item';
            tlItem.id = `timeline-ref-${callId}`;
            tlItem.innerHTML = `
                <div class="timeline-item-title" style="flex-wrap: wrap;">
                    <span><i class="ph ph-wrench"></i> ${escapeHtml(event.tool)}</span>
                    <span style="font-weight: normal; font-size: 0.75rem; opacity: 0.7;">${escapeHtml(previewStr)}</span>
                </div>
                <div class="timeline-item-status" id="timeline-status-${callId}">Running...</div>
            `;
            tlItem.addEventListener('click', () => {
                const target = document.getElementById(callId);
                if (target) {
                    target.scrollIntoView({ behavior: 'smooth', block: 'center' });
                    // Optional flash / highlight effect
                    target.style.background = 'var(--panel-bg)';
                    setTimeout(() => target.style.background = '', 1000);
                }
            });
            timelineContainer.appendChild(tlItem);
            timelineContainer.scrollTop = timelineContainer.scrollHeight;
        }

        renderActiveToolEntry();
        ensureActiveToolTicker();
    }

    function markActiveToolWaiting(message) {
        if (!_activeToolState) {
            return;
        }
        _activeToolState.phase = 'waiting';
        _activeToolState.note = message || 'Paused at a timeout checkpoint and waiting for a decision.';
        renderActiveToolEntry();
        persistLiveLog();
    }

    function clearActiveToolStatus() {
        _activeToolState = null;
        _activeToolEntry = null;
        stopActiveToolTicker();
    }

    function clearLog() {
        liveLogViewer.innerHTML = '';
        _logInitialCleared = false;
        clearActiveToolStatus();
        persistLiveLog();
    }
    function closeSse() {
        if (_eventSource) { _eventSource.close(); _eventSource = null; }
    }

    // ---------------------------------------------------------------
    // Start / Stop Service
    // ---------------------------------------------------------------
    function askToStopSession(runId = null) {
        _sessionToStopId = runId;
        confirmModalOverlay.style.display = 'flex';
    }

    confirmCancelBtn.addEventListener('click', () => {
        confirmModalOverlay.style.display = 'none';
        _sessionToStopId = null;
    });

    confirmStopBtn.addEventListener('click', () => {
        confirmModalOverlay.style.display = 'none';
        if (_sessionToStopId) {
            stopTargetedSession(_sessionToStopId);
        } else {
            stopService();
        }
    });

    chatStopBtn.addEventListener('click', () => askToStopSession(null));

    function closePostToolReplyModal() {
        _awaitingPostToolReplyDecision = false;
        postToolReplyModalOverlay.style.display = 'none';
        retryPostToolReplyBtn.disabled = false;
        cancelPostToolReplyBtn.disabled = false;
    }

    async function resolvePostToolReply(action) {
        if (!_serviceRunning || !_awaitingPostToolReplyDecision) return;

        retryPostToolReplyBtn.disabled = true;
        cancelPostToolReplyBtn.disabled = true;

        try {
            const response = await fetch('/api/session/post_tool_reply_action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action })
            });
            const data = await response.json();

            if (!data.success) {
                throw new Error(data.error || 'Could not resolve post-tool reply decision.');
            }

            closePostToolReplyModal();
        } catch (error) {
            retryPostToolReplyBtn.disabled = false;
            cancelPostToolReplyBtn.disabled = false;
            showAlert(error.message, 'error');
        }
    }

    retryPostToolReplyBtn.addEventListener('click', () => resolvePostToolReply('retry'));
    cancelPostToolReplyBtn.addEventListener('click', () => resolvePostToolReply('cancel'));

    function closeDangerousToolModal() {
        _awaitingDangerousToolApproval = false;
        dangerousToolModalOverlay.style.display = 'none';
        approveDangerousToolBtn.disabled = false;
        cancelDangerousToolBtn.disabled = false;
    }

    async function resolveDangerousToolApproval(action) {
        if (!_serviceRunning || !_awaitingDangerousToolApproval) return;

        approveDangerousToolBtn.disabled = true;
        cancelDangerousToolBtn.disabled = true;

        try {
            const response = await fetch('/api/session/dangerous_tool_action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action })
            });
            const data = await response.json();

            if (!data.success) {
                throw new Error(data.error || 'Could not resolve dangerous tool approval.');
            }

            closeDangerousToolModal();
        } catch (error) {
            approveDangerousToolBtn.disabled = false;
            cancelDangerousToolBtn.disabled = false;
            showAlert(error.message, 'error');
        }
    }

    approveDangerousToolBtn.addEventListener('click', () => resolveDangerousToolApproval('approve'));
    cancelDangerousToolBtn.addEventListener('click', () => resolveDangerousToolApproval('cancel'));

    function closeToolTimeoutModal() {
        _awaitingToolTimeoutDecision = false;
        toolTimeoutModalOverlay.style.display = 'none';
        waitToolTimeoutBtn.disabled = false;
        killToolTimeoutBtn.disabled = false;
    }

    async function resolveToolTimeoutDecision(action) {
        if (!_serviceRunning || !_awaitingToolTimeoutDecision) return;

        waitToolTimeoutBtn.disabled = true;
        killToolTimeoutBtn.disabled = true;

        try {
            const response = await fetch('/api/session/tool_timeout_action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action })
            });
            const data = await response.json();

            if (!data.success) {
                throw new Error(data.error || 'Could not resolve tool timeout decision.');
            }

            closeToolTimeoutModal();
            
            // Immediately reflect the user's decision in the live log UI so they know their click registered
            if (_activeToolState && _activeToolEntry) {
                if (action === 'kill') {
                    _activeToolState.phase = 'killing';
                    _activeToolState.note = "Termination requested. Waiting for process to die...";
                } else {
                    _activeToolState.phase = 'running';
                    _activeToolState.note = "Allowed to continue running...";
                }
                renderActiveToolEntry();
            }
        } catch (error) {
            waitToolTimeoutBtn.disabled = false;
            killToolTimeoutBtn.disabled = false;
            showAlert(error.message, 'error');
        }
    }

    waitToolTimeoutBtn.addEventListener('click', () => resolveToolTimeoutDecision('wait'));
    killToolTimeoutBtn.addEventListener('click', () => resolveToolTimeoutDecision('kill'));

    async function stopTargetedSession(runId) {
        try {
            const response = await fetch(`/api/sessions/${runId}/stop`, { method: 'POST' });
            const data = await response.json();
            if (data.success) {
                showAlert(data.message, 'success');
                loadSessions(); 
                if (runId === _currentRunId) {
                    handleServiceStopped();
                }
            } else {
                throw new Error(data.error || 'Failed to stop session');
            }
        } catch (error) {
            showAlert(error.message);
        } finally {
            _sessionToStopId = null;
        }
    }

    async function stopService() {
        if (!_serviceRunning) {
            console.warn("stopService called but _serviceRunning is false. Checking backend status...");
            const statusRes = await fetch('/api/session/status');
            const statusData = await statusRes.json();
            if (statusData.status === 'idle') return;
            // Otherwise, we might be out of sync, proceed with stop signal
        }
        
        startBtn.disabled = true;
        startBtn.innerHTML = ICON_SVG.SPINNER + '<span>Stopping service…</span>';
        updateStatus('running', 'Stopping service…');

        try {
            const response = await fetch('/api/session/stop', { method: 'POST' });
            const data = await response.json();
            if (data.success) {
                // handleServiceStopped will be called via SSE 'done' or 'service_stopped'
                // But we call it here too for immediate UI feedback
                handleServiceStopped();
                appendLog('Service stop signal sent.', 'log-status');
            } else {
                throw new Error(data.error || 'Failed to stop service');
            }
        } catch (error) {
            showAlert(error.message);
            startBtn.disabled = false;
        }
    }

    startBtn.addEventListener('click', async () => {
        if (_serviceRunning) {
            askToStopSession();
            return;
        }

        const url = ollamaUrlInput.value.trim();
        const provider = normalizeProvider(providerSelect?.value);
        const apiKey = providerUsesApiKey(provider) ? (apiKeyInput?.value.trim() || '') : '';
        const sslVerify = Boolean(sslVerifyToggle?.checked ?? true);
        if (!validateProviderApiKey(provider, apiKey)) {
            return;
        }
        const model = modelSelect.value;
        const cmdType = kaliCommandType.value;
        const contextWindow = parseInt(document.getElementById('context-window').value, 10);
        const maxTurns = parseInt(maxTurnsInput.value, 10);
        const keyloggerEnabled = Boolean(keyloggerEnableToggle?.checked);
        syncPolicyDraftFromEditor();
        const networkPolicy = {
            allow: Array.isArray(_policyDraft.allow) && _policyDraft.allow.length ? [..._policyDraft.allow] : ['*'],
            disallow: Array.isArray(_policyDraft.disallow) ? [..._policyDraft.disallow] : [],
        };

        if (!Number.isInteger(maxTurns) || maxTurns < 1 || maxTurns > 100) {
            showAlert('Max tool/model turns per prompt must be between 1 and 100.', 'error');
            return;
        }

        let command = '';
        if (cmdType === 'python') {
            command = 'python3 mcp_kali.py';
        } else if (cmdType === 'apt') {
            command = 'python3 apt_logger_wrapper.py';
        }

        let toolsConfig = null;
        if (cmdType !== 'apt') {
            updateToolsJson();
            try { toolsConfig = JSON.parse(toolsJsonArea.value); }
            catch (e) { showAlert('Invalid JSON formatting in kali_tools.json editor.', 'error'); return; }
            if (!Array.isArray(toolsConfig.tools) || toolsConfig.tools.length === 0) {
                showAlert('Select at least one Kali tool before starting a native session.', 'error');
                return;
            }
        }

        if (!model || !command) return;

        setConfigEnabled(false);
        startBtn.innerHTML = ICON_SVG.SPINNER + '<span>Starting service…</span>';
        startBtn.disabled = true;
        updateStatus('running', 'Starting service…');

        clearLog();
        liveLogPanel.style.display = 'flex';
        appendLog('<i class="ph ph-spinner-gap spin"></i> Launching MCP service…', 'log-status');

        try {
            const response = await fetch('/api/session/start', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url, provider, api_key: apiKey, ssl_verify: sslVerify, model, server_command: command, tools_config: toolsConfig, context_window: contextWindow, max_turns: maxTurns, network_policy: networkPolicy, keylogger_enabled: keyloggerEnabled, extended_msf_prompt: Boolean(extendedMsfPromptToggle?.checked) })
            });
            const data = await response.json();

            if (data.success) {
                _serviceRunning = true;
                _currentRunId = data.run_id;
                _sessionsById[data.run_id] = {
                    run_id: data.run_id,
                    llm_provider: data.llm_provider || provider,
                    network_policy: data.network_policy || networkPolicy,
                    llm_auth_enabled: Boolean(apiKey),
                    available_tools: Array.isArray(data.tools) ? data.tools : [],
                    available_tool_count: Array.isArray(data.tools) ? data.tools.length : 0,
                    ...(data.metadata || {}),
                };
                persistLiveLog();
                
                // Switch button to Stop state
                startBtn.className = 'btn btn-danger';
                startBtn.innerHTML = ICON_SVG.STOP + '<span>Stop Service</span>';
                startBtn.disabled = false;

                if (data.tools && data.tools.length) {
                    setLiveToolsBadge(data.tools);
                }
                setLivePolicyBadge(data.network_policy || networkPolicy);
                
                updateStatus('running', 'Service Running - Chat Active');
                
                // Switch to Chat tab
                navChatBtn.disabled = false;
                switchTab('chat-pane');
                
                // Enable Chat Console inputs
                updateChatControlAvailability();
                chatPromptInput.disabled = false;
                chatPromptInput.placeholder = "Type your prompt and press Enter to run...";
                sendPromptBtn.disabled = false;
                annotateBtn.disabled = false;
                chatStopBtn.disabled = false;
                chatDownloadBtn.style.display = 'inline-block';

                openSseStream();

                // Start browser keylogger if enabled
                if (keyloggerEnableToggle?.checked && window.BrowserKeylogger) {
                    window.BrowserKeylogger.start(data.run_id);
                }

                showAlert('Service started! Use the Prompt console to chat.', 'success');
                // Clear stale watcher suggestions from any previous session
                if (typeof window.watcherClearSuggestions === 'function') {
                    window.watcherClearSuggestions();
                }
                // Expose session LLM meta to watcher tab for same-LLM detection
                if (typeof window.watcherSetSessionMeta === 'function') {
                    window.watcherSetSessionMeta({
                        url: ollamaUrlInput.value.trim(),
                        model: modelSelect.value,
                        provider: providerSelect?.value || 'ollama_direct',
                        api_key: apiKeyInput?.value?.trim() || '',
                        ssl_verify: Boolean(sslVerifyToggle?.checked ?? true),
                    });
                }
                setTimeout(() => chatPromptInput.focus(), 500);
            } else {
                throw new Error(data.error || 'Failed to start session');
            }
        } catch (error) {
            showAlert(error.message);
            setConfigEnabled(true);
            updateStatus('error', 'Error');
            resetStartBtn();
        }
    });

    function resetStartBtn() {
        startBtn.classList.remove('btn-danger');
        startBtn.classList.add('btn-primary');
        startBtn.innerHTML = ICON_SVG.POWER + '<span>Start Service</span>';
        startBtn.disabled = false;
        startBtn.style.display = 'inline-flex';
    }

    function setConfigEnabled(enabled) {
        const inputs = configPanel.querySelectorAll('input, select, textarea, button');
        inputs.forEach(el => {
            if (el.id === 'start-service-btn' || el.id === 'stop-service-btn' || el.id === 'fetch-models-btn') return;
            
            if (enabled) {
                el.removeAttribute('data-service-disabled');
                el.disabled = el.hasAttribute('data-originally-disabled');
            } else {
                if (el.disabled) el.setAttribute('data-originally-disabled', '');
                el.setAttribute('data-service-disabled', '');
                el.disabled = true;
            }
        });
        if (fetchBtn) {
            fetchBtn.disabled = false;
            fetchBtn.removeAttribute('data-service-disabled');
            fetchBtn.removeAttribute('data-originally-disabled');
        }
        configPanel.classList.toggle('config-disabled', !enabled);
    }

    // ---------------------------------------------------------------
    // Sidebar Action Toggles
    const btnToggleTimeline = document.getElementById('btn-toggle-timeline');
    const chatSidebar = document.getElementById('chat-sidebar');
    if (btnToggleTimeline && chatSidebar) {
        const svgPathLeft = "M165.66,202.34a8,8,0,0,1-11.32,11.32l-80-80a8,8,0,0,1,0-11.32l80-80a8,8,0,0,1,11.32,11.32L91.31,128Z";
        const svgPathRight = "M181.66,133.66l-80,80a8,8,0,0,1-11.32-11.32L164.69,128,90.34,53.66a8,8,0,0,1,11.32-11.32l80,80A8,8,0,0,1,181.66,133.66Z";

        btnToggleTimeline.addEventListener('click', () => {
            chatSidebar.classList.toggle('is-visible');
            const isVisible = chatSidebar.classList.contains('is-visible');
            const pathElem = btnToggleTimeline.querySelector('path');

            if (isVisible) {
                btnToggleTimeline.style.right = '260px'; /* match sidebar width */
                if (pathElem) pathElem.setAttribute('d', svgPathRight);
            } else {
                btnToggleTimeline.style.right = '0';
                if (pathElem) pathElem.setAttribute('d', svgPathLeft);
            }
        });
    }

    // ---------------------------------------------------------------
    // SSE Stream
    // ---------------------------------------------------------------
    function openSseStream() {
        closeSse();
        _eventSource = new EventSource('/api/session/stream');
        _eventSource.onmessage = (ev) => {
            try {
                const event = JSON.parse(ev.data);
                renderEvent(event);
                if (event.type === 'done') { closeSse(); handleServiceStopped(); }
            } catch (err) {}
        };
        _eventSource.onerror = () => {
            closeSse();
            if (_serviceRunning) {
                appendLog('<span class="log-label">⚠️</span> SSE connection lost. Reconnecting…', 'log-status');
                setTimeout(() => { if (_serviceRunning) openSseStream(); }, 2000);
            }
        };
    }

    // ---------------------------------------------------------------
    // Send Chat
    // ---------------------------------------------------------------
    sendPromptBtn.addEventListener('click', () => {
        if (_chatBusy) {
            cancelChat();
        } else {
            sendChat();
        }
    });

    // Hidden clone used to measure desired textarea height without touching the DOM layout.
    let _promptMeasureClone = null;
    function resizeChatPromptInput() {
        const minHeight = 52;
        const maxHeight = 250;

        // Create a hidden off-screen clone once, reuse it for all measurements.
        if (!_promptMeasureClone) {
            _promptMeasureClone = chatPromptInput.cloneNode(false);
            _promptMeasureClone.setAttribute('aria-hidden', 'true');
            _promptMeasureClone.setAttribute('tabindex', '-1');
            Object.assign(_promptMeasureClone.style, {
                position: 'absolute',
                top: '-9999px',
                left: '-9999px',
                visibility: 'hidden',
                height: 'auto',
                overflow: 'hidden',
                whiteSpace: 'pre-wrap',
                wordWrap: 'break-word',
            });
            // Match the real element's sizing
            const cs = getComputedStyle(chatPromptInput);
            _promptMeasureClone.style.width = cs.width;
            _promptMeasureClone.style.paddingTop = cs.paddingTop;
            _promptMeasureClone.style.paddingBottom = cs.paddingBottom;
            _promptMeasureClone.style.paddingLeft = cs.paddingLeft;
            _promptMeasureClone.style.paddingRight = cs.paddingRight;
            _promptMeasureClone.style.borderWidth = cs.borderWidth;
            _promptMeasureClone.style.fontSize = cs.fontSize;
            _promptMeasureClone.style.fontFamily = cs.fontFamily;
            _promptMeasureClone.style.lineHeight = cs.lineHeight;
            _promptMeasureClone.style.boxSizing = cs.boxSizing;
            chatPromptInput.parentNode.appendChild(_promptMeasureClone);
        }

        // Sync clone width in case the layout changed (e.g. window resize).
        _promptMeasureClone.style.width = getComputedStyle(chatPromptInput).width;
        _promptMeasureClone.value = chatPromptInput.value;

        const nextHeight = Math.max(minHeight, Math.min(maxHeight, _promptMeasureClone.scrollHeight));
        chatPromptInput.style.height = `${nextHeight}px`;
    }

    chatPromptInput.addEventListener('input', function() {
        resizeChatPromptInput();
    });

    const PROMPT_HISTORY_MAX = 50;
    const promptHistory = [];
    let promptHistoryIndex = -1;
    let promptCurrentDraft = "";

    chatPromptInput.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            sendChat();
        } else if (e.key === 'ArrowUp') {
            if (chatPromptInput.selectionStart === 0 && chatPromptInput.selectionEnd === 0) {
                if (promptHistoryIndex < 0) {
                    promptHistoryIndex = promptHistory.length;
                }
                if (promptHistoryIndex > 0) {
                    if (promptHistoryIndex === promptHistory.length) {
                        promptCurrentDraft = chatPromptInput.value;
                    }
                    promptHistoryIndex--;
                    chatPromptInput.value = promptHistory[promptHistoryIndex];
                    resizeChatPromptInput();
                    e.preventDefault();
                }
            }
        } else if (e.key === 'ArrowDown') {
            if (chatPromptInput.selectionStart === chatPromptInput.value.length && chatPromptInput.selectionEnd === chatPromptInput.value.length) {
                if (promptHistoryIndex >= 0 && promptHistoryIndex < promptHistory.length) {
                    promptHistoryIndex++;
                    if (promptHistoryIndex === promptHistory.length) {
                        chatPromptInput.value = promptCurrentDraft;
                    } else {
                        chatPromptInput.value = promptHistory[promptHistoryIndex];
                    }
                    resizeChatPromptInput();
                    e.preventDefault();
                }
            }
        }
    });

    async function sendChat() {
        const prompt = chatPromptInput.value.trim();
        if (!prompt || _chatBusy || !_serviceRunning) return;
        const scopeEnabled = isChatScopeEnabled();
        const urgencyEnabled = isChatUrgencyEnabled();
        const scope = scopeEnabled ? getChatScopeConfig().id : null;
        const urgency = urgencyEnabled ? getChatUrgencyConfig().id : null;

        _chatBusy = true;
        
        if (promptHistory.length === 0 || promptHistory[promptHistory.length - 1] !== prompt) {
            promptHistory.push(prompt);
            if (promptHistory.length > PROMPT_HISTORY_MAX) {
                promptHistory.shift();
            }
        }
        promptHistoryIndex = promptHistory.length;
        promptCurrentDraft = "";
        
        chatPromptInput.value = '';
        resizeChatPromptInput();
        chatPromptInput.disabled = true;
        
        // Morph the send button into a stop button
        sendPromptBtn.classList.remove('btn-primary');
        sendPromptBtn.classList.add('btn-danger');
        sendPromptBtn.title = 'Stop agent turn';
        sendPromptBtn.setAttribute('aria-label', 'Stop agent turn');
        sendPromptBtn.innerHTML = ICON_SVG.STOP;

        appendLog(`<span class="log-label">👤 You</span> ${escapeHtml(prompt)}`, 'log-prompt');

        try {
            const response = await fetch('/api/session/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    prompt,
                    scope,
                    urgency,
                    scope_enabled: scopeEnabled,
                    urgency_enabled: urgencyEnabled,
                })
            });
            const data = await response.json();
            if (!data.success) {
                appendLog(`<span class="log-label">❌ Error</span> ${escapeHtml(data.error || 'Chat failed.')}`, 'log-error');
            }
        } catch (error) {
            appendLog(`<span class="log-label">❌ Error</span> ${escapeHtml(error.message)}`, 'log-error');
            setChatReady();
        }
    }

    function setChatReady() {
        _chatBusy = false;
        clearActiveToolStatus();
        closePostToolReplyModal();
        closeToolTimeoutModal();
        
        // Restore the send button
        sendPromptBtn.classList.remove('btn-danger', 'btn-secondary');
        sendPromptBtn.classList.add('btn-primary');
        sendPromptBtn.title = 'Send prompt';
        sendPromptBtn.setAttribute('aria-label', 'Send prompt');
        sendPromptBtn.disabled = false;
        sendPromptBtn.innerHTML = ICON_SVG.SEND;

        if (_serviceRunning) {
            chatPromptInput.disabled = false;
            chatPromptInput.focus();
        }
    }

    async function cancelChat() {
        if (!_chatBusy || !_serviceRunning) return;
        
        // Disable the stop button and turn into spinner so they can't spam it
        sendPromptBtn.innerHTML = ICON_SVG.SPINNER;

        appendLog('<span class="log-label">⏹️</span> Cancelling prompt...', 'log-status');
        
        try {
            await fetch('/api/session/cancel_prompt', { method: 'POST' });
        } catch (error) {
            appendLog(`<span class="log-label">❌ Error</span> ${escapeHtml('Failed to send cancel signal.')}`, 'log-error');
            sendPromptBtn.disabled = false;
            sendPromptBtn.title = 'Stop agent turn';
            sendPromptBtn.setAttribute('aria-label', 'Stop agent turn');
            sendPromptBtn.innerHTML = ICON_SVG.STOP;
        }
    }

    window.stopCurrentTool = async function(event) {
        if (event) event.preventDefault();
        if (_activeToolState) {
            _activeToolState.stopping = true;
            renderActiveToolEntry();
        }
        
        try {
            const resp = await fetch('/api/session/stop_tool', { method: 'POST' });
            const data = await resp.json();
            if (data.success) {
                appendLog(`<span class="log-label">⏹ Info</span> Stop signal sent to tool. Waiting for final output...`, 'log-info');
            } else {
                appendLog(`<span class="log-label">❌ Error</span> ${escapeHtml(data.error || 'Failed to stop tool.')}`, 'log-error');
                if (_activeToolState) {
                    _activeToolState.stopping = false;
                    renderActiveToolEntry();
                }
            }
        } catch (err) {
            appendLog(`<span class="log-label">❌ Error</span> Failed to contact server: ${escapeHtml(err.message)}`, 'log-error');
            if (_activeToolState) {
                _activeToolState.stopping = false;
                renderActiveToolEntry();
            }
        }
    };

    // ---------------------------------------------------------------
    // Annotations & Live Analysis
    // ---------------------------------------------------------------
    annotateBtn.addEventListener('click', (e) => {
        if (!_serviceRunning) return;
        e.stopPropagation();
        annotationMenu.classList.toggle('show');
    });

    // Close dropdown on click-away
    window.addEventListener('click', () => {
        annotationMenu.classList.remove('show');
    });

    annotationMenu.querySelectorAll('li').forEach(item => {
        item.addEventListener('click', () => {
            const action = item.getAttribute('data-action');
            openAnnotationModal(action);
        });
    });

    function openAnnotationModal(action) {
        if (!_serviceRunning) return;
        if (action === 'analyze') {
            annotationMenu.classList.remove('show');
            openAnalysisConfigModal({
                suggestedUrl: ollamaUrlInput.value.trim(),
                suggestedProvider: normalizeProvider(providerSelect?.value),
                suggestedApiKey: apiKeyInput?.value.trim() || '',
                suggestedSslVerify: Boolean(sslVerifyToggle?.checked ?? true),
                suggestedModel: modelSelect.value,
                title: 'Analyze Live Logs',
                description: 'Choose a log window plus the Ollama instance and model for this background analysis job.',
                includeSpan: true,
                defaultSpan: 'Event Point',
                confirmLabel: 'Run Analysis',
            }).then(async analysisConfig => {
                if (!analysisConfig || !_currentRunId) {
                    return;
                }

                try {
                    const response = await fetch(`/api/sessions/${_currentRunId}/analyze`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(analysisConfig)
                    });
                    const data = await response.json();

                    if (data.success) {
                        showAlert('Background analysis job started. Check the Analysis Jobs tab.', 'success');
                        switchTab('analysis-pane');
                        loadAnalysisJobs();
                        startAnalysisJobsPolling();
                    } else {
                        showAlert('Live Analysis failed: ' + (data.error || 'Unknown error'), 'error');
                    }
                } catch (err) {
                    showAlert('Failed to analyze logs: ' + err.message, 'error');
                }
            });
            return;
        }

        annotationModalOverlay.style.display = 'flex';
        annotationAction.value = action;

        if (action === 'annotate') {
            modalTitle.innerHTML = '<i class="ph ph-note-pencil"></i> Add Observation';
            annotationTextGroup.style.display = 'flex';
            saveAnnotationBtn.textContent = 'Save Note';
            setTimeout(() => annotationText.focus(), 100);
        } else {
            modalTitle.innerHTML = '<i class="ph ph-note-pencil"></i> Add Observation';
            annotationTextGroup.style.display = 'flex';
            saveAnnotationBtn.textContent = 'Save Note';
        }
        annotationMenu.classList.remove('show');
    }

    const closeAndResetModal = () => {
        annotationModalOverlay.style.display = 'none';
        annotationText.value = '';
        annotationSpan.value = 'Event Point';
        annotationAction.value = 'annotate';
        annotationTextGroup.style.display = 'flex';
        saveAnnotationBtn.textContent = 'Save Note';
    };

    closeAnnotationBtn.addEventListener('click', closeAndResetModal);
    cancelAnnotationBtn.addEventListener('click', closeAndResetModal);

    // Also close on overlay click
    annotationModalOverlay.addEventListener('click', (e) => {
        if (e.target === annotationModalOverlay) closeAndResetModal();
    });

    saveAnnotationBtn.addEventListener('click', async () => {
        const action = annotationAction.value;
        const text = annotationText.value.trim();
        const span = annotationSpan.value;
        if (!_currentRunId) {
            showAlert('Cannot save: No active session ID found.', 'error');
            return;
        }
        if (action === 'annotate' && !text) {
            showAlert('Please enter an observation note.', 'warning');
            return;
        }

        saveAnnotationBtn.disabled = true;
        saveAnnotationBtn.textContent = action === 'analyze' ? 'Running...' : 'Saving...';

        try {
            if (action === 'annotate') {
                const response = await fetch(`/api/sessions/${_currentRunId}/annotate`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ text, span })
                });
                const data = await response.json();
                
                if (data.success) {
                    appendLog(`<span class="log-label">📝 Annotation saved</span> <em>Scope: ${span}</em><br/>${escapeHtml(text)}`, 'log-prompt');
                    closeAndResetModal();
                } else {
                    showAlert('Failed to save annotation: ' + (data.error || 'Unknown error'), 'error');
                }
            } else {
                showAlert('Unsupported annotation action.', 'error');
            }
        } catch (err) {
            showAlert(`Failed to ${action}: ` + err.message, 'error');
        } finally {
            saveAnnotationBtn.disabled = false;
            saveAnnotationBtn.textContent = 'Save Note';
        }
    });

    // Stop Service (Handled by startBtn toggle)
    // ---------------------------------------------------------------
    function handleServiceStopped() {
        if (!_serviceRunning && statusText.textContent === 'Idle') return; // Already cleaned up

        const stoppedRunId = _currentRunId;
        _serviceRunning = false;
        _chatBusy = false;
        _currentRunId = null;
        _logInitialCleared = false; // Reset for next run
        updateStatus('success', 'Service Stopped');
        clearActiveToolStatus();
        closePostToolReplyModal();
        closeToolTimeoutModal();

        if (stoppedRunId) {
            persistLiveLog(stoppedRunId);
        }
        
        resetStartBtn();
        setConfigEnabled(true);
        setLiveToolsBadge([]);
        setLivePolicyBadge(null);
        
        // Clear isess tabs
        const isessTabs = chatTabBar.querySelectorAll('.chat-tab:not([data-tab-id="main"])');
        isessTabs.forEach(t => t.remove());
        const isessPanels = chatTabsContent.querySelectorAll('.chat-tab-panel:not(#chat-tab-main)');
        isessPanels.forEach(p => p.remove());
        switchChatTab('main');
        
        // Disable active chat inputs
        updateChatControlAvailability();
        chatPromptInput.disabled = true;
        chatPromptInput.placeholder = "Start the service in the Configuration tab to begin...";
        
        sendPromptBtn.classList.remove('btn-danger', 'btn-secondary');
        sendPromptBtn.classList.add('btn-primary');
        sendPromptBtn.title = 'Send prompt';
        sendPromptBtn.setAttribute('aria-label', 'Send prompt');
        sendPromptBtn.innerHTML = ICON_SVG.SEND;
        sendPromptBtn.disabled = true;
        
        annotateBtn.disabled = true;
        chatStopBtn.disabled = true;
        chatDownloadBtn.style.display = 'none';

        // We DON'T force a tab switch to config here anymore to prevent jarring jumps.
        // The user can switch back when they are ready to reconfigure.
        // Just disable the Live Chat tab if we're not on it, or let them see logs.
        navChatBtn.disabled = true; 

        loadSessions(); // Refresh history

        // Stop browser keylogger
        if (window.BrowserKeylogger?.getStatus().enabled) {
            window.BrowserKeylogger.stop();
        }

        // Notify the watcher tab that the session stopped
        if (typeof window.watcherHandleSessionStopped === 'function') {
            window.watcherHandleSessionStopped();
        }
    }

    // ---------------------------------------------------------------
    // SSE Event Rendering
    // ---------------------------------------------------------------
    function renderEvent(event) {
        switch (event.type) {
            case 'prompt':
                appendLog(`<span class="log-label">👤 Prompt</span> ${escapeHtml(event.text)}`, 'log-prompt'); break;
            case 'response':
                appendLog(`<span class="log-label">🤖 Response</span>\n<pre class="log-pre">${escapeHtml(event.text)}</pre>`, 'log-response'); break;
            case 'tool_call': {
                const entry = appendLog('', 'log-tool-call');
                beginActiveTool(event, entry);
                persistLiveLog();
                break;
            }
            case 'tool_result': {
                const label = event.graceful_stop ? 'Stopped' : (event.exit_code === 0 ? 'Completed' : 'Failed');
                const chipClass = event.graceful_stop ? 'is-waiting' : (event.exit_code === 0 ? 'is-complete' : 'is-error');
                finalizeActiveToolEntry(
                    `Finished in ${formatElapsedDuration(event.duration_ms || 0)}.`,
                    chipClass,
                    label,
                    event.duration_ms,
                );
                clearActiveToolStatus();
                const exitBadge = event.exit_code === 0 ? `<span class="exit-ok">exit 0</span>` : `<span class="exit-err">exit ${event.exit_code}</span>`;
                appendLog(`<span class="log-label">📋 Result</span> <strong>${escapeHtml(event.tool)}</strong> ${exitBadge} (${event.duration_ms}ms)\n<pre class="log-pre">${escapeHtml(event.result || '(no output)')}</pre>`, 'log-tool-result');
                break;
            }
            case 'status': {
                const transientRecoveryStatuses = [
                    'Model still failed to produce a final reply after an automatic retry. Waiting for user decision: retry again or cancel and restore.',
                    'Model returned an empty post-tool reply; retrying once without tools for a final answer …',
                ];
                if (!transientRecoveryStatuses.includes(event.message || '')) {
                    appendLog(`<span class="log-label">ℹ️ Status</span> ${escapeHtml(event.message)}`, 'log-status');
                }
                break;
            }
            case 'context_usage': updateContextBar(event); break;
            case 'service_started': appendLog(`<span class="log-label">🟢 Service Started</span>`, 'log-done'); break;
            case 'service_stopped':
                finalizeActiveToolEntry('Stopped before a result event was received.', 'is-error', 'Stopped');
                clearActiveToolStatus();
                appendLog(`<span class="log-label">🔴 Service Stopped</span>`, 'log-status');
                break;
            case 'post_tool_reply_decision':
                _awaitingPostToolReplyDecision = true;
                postToolReplyMessage.textContent = event.message || 'The model completed the tool calls, returned an empty final reply, and then failed one automatic final-answer retry.';
                postToolReplyModalOverlay.style.display = 'flex';
                break;
            case 'dangerous_tool_approval':
                _awaitingDangerousToolApproval = true;
                dangerousToolMessage.textContent = event.message || 'The model requested a dangerous shell command.';
                dangerousToolCommand.textContent = String(event.command || '');
                dangerousToolModalOverlay.style.display = 'flex';
                break;
            case 'tool_timeout_decision':
                _awaitingToolTimeoutDecision = true;
                markActiveToolWaiting('Paused at a timeout checkpoint. Waiting for your decision to keep running or stop it.');
                toolTimeoutMessage.textContent = event.message || 'A tool reached its timeout checkpoint.';
                toolTimeoutCommand.textContent = String(event.command || '');
                toolTimeoutModalOverlay.style.display = 'flex';
                break;
            case 'chat_done':
                appendLog(`<span class="log-label">✅ Turn Complete</span> ${escapeHtml(event.message || 'Ready for next prompt.')}`, 'log-done');
                setChatReady(); break;
            case 'error':
                finalizeActiveToolEntry('Interrupted before a result event was received.', 'is-error', 'Interrupted');
                clearActiveToolStatus();
                appendLog(`<span class="log-label">❌ Error</span>\n<pre class="log-pre log-error-text">${escapeHtml(event.message)}</pre>`, 'log-error');
                updateStatus('error', 'Error'); setChatReady(); break;
            case 'done': appendLog(`<span class="log-label">⏹️ Done</span>`, 'log-done'); break;
            case 'tool_suggestion':
                if (typeof window.watcherAddSuggestion === 'function') {
                    window.watcherAddSuggestion(event);
                }
                break;
            case 'watcher_note_start':
                if (typeof window.watcherNoteStart === 'function') window.watcherNoteStart(event);
                break;
            case 'watcher_note_token':
                if (typeof window.watcherNoteToken === 'function') window.watcherNoteToken(event);
                break;
            case 'watcher_note_complete':
                if (typeof window.watcherNoteComplete === 'function') window.watcherNoteComplete(event);
                break;
            case 'isess_created': {
                // _emit() spreads fields to top-level; handle both shapes for safety
                const sid = event.session_id || (event.data && event.data.session_id);
                const tool = event.tool || (event.data && event.data.tool) || '';
                const argsSummary = event.args_summary || (event.data && event.data.args_summary) || '';
                if (sid) createTerminalTab(sid, tool, argsSummary);
                break;
            }
            case 'isess_output': {
                const osid = (event.data && event.data.session_id) || event.session_id;
                const otext = (event.data && event.data.output) || event.output || '';
                if (osid && otext) {
                    appendIsessLog(osid, otext, 'log-tool-result');
                    
                    // Enable input once real output arrives
                    const inputEl = document.getElementById(`input-${osid}`);
                    if (inputEl && inputEl.disabled) {
                        inputEl.disabled = false;
                        inputEl.placeholder = `Type a command for ${osid} and press Enter...`;
                        // Focus if current tab
                        const activeTab = document.querySelector('.chat-tab.active');
                        if (activeTab && activeTab.dataset.tabId === osid) {
                            inputEl.focus();
                        }
                    }
                }
                break;
            }
            case 'isess_closed': {
                const csid = (event.data && event.data.session_id) || event.session_id;
                if (csid) markSessionClosed(csid);
                break;
            }
            case 'watcher_analysis_note':
                if (typeof window.watcherAddAnalysisNote === 'function') window.watcherAddAnalysisNote(event);
                break;
        }
    }

    function updateContextBar(event) {
        const bar = document.getElementById('context-usage-bar');
        const fill = document.getElementById('context-usage-fill');
        const text = document.getElementById('context-usage-text');
        const modelMaxEl = document.getElementById('context-model-max');
        bar.style.display = 'block';
        const used = event.used || 0;
        const budget = event.budget || 8192;
        const pct = Math.min(100, Math.round((used / budget) * 100));
        text.textContent = `${used.toLocaleString()} / ${budget.toLocaleString()} tokens (${pct}%)`;
        modelMaxEl.textContent = `model max: ${(event.model_max || budget).toLocaleString()}`;
        fill.style.width = pct + '%';
        fill.classList.remove('ctx-green', 'ctx-amber', 'ctx-red');
        if (pct < 50) fill.classList.add('ctx-green');
        else if (pct < 75) fill.classList.add('ctx-amber');
        else fill.classList.add('ctx-red');
    }

    // ---------------------------------------------------------------
    // Sessions Browser
    // ---------------------------------------------------------------
    let _browseRunId = null, _currentTab = 'transcript';
    const sessionsList = document.getElementById('sessions-list'), sessionDetail = document.getElementById('session-detail'), detailContent = document.getElementById('detail-content');

    async function loadSessions() {
        try {
            const res = await fetch('/api/sessions'); const data = await res.json();
            _sessionsById = Object.fromEntries((data.sessions || []).map(session => [session.run_id, session]));
            renderSessionList(data.sessions || []);
        } catch (e) { sessionsList.innerHTML = '<div class="empty-state">Could not load sessions.</div>'; }
    }

    function renderSessionList(sessions) {
        if (!sessions.length) { sessionsList.innerHTML = '<div class="empty-state">No sessions yet. Run an agent to start logging.</div>'; return; }
        sessionsList.innerHTML = sessions.map(s => {
            return `
            <div class="session-card ${s.run_id === _browseRunId ? 'active' : ''}" data-run="${s.run_id}">
                <div class="session-card-left">
                    <span class="session-run-id">${s.run_id}</span>
                    <span class="session-meta">${s.start_time ? new Date(s.start_time).toLocaleString() : '—'}</span>
                </div>
                <div style="display: flex; align-items: center;">
                    <span class="session-status ${s.status || 'unknown'}">${s.status || 'unknown'}</span>
                    ${s.status === 'running' ? `<button class="btn-stop-session" title="Stop Running Session" data-stop-run="${s.run_id}">${ICON_SVG.STOP}</button>` : ''}
                </div>
            </div>`;
        }).join('');
        
        sessionsList.querySelectorAll('.session-card').forEach(card => card.addEventListener('click', (e) => {
            if (e.target.closest('.btn-stop-session')) return; // Ignore card click if stop button pressed
            openSession(card.dataset.run)
        }));

        sessionsList.querySelectorAll('.btn-stop-session').forEach(btn => btn.addEventListener('click', (e) => {
            e.stopPropagation();
            askToStopSession(btn.dataset.stopRun);
        }));
    }

    async function openSession(runId) {
        _browseRunId = runId; sessionDetail.style.display = 'block';
        sessionsList.querySelectorAll('.session-card').forEach(c => c.classList.toggle('active', c.dataset.run === runId));
        sessionDownloadBtn.style.display = 'inline-block';
        sessionAnalyzeBtn.style.display = 'inline-block';
        renderSessionSummary(_sessionsById[runId]);
        if (_analysisCache[runId]) tabAnalysis.style.display = 'inline-block';
        await renderTab(_currentTab === 'analysis' && !_analysisCache[runId] ? 'transcript' : _currentTab);
    }

    function parseRecommendedToolingAssets(responseText) {
        const source = String(responseText || '');
        const headingRegex = /^#{1,6}\s+Recommended Tooling Assets\s*$/gim;
        const headingMatch = headingRegex.exec(source);
        if (!headingMatch) {
            return { assets: [], markdownWithoutSection: source };
        }

        const sectionStart = headingMatch.index;
        const afterHeadingIndex = headingRegex.lastIndex;
        const trailingText = source.slice(afterHeadingIndex);
        const nextHeadingOffset = trailingText.search(/\n#{1,6}\s+/m);
        const sectionEnd = nextHeadingOffset >= 0 ? afterHeadingIndex + nextHeadingOffset + 1 : source.length;
        const sectionBody = source.slice(afterHeadingIndex, sectionEnd).trim();
        const markdownWithoutSection = `${source.slice(0, sectionStart).trimEnd()}\n\n${source.slice(sectionEnd).trimStart()}`.trim();

        const assets = [];
        const fieldOrder = [
            'Type',
            'Name',
            'Problem',
            'Expected Gain',
            'Why Better Than Prompting Alone',
            'Starter Prompt',
        ];
        const fieldSet = new Set(fieldOrder.map(field => field.toLowerCase()));
        let currentAsset = null;
        let currentField = null;

        sectionBody.split(/\r?\n/).forEach(rawLine => {
            const line = rawLine.trimEnd();
            const fieldMatch = line.match(/^\s*-\s*(Type|Name|Problem|Expected Gain|Why Better Than Prompting Alone|Starter Prompt):\s*(.*)$/i);
            if (fieldMatch) {
                const fieldName = fieldOrder.find(field => field.toLowerCase() === fieldMatch[1].toLowerCase());
                if (!fieldName) {
                    return;
                }
                if (fieldName === 'Type') {
                    if (currentAsset && Object.keys(currentAsset).length) {
                        assets.push(currentAsset);
                    }
                    currentAsset = {};
                }
                if (!currentAsset) {
                    currentAsset = {};
                }
                currentField = fieldName;
                currentAsset[currentField] = fieldMatch[2].trim();
                return;
            }

            if (!currentAsset || !currentField) {
                return;
            }

            const trimmed = line.trim();
            if (!trimmed) {
                return;
            }

            const potentialField = trimmed.match(/^-\s*([^:]+):/);
            if (potentialField && fieldSet.has(potentialField[1].trim().toLowerCase())) {
                return;
            }

            currentAsset[currentField] = currentAsset[currentField]
                ? `${currentAsset[currentField]}\n${trimmed}`
                : trimmed;
        });

        if (currentAsset && Object.keys(currentAsset).length) {
            assets.push(currentAsset);
        }

        return { assets, markdownWithoutSection };
    }

    function renderRecommendedToolingAssets(assets) {
        if (!Array.isArray(assets) || !assets.length) {
            return '';
        }

        return `
            <section class="analysis-tool-assets">
                <div class="analysis-tool-assets-header">
                    <span class="analysis-tool-assets-kicker">Structured Section</span>
                    <h4>Recommended Tooling Assets</h4>
                </div>
                <div class="analysis-tool-assets-grid">
                    ${assets.map(asset => {
                        const type = escapeHtml(asset.Type || 'Unspecified');
                        const name = escapeHtml(asset.Name || 'Unnamed asset');
                        const problem = marked.parseInline(escapeHtml(asset.Problem || 'Not provided.'));
                        const gain = marked.parseInline(escapeHtml(asset['Expected Gain'] || 'Not provided.'));
                        const why = marked.parseInline(escapeHtml(asset['Why Better Than Prompting Alone'] || 'Not provided.'));
                        const starterPrompt = escapeHtml(asset['Starter Prompt'] || 'Not provided.');

                        return `
                            <article class="analysis-tool-card">
                                <div class="analysis-tool-card-topline">
                                    <span class="analysis-tool-type">${type}</span>
                                    <h5>${name}</h5>
                                </div>
                                <dl class="analysis-tool-card-fields">
                                    <div>
                                        <dt>Problem</dt>
                                        <dd>${problem}</dd>
                                    </div>
                                    <div>
                                        <dt>Expected Gain</dt>
                                        <dd>${gain}</dd>
                                    </div>
                                    <div>
                                        <dt>Why Better Than Prompting Alone</dt>
                                        <dd>${why}</dd>
                                    </div>
                                    <div>
                                        <dt>Starter Prompt</dt>
                                        <dd><pre>${starterPrompt}</pre></dd>
                                    </div>
                                </dl>
                            </article>
                        `;
                    }).join('')}
                </div>
            </section>
        `;
    }

    function renderAnalysisResponseContent(responseSource) {
        const responseText = String(responseSource || '').trim();
        if (!responseText) {
            return '<p>No response captured yet.</p>';
        }

        const { assets, markdownWithoutSection } = parseRecommendedToolingAssets(responseText);
        const markdownSource = String(markdownWithoutSection || responseText).trim();
        const renderedMarkdown = markdownSource ? marked.parse(markdownSource) : '';
        const assetsSection = renderRecommendedToolingAssets(assets);

        return `
            <div class="analysis-response-layout">
                ${assetsSection}
                <div class="markdown-body analysis-markdown">
                    ${renderedMarkdown || '<p>No response captured yet.</p>'}
                </div>
            </div>
        `;
    }

    async function renderTab(tab) {
        _currentTab = tab;
        document.querySelectorAll('.detail-tab').forEach(t => t.classList.toggle('active', t.dataset.tab === tab));
        if (tab === 'transcript') {
            try { const res = await fetch(`/api/sessions/${_browseRunId}/transcript`); const data = await res.json(); detailContent.innerHTML = `<pre>${escapeHtml(data.content || '(empty)')}</pre>`; } catch { detailContent.innerHTML = '<div class="empty-state">Could not load transcript.</div>'; }
        } else if (tab === 'tool_calls') {
            try { 
                const res = await fetch(`/api/sessions/${_browseRunId}/tool_calls`); const data = await res.json(); const tcs = data.tool_calls || [];
                if (!tcs.length) { detailContent.innerHTML = '<div class="empty-state">No tool calls recorded.</div>'; return; }
                detailContent.innerHTML = tcs.map(tc => `<div class="tool-call-card"><div class="tool-call-header"><span class="tool-call-name"><i class="ph ph-wrench"></i> ${escapeHtml(tc.tool)}</span><span class="tool-call-meta">${tc.duration_ms}ms</span></div><div class="tool-call-result">${escapeHtml(tc.result || '(no output)')}</div></div>`).join('');
            } catch { detailContent.innerHTML = '<div class="empty-state">Could not load tool calls.</div>'; }
        } else if (tab === 'artifacts') {
            try {
                const res = await fetch(`/api/sessions/${_browseRunId}/artifacts`); const data = await res.json(); const arts = data.artifacts || [];
                if (!arts.length) { detailContent.innerHTML = '<div class="empty-state">No artifacts saved.</div>'; return; }
                detailContent.innerHTML = `<ul class="artifact-list">${arts.map(a => `<li class="artifact-item" data-artifact="${escapeHtml(a)}"><i class="ph ph-file-text"></i> ${escapeHtml(a)}</li>`).join('')}</ul>`;
                detailContent.querySelectorAll('.artifact-item').forEach(el => el.addEventListener('click', () => openArtifact(el.dataset.artifact)));
            } catch { detailContent.innerHTML = '<div class="empty-state">Could not load artifacts.</div>'; }
        } else if (tab === 'analysis') {
            if (_analysisCache[_browseRunId]) {
                let assetsHtml = '';
                try {
                    const res = await fetch(`/api/sessions/${_browseRunId}/scaffolding`);
                    const data = await res.json();
                    if (data.success && data.assets && data.assets.length > 0) {
                        assetsHtml = `
                            <div class="scaffolding-assets-container" style="margin-bottom: 2rem; padding: 1.5rem; background: rgba(var(--accent-primary-rgb, 100, 100, 255), 0.05); border-radius: 8px; border: 1px solid rgba(var(--accent-primary-rgb, 100, 100, 255), 0.2);">
                                <h4 style="margin-top: 0; color: var(--accent-primary); display: flex; align-items: center; gap: 0.5rem;"><i class="ph ph-cube"></i> Generated Scaffolding Ready to Build</h4>
                                <p class="input-hint" style="margin-bottom: 1rem;">The analysis engine extracted these assets. Click Generate to open an interactive Claude Code session and build them immediately.</p>
                                <div class="assets-grid" style="display: grid; grid-template-columns: repeat(auto-fill, minmax(280px, 1fr)); gap: 1rem;">
                                    ${data.assets.map(a => `
                                        <div class="asset-card config-card-lite" style="display: flex; flex-direction: column; justify-content: space-between;">
                                            <div style="font-weight: 600; font-size: 1.1rem; margin-bottom: 1rem;">${escapeHtml(a.name)}</div>
                                            <button type="button" class="btn btn-primary btn-generate-asset" data-asset-name="${escapeHtml(a.name)}" style="width: 100%; justify-content: center;">
                                                <i class="ph ph-robot"></i> Generate
                                            </button>
                                        </div>
                                    `).join('')}
                                </div>
                            </div>
                        `;
                    }
                } catch (e) {
                    console.error("Failed to load scaffolding assets", e);
                }
                
                detailContent.innerHTML = `<div class="analysis-result" style="padding: 1rem;">${assetsHtml}${renderAnalysisResponseContent(_analysisCache[_browseRunId])}</div>`;
                
                // Add event listeners for the new buttons
                detailContent.querySelectorAll('.btn-generate-asset').forEach(btn => {
                    btn.addEventListener('click', () => {
                        openAssetConfigModal(btn.dataset.assetName, _browseRunId);
                    });
                });
            } else {
                detailContent.innerHTML = '<div class="empty-state">No analysis generated yet. Click "Analyze Session" to run inference.</div>';
            }
        }
    }

    async function openArtifact(filename) {
        try { const res = await fetch(`/api/sessions/${_browseRunId}/artifacts/${filename}`); const data = await res.json(); detailContent.innerHTML = `<div style="margin-bottom:0.5rem;"><button onclick="renderTab('artifacts')" style="background:none;border:none;color:var(--accent-primary);cursor:pointer;">← Back</button> &nbsp;${escapeHtml(filename)}</div><pre>${escapeHtml(data.content || '(empty)')}</pre>`; } catch { detailContent.innerHTML = '<div class="empty-state">Could not load artifact.</div>'; }
    }

    function downloadFilenameFromResponse(response, fallbackName) {
        const disposition = response.headers.get('Content-Disposition') || '';
        const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
        if (utf8Match?.[1]) {
            return decodeURIComponent(utf8Match[1]);
        }
        const asciiMatch = disposition.match(/filename="?([^";]+)"?/i);
        if (asciiMatch?.[1]) {
            return asciiMatch[1];
        }
        return fallbackName;
    }

    async function downloadSessionArchive(runId) {
        if (!runId) {
            return;
        }

        try {
            const response = await fetch(`/api/sessions/${runId}/download`);
            if (!response.ok) {
                throw new Error(`Download failed (${response.status})`);
            }

            const blob = await response.blob();
            const downloadUrl = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = downloadUrl;
            link.download = downloadFilenameFromResponse(response, `acosta_kali_mcp_run_${runId}.zip`);
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(downloadUrl);
        } catch (err) {
            showAlert(`Failed to download archive: ${err.message}`, 'error');
        }
    }

    document.getElementById('detail-tabs').addEventListener('click', e => { const tab = e.target.closest('.detail-tab'); if (tab && _browseRunId) renderTab(tab.dataset.tab); });
    document.getElementById('refresh-sessions-btn').addEventListener('click', loadSessions);

    chatDownloadBtn.addEventListener('click', async () => {
        await downloadSessionArchive(_currentRunId);
    });
    
    sessionDownloadBtn.addEventListener('click', async () => {
        await downloadSessionArchive(_browseRunId);
    });
    
    sessionAnalyzeBtn.addEventListener('click', async () => {
        if (!_browseRunId) return;

        const analysisConfig = await openAnalysisConfigModal({
            suggestedUrl: ollamaUrlInput.value.trim(),
            suggestedProvider: normalizeProvider(_sessionsById[_browseRunId]?.llm_provider || providerSelect?.value),
            suggestedApiKey: apiKeyInput?.value.trim() || '',
            suggestedSslVerify: Boolean(_sessionsById[_browseRunId]?.ssl_verify ?? sslVerifyToggle?.checked ?? true),
            suggestedModel: modelSelect.value,
            title: 'Analyze Session',
            description: 'Choose which Ollama instance and model should be used for this session analysis job.',
            fixedSpan: 'Entire Session',
        });
        if (!analysisConfig) {
            return;
        }

        const originalText = sessionAnalyzeBtn.innerHTML;
        sessionAnalyzeBtn.innerHTML = '<i class="ph ph-spinner ph-spin"></i> Analyzing...';
        sessionAnalyzeBtn.disabled = true;

        try {
            const res = await fetch(`/api/sessions/${_browseRunId}/analyze`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(analysisConfig)
            });
            const data = await res.json();
            
            if (data.success) {
                showAlert('Background analysis job started.', 'success');
                switchTab('analysis-pane');
                loadAnalysisJobs();
                startAnalysisJobsPolling();
            } else {
                showAlert('Analysis failed: ' + (data.error || 'Unknown error'), 'error');
            }
        } catch (err) {
            showAlert('Failed to analyze session: ' + err.message, 'error');
        } finally {
            sessionAnalyzeBtn.innerHTML = originalText;
            sessionAnalyzeBtn.disabled = false;
        }
    });

    async function checkServiceStatus() {
        try {
            const response = await fetch('/api/session/status');
            const data = await response.json();
            
            if (data.status === 'running' || data.status === 'starting') {
                console.log("Service is already active, restoring UI state...", data);
                _serviceRunning = true;
                _currentRunId = data.run_id;
                if (data.metadata?.run_id) {
                    _sessionsById[data.metadata.run_id] = data.metadata;
                }

                // Sync UI elements
                setConfigEnabled(false);
                startBtn.className = 'btn btn-danger';
                startBtn.innerHTML = ICON_SVG.STOP + '<span>Stop Service</span>';
                startBtn.disabled = false;

                updateStatus('running', 'Service Running - Chat Active');

                if (Array.isArray(data.metadata?.available_tools) && data.metadata.available_tools.length) {
                    setLiveToolsBadge(data.metadata.available_tools);
                }
                setLivePolicyBadge(data.metadata?.network_policy || null);

                if (!restoreLiveLog(_currentRunId)) {
                    _logInitialCleared = liveLogViewer.children.length > 0;
                }
                
                // Enable Chat Console inputs
                navChatBtn.disabled = false;
                updateChatControlAvailability();
                chatPromptInput.disabled = false;
                chatPromptInput.placeholder = "Type your prompt and press Enter to run...";
                sendPromptBtn.disabled = false;
                annotateBtn.disabled = false;
                chatStopBtn.disabled = false;
                chatDownloadBtn.style.display = 'inline-block';

                // Re-open log stream
                openSseStream();
                
                // Optional: switch to chat tab if running
                switchTab('chat-pane');
            } else {
                setLiveToolsBadge([]);
                setLivePolicyBadge(null);
                const lastRunId = localStorage.getItem(LAST_ACTIVE_RUN_STORAGE_KEY);
                if (lastRunId) {
                    restoreLiveLog(lastRunId);
                }
            }
        } catch (err) {
            console.error("Failed to check initial service status:", err);
        }
    }

    function escapeHtml(str) { return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;'); }
    
    // Initialize
    loadSessions();
    checkServiceStatus();
    
    // ---------------------------------------------------------------
    // Analysis Job Management
    // ---------------------------------------------------------------
    async function loadAnalysisJobs() {
        try {
            const res = await fetch('/api/analysis/jobs');
            const data = await res.json();
            renderAnalysisJobs(data.jobs || []);
        } catch (err) {
            console.error('Failed to load analysis jobs:', err);
        }
    }

    function buildAnalysisJobSummary(jobs) {
        const counts = { all: jobs.length, initial: 0, rewrite: 0, fallback: 0, failed: 0 };
        jobs.forEach(job => {
            const path = String(job.completion_path || '').toLowerCase();
            if (Object.prototype.hasOwnProperty.call(counts, path)) {
                counts[path] += 1;
            }
        });
        return counts;
    }

    function renderAnalysisJobsSummary(jobs) {
        if (!analysisJobsSummary) {
            return;
        }

        if (!jobs.length) {
            analysisJobsSummary.style.display = 'none';
            analysisJobsSummary.innerHTML = '';
            return;
        }

        const counts = buildAnalysisJobSummary(jobs);
        const items = [
            { key: 'all', label: 'All Jobs' },
            { key: 'initial', label: 'Initial Pass' },
            { key: 'rewrite', label: 'Rewrite Pass' },
            { key: 'fallback', label: 'Fallback Pass' },
            { key: 'failed', label: 'Failed' },
        ];

        analysisJobsSummary.style.display = 'flex';
        analysisJobsSummary.innerHTML = `
            <div class="analysis-summary-kicker">Reliability Summary</div>
            <div class="analysis-summary-chips">
                ${items.map(item => `
                    <button
                        type="button"
                        class="analysis-summary-chip ${_analysisJobPathFilter === item.key ? 'analysis-summary-chip-active' : ''}"
                        data-analysis-filter="${item.key}">
                        <span>${escapeHtml(item.label)}</span>
                        <strong>${counts[item.key] || 0}</strong>
                    </button>
                `).join('')}
            </div>
        `;

        analysisJobsSummary.querySelectorAll('[data-analysis-filter]').forEach(button => {
            button.addEventListener('click', () => {
                _analysisJobPathFilter = button.dataset.analysisFilter || 'all';
                renderAnalysisJobs(jobs);
            });
        });
    }

    function renderAnalysisJobs(jobs) {
        renderAnalysisJobsSummary(jobs);

        if (!jobs.length) {
            analysisJobsList.innerHTML = `
                <div class="empty-state">
                    <i class="ph ph-tray" style="font-size: 2.5rem; opacity: 0.3; margin-bottom: 1rem;"></i>
                    <p>No analysis jobs found. Run an analysis from Chat or Past Sessions.</p>
                </div>`;
            return;
        }

        const filteredJobs = _analysisJobPathFilter === 'all'
            ? jobs
            : jobs.filter(job => String(job.completion_path || '').toLowerCase() === _analysisJobPathFilter);

        if (!filteredJobs.length) {
            analysisJobsList.innerHTML = `
                <div class="empty-state">
                    <i class="ph ph-funnel" style="font-size: 2.2rem; opacity: 0.3; margin-bottom: 1rem;"></i>
                    <p>No analysis jobs match the selected completion path filter.</p>
                </div>`;
            return;
        }

        analysisJobsList.innerHTML = filteredJobs.map(job => {
            const requestedOutputs = Array.isArray(job.analysis_outputs) ? job.analysis_outputs : [];
            const outputLabels = ['Core Efficiency Review', ...requestedOutputs.map(formatAnalysisOutputLabel)];
            const completionPathLabel = formatAnalysisCompletionPath(job.completion_path);
            const date = new Date(job.start_time).toLocaleString();
            const statusClass = `status-${job.status}`;
            const statusIcon = job.status === 'running' ? 'ph-spinner spinning' : (job.status === 'success' ? 'ph-check-circle' : 'ph-x-circle');
            const statusDetail = String(job.status_detail || '').trim();
            const lastUpdateText = job.last_update_time ? new Date(job.last_update_time).toLocaleTimeString() : '';
            const responsePreviewSource = String(job.response || job.result || job.result_preview || '').trim();
            const responsePreview = responsePreviewSource
                ? escapeHtml(responsePreviewSource.replace(/\s+/g, ' ').slice(0, 280))
                : '';
            
            return `
                <div class="job-card">
                    <div class="job-header">
                        <div class="job-info">
                            <div class="job-id">${job.job_id}</div>
                            <div class="job-title">Analysis: ${job.run_id}</div>
                        </div>
                        <div class="job-card-controls">
                            <div class="job-status-badge ${statusClass}">
                                <i class="ph ${statusIcon}"></i>
                                <span>${job.status}</span>
                            </div>
                            <div class="dropdown job-actions-dropdown">
                                <button class="btn btn-secondary job-actions-toggle" type="button" data-job-id="${job.job_id}">
                                    <span>Actions</span>
                                    <i class="ph ph-caret-down"></i>
                                </button>
                                <ul class="dropdown-menu job-actions-menu" data-job-id="${job.job_id}">
                                    <li data-action="view" data-job-id="${job.job_id}"><i class="ph ph-eye"></i> View</li>
                                    <li data-action="copy" data-job-id="${job.job_id}"><i class="ph ph-copy"></i> Copy Response</li>
                                    <li data-action="download" data-job-id="${job.job_id}"><i class="ph ph-download-simple"></i> Download</li>
                                </ul>
                            </div>
                        </div>
                    </div>
                    ${(job.status === 'running' || statusDetail) ? `
                        <div class="job-progress ${job.status === 'running' ? 'job-progress-active' : ''}">
                            <span class="job-progress-label">${escapeHtml(statusDetail || (job.status === 'running' ? 'Working' : job.status || 'Unknown'))}</span>
                            ${lastUpdateText ? `<span class="job-progress-meta">Updated ${escapeHtml(lastUpdateText)}</span>` : ''}
                        </div>
                    ` : ''}
                    ${job.status === 'success' && responsePreview ? `
                        <div class="job-preview">
                            <span class="job-preview-label">Response Preview</span>
                            <p class="job-preview-text">${responsePreview}</p>
                        </div>
                    ` : ''}
                    <div class="job-output-summary">
                        <span class="job-output-summary-label">Outputs</span>
                        <div class="job-output-chips">
                            ${outputLabels.map(label => `<span class="job-output-chip">${escapeHtml(label)}</span>`).join('')}
                        </div>
                    </div>
                    ${completionPathLabel ? `
                        <div class="job-attempt-summary">
                            <span class="job-output-summary-label">Completion Path</span>
                            <span class="job-attempt-chip job-attempt-chip-${escapeHtml(String(job.completion_path || '').toLowerCase())}">${escapeHtml(completionPathLabel)}</span>
                        </div>
                    ` : ''}
                    <div class="job-footer">
                        <div class="job-meta">
                            <span><i class="ph ph-calendar"></i> ${date}</span>
                            <span><i class="ph ph-clock"></i> ${job.span}</span>
                        </div>
                        ${job.status === 'failed' ? `
                            <div class="status-error" style="font-size: 0.8rem;">Error: ${escapeHtml(job.error)}</div>
                        ` : ''}
                    </div>
                </div>
            `;
        }).join('');

        analysisJobsList.querySelectorAll('.job-actions-toggle').forEach(btn => {
            btn.addEventListener('click', (event) => {
                event.stopPropagation();
                const jobId = btn.dataset.jobId;
                const menu = analysisJobsList.querySelector(`.job-actions-menu[data-job-id="${jobId}"]`);
                const isOpen = menu.classList.contains('show');
                closeAnalysisJobMenus();
                if (!isOpen) {
                    menu.classList.add('show');
                    _openAnalysisJobMenuId = jobId;
                }
            });
        });

        analysisJobsList.querySelectorAll('.job-actions-menu li').forEach(item => {
            item.addEventListener('click', (event) => {
                event.stopPropagation();
                const { action, jobId } = item.dataset;
                closeAnalysisJobMenus();
                if (action === 'view') {
                    window.viewAnalysisResult(jobId);
                } else if (action === 'copy') {
                    window.copyAnalysisJobResponse(jobId);
                } else if (action === 'download') {
                    window.downloadAnalysisJob(jobId);
                }
            });
        });

        if (_openAnalysisJobMenuId) {
            const openMenu = analysisJobsList.querySelector(`.job-actions-menu[data-job-id="${_openAnalysisJobMenuId}"]`);
            if (openMenu) {
                openMenu.classList.add('show');
            } else {
                _openAnalysisJobMenuId = null;
            }
        }
    }

    function closeAnalysisJobMenus() {
        analysisJobsList.querySelectorAll('.job-actions-menu.show').forEach(menu => {
            menu.classList.remove('show');
        });
        _openAnalysisJobMenuId = null;
    }

    function formatAnalysisOutputLabel(value) {
        if (value === 'tooling_assets') {
            return 'Recommended Tooling Assets';
        }
        if (value === 'progress_analysis') {
            return 'Progress Analysis';
        }
        return String(value || '')
            .split('_')
            .filter(Boolean)
            .map(part => part.charAt(0).toUpperCase() + part.slice(1))
            .join(' ');
    }

    function formatAnalysisCompletionPath(value) {
        if (value === 'initial') {
            return 'Initial Pass';
        }
        if (value === 'rewrite') {
            return 'Rewrite Pass';
        }
        if (value === 'fallback') {
            return 'Fallback Template Pass';
        }
        if (value === 'failed') {
            return 'Failed';
        }
        return '';
    }

    window.viewAnalysisResult = async function(jobId) {
        try {
            const res = await fetch(`/api/analysis/jobs/${jobId}`);
            const job = await res.json();
            
            if (job) {
                const responseSource = String(
                    job.response
                    || job.result
                    || job.raw_response?.message?.content
                    || 'No response captured yet.'
                );
                const modal = document.createElement('div');
                modal.className = 'modal-overlay';
                modal.style.display = 'flex';
                const renderedResponse = renderAnalysisResponseContent(responseSource);
                const renderedSystemPrompt = escapeHtml(job.system_prompt || 'Not captured.');
                const renderedUserPrompt = escapeHtml(job.user_prompt || 'Not captured.');
                const renderedError = job.error ? `<div class="status-error" style="margin-bottom: 1rem;">${escapeHtml(job.error)}</div>` : '';
                const requestedOutputs = Array.isArray(job.analysis_outputs) ? job.analysis_outputs : [];
                const completionPathLabel = formatAnalysisCompletionPath(job.completion_path);
                const renderedOutputs = ['Core Efficiency Review', ...requestedOutputs.map(formatAnalysisOutputLabel)]
                    .map(label => `<span class="job-output-chip">${escapeHtml(label)}</span>`)
                    .join('');
                modal.innerHTML = `
                    <div class="annotation-modal" style="max-width: 800px; width: 90%;">
                        <div class="modal-header">
                            <h3><i class="ph ph-brain"></i> Analysis Job: ${job.run_id}</h3>
                            <button type="button" class="icon-btn" onclick="this.closest('.modal-overlay').remove()"><i class="ph ph-x"></i></button>
                        </div>
                        <div class="modal-body" style="max-height: 60vh; overflow-y: auto; padding: 1.5rem; background: rgba(0,0,0,0.2); border-radius: 12px; margin: 1rem;">
                            <div style="display: grid; gap: 1rem; font-size: 0.95rem; line-height: 1.6; color: var(--text-primary);">
                                <div>
                                    <strong>Status:</strong> ${escapeHtml(job.status || 'unknown')}<br>
                                    <strong>Completion Path:</strong> ${escapeHtml(completionPathLabel || 'Pending')}<br>
                                    <strong>Span:</strong> ${escapeHtml(job.span || 'unknown')}<br>
                                    <strong>Ollama URL:</strong> ${escapeHtml(job.ollama_url || 'unknown')}<br>
                                    <strong>Model:</strong> ${escapeHtml(job.model || 'unknown')}
                                </div>
                                <div class="job-output-summary">
                                    <span class="job-output-summary-label">Requested Outputs</span>
                                    <div class="job-output-chips">${renderedOutputs}</div>
                                </div>
                                ${renderedError}
                                <div>
                                    <h4 style="margin-bottom: 0.5rem;">System Prompt</h4>
                                    <pre class="log-pre" style="white-space: pre-wrap;">${renderedSystemPrompt}</pre>
                                </div>
                                <div>
                                    <h4 style="margin-bottom: 0.5rem;">User Prompt</h4>
                                    <pre class="log-pre" style="white-space: pre-wrap;">${renderedUserPrompt}</pre>
                                </div>
                                <div>
                                    <h4 style="margin-bottom: 0.5rem;">Response</h4>
                                    <div style="font-size: 0.95rem; line-height: 1.6; color: var(--text-primary);">
                                        ${renderedResponse}
                                    </div>
                                </div>
                            </div>
                        </div>
                        <div class="modal-footer">
                            <button type="button" class="btn btn-secondary" onclick="this.closest('.modal-overlay').remove()">Close</button>
                        </div>
                    </div>
                `;
                document.body.appendChild(modal);
                // Close on overlay click
                modal.addEventListener('click', (e) => {
                    if (e.target === modal) modal.remove();
                });
            }
        } catch (err) {
            showAlert('Failed to load analysis result: ' + err.message, 'error');
        }
    };

    window.downloadAnalysisJob = function(jobId) {
        window.location.href = `/api/analysis/jobs/${jobId}/download`;
    };

    window.copyAnalysisJobResponse = async function(jobId) {
        try {
            const res = await fetch(`/api/analysis/jobs/${jobId}`);
            const job = await res.json();
            const responseSource = String(
                job.response
                || job.result
                || job.raw_response?.message?.content
                || ''
            ).trim();

            if (!responseSource) {
                showAlert('No analysis response is available to copy.', 'error');
                return;
            }

            if (navigator.clipboard?.writeText) {
                await navigator.clipboard.writeText(responseSource);
            } else {
                const tempArea = document.createElement('textarea');
                tempArea.value = responseSource;
                tempArea.setAttribute('readonly', '');
                tempArea.style.position = 'absolute';
                tempArea.style.left = '-9999px';
                document.body.appendChild(tempArea);
                tempArea.select();
                document.execCommand('copy');
                tempArea.remove();
            }

            showAlert('Analysis response copied to clipboard.', 'success');
        } catch (err) {
            showAlert('Failed to copy analysis response: ' + err.message, 'error');
        }
    };

    document.addEventListener('click', (event) => {
        if (!event.target.closest('.job-actions-dropdown')) {
            closeAnalysisJobMenus();
        }
    });

    function startAnalysisJobsPolling() {
        if (_analysisJobsInterval) return;
        _analysisJobsInterval = setInterval(loadAnalysisJobs, 3000);
    }

    function stopAnalysisJobsPolling() {
        if (_analysisJobsInterval) {
            clearInterval(_analysisJobsInterval);
            _analysisJobsInterval = null;
        }
    }

    clearJobsBtn.addEventListener('click', async () => {
        if (!confirm('Clear all analysis job history?')) return;
        try {
            await fetch('/api/analysis/jobs/clear', { method: 'POST' });
            loadAnalysisJobs();
        } catch (err) {
            showAlert('Failed to clear jobs: ' + err.message, 'error');
        }
    });

    // ---------------------------------------------------------------
    // Scaffolding Generation via Claude Code
    // ---------------------------------------------------------------
    const assetConfigModal = document.getElementById('asset-config-modal-overlay');
    const assetTerminalModal = document.getElementById('asset-terminal-modal-overlay');
    let _activeAssetConfig = null;
    let _activeAssetTerminalId = null;
    let _assetTerminalEventSource = null;

    function openAssetConfigModal(assetName, runId) {
        _activeAssetConfig = { assetName, runId };
        
        // Auto-fill from active global context
        const providerSelect = document.getElementById('provider-select');
        const ollamaUrlInput = document.getElementById('ollama-url');
        const apiKeyInput = document.getElementById('api-key');
        
        const assetProvider = document.getElementById('asset-provider-select');
        const assetUrl = document.getElementById('asset-url-input');
        const assetApiKey = document.getElementById('asset-api-key');
        
        assetProvider.value = providerSelect.value || 'ollama_direct';
        assetUrl.value = ollamaUrlInput.value || 'http://localhost:11434';
        assetApiKey.value = apiKeyInput.value || '';
        
        // Set default tag based on asset name
        document.getElementById('asset-tag').value = assetName;
        document.getElementById('asset-output-path').value = `Working Directory: ./tools/${assetName}/`;
        
        assetConfigModal.style.display = 'flex';
    }

    document.getElementById('asset-fetch-models-btn').addEventListener('click', async () => {
        const provider = document.getElementById('asset-provider-select').value;
        const url = document.getElementById('asset-url-input').value.trim();
        const apiKey = document.getElementById('asset-api-key').value.trim();
        const errorLabel = document.getElementById('asset-fetch-error');
        const btn = document.getElementById('asset-fetch-models-btn');
        const modelSelect = document.getElementById('asset-model-select');
        
        await fetchModelsIntoSelect({
            url: url,
            provider: provider,
            apiKey: apiKey,
            sslVerify: true,
            button: btn,
            errorLabel: errorLabel,
            selectElement: modelSelect,
            progressTitleText: 'Fetching Claude Code Models',
            successMessage: 'Models loaded for Claude Code generation.',
            onSuccess: (models) => {
                // Pre-select if global model matches
                const globalModel = document.getElementById('model-select').value;
                if (models.some(m => m.id === globalModel)) {
                    modelSelect.value = globalModel;
                }
            },
            onFailure: () => {}
        });
    });

    document.getElementById('cancel-asset-config-btn').addEventListener('click', () => {
        assetConfigModal.style.display = 'none';
        _activeAssetConfig = null;
    });

    document.getElementById('confirm-asset-config-btn').addEventListener('click', async () => {
        if (!_activeAssetConfig) return;
        
        const provider = document.getElementById('asset-provider-select').value;
        const model = document.getElementById('asset-model-select').value;
        const apiKey = document.getElementById('asset-api-key').value.trim();
        const baseUrl = document.getElementById('asset-url-input').value.trim();
        const tag = document.getElementById('asset-tag').value.trim();
        const autoAdd = document.getElementById('asset-auto-add').checked;
        const btn = document.getElementById('confirm-asset-config-btn');
        
        const originalText = btn.innerHTML;
        btn.innerHTML = '<i class="ph ph-spinner ph-spin"></i> Starting...';
        btn.disabled = true;
        
        try {
            const res = await fetch('/api/scaffolding/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    run_id: _activeAssetConfig.runId,
                    asset_name: _activeAssetConfig.assetName,
                    provider: provider,
                    model: model,
                    api_key: apiKey,
                    base_url: baseUrl,
                    tag: tag,
                    auto_add: autoAdd
                })
            });
            const data = await res.json();
            if (data.success) {
                assetConfigModal.style.display = 'none';
                openAssetTerminal(data.term_id, _activeAssetConfig.assetName);
            } else {
                showAlert('Failed to start Claude Code: ' + data.error, 'error');
            }
        } catch (err) {
            showAlert('Error starting generation: ' + err.message, 'error');
        } finally {
            btn.innerHTML = originalText;
            btn.disabled = false;
        }
    });

    function openAssetTerminal(termId, assetName) {
        _activeAssetTerminalId = termId;
        document.getElementById('asset-terminal-title').innerHTML = `<i class="ph ph-terminal"></i> Claude Code: ${escapeHtml(assetName)}`;
        
        const viewer = document.getElementById('asset-terminal-viewer');
        viewer.innerHTML = '<div class="log-entry log-status">Connecting to Claude Code...</div>';
        
        const input = document.getElementById('asset-terminal-input');
        input.value = '';
        input.disabled = true;
        
        assetTerminalModal.style.display = 'flex';
        
        if (_assetTerminalEventSource) {
            _assetTerminalEventSource.close();
        }
        
        _assetTerminalEventSource = new EventSource(`/api/terminal/${termId}/stream`);
        
        _assetTerminalEventSource.onmessage = (e) => {
            try {
                const data = JSON.parse(e.data);
                if (data.type === 'output') {
                    const el = document.createElement('div');
                    el.className = 'log-entry log-tool-result';
                    // We preserve whitespace with log-pre class or pre tags
                    el.innerHTML = `<pre class="log-pre" style="margin:0; padding:0; background:none; border:none; white-space: pre-wrap;">${escapeHtml(data.data)}</pre>`;
                    viewer.appendChild(el);
                    viewer.scrollTop = viewer.scrollHeight;
                    
                    if (input.disabled) {
                        input.disabled = false;
                        input.focus();
                    }
                } else if (data.type === 'close') {
                    const el = document.createElement('div');
                    el.className = 'log-entry log-status';
                    el.textContent = 'Session closed.';
                    viewer.appendChild(el);
                    viewer.scrollTop = viewer.scrollHeight;
                    input.disabled = true;
                    _assetTerminalEventSource.close();
                }
            } catch (err) {
                console.error("Error parsing terminal SSE", err);
            }
        };
        
        _assetTerminalEventSource.onerror = (err) => {
            console.error("Terminal SSE Error", err);
            _assetTerminalEventSource.close();
        };
    }

    document.getElementById('asset-terminal-input').addEventListener('keydown', async (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            const inputEl = e.target;
            const text = inputEl.value;
            inputEl.value = '';
            
            const viewer = document.getElementById('asset-terminal-viewer');
            const el = document.createElement('div');
            el.className = 'log-entry log-user-input';
            el.innerHTML = `<span class="isess-prompt-indicator">></span> ${escapeHtml(text)}`;
            viewer.appendChild(el);
            viewer.scrollTop = viewer.scrollHeight;
            
            if (_activeAssetTerminalId) {
                try {
                    await fetch(`/api/terminal/${_activeAssetTerminalId}/input`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ input: text + '\n' })
                    });
                } catch (err) {
                    console.error("Failed to send terminal input", err);
                }
            }
        }
    });

    document.getElementById('close-asset-terminal-btn').addEventListener('click', () => {
        assetTerminalModal.style.display = 'none';
        if (_assetTerminalEventSource) {
            _assetTerminalEventSource.close();
            _assetTerminalEventSource = null;
        }
        // Could also send a terminate request to the backend here, but we will rely on standard terminal closure.
    });

    if (typeof Sortable !== 'undefined' && chatTabBar) {
        new Sortable(chatTabBar, {
            animation: 150,
            ghostClass: 'chat-tab-ghost',
            filter: '.chat-tab[data-tab-id="main"]',
            onMove: function (evt) {
                return evt.related.dataset.tabId !== 'main';
            }
        });
    }

    if (chatTabBar) {
        chatTabBar.addEventListener('wheel', (evt) => {
            if (evt.deltaY !== 0) {
                evt.preventDefault();
                chatTabBar.scrollLeft += evt.deltaY;
            }
        });
    }

});
