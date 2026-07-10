(function () {
    'use strict';

    const STORAGE_PREFIX = 'recommendations-notes:';
    let activeSessions = [];
    const scaffoldingCache = {}; // runId -> assets array (null while loading, [] if none found)

    const $ = (id) => document.getElementById(id);

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function getNotesKey(runId) {
        return `${STORAGE_PREFIX}${runId}`;
    }

    function getResponseSource(job) {
        return String(
            job.response
            || job.result
            || job.raw_response?.message?.content
            || ''
        ).trim();
    }

    function renderAnalysisSummary(job) {
        const responseSource = getResponseSource(job);
        if (!responseSource) {
            return '<div class="empty-state">No analysis response captured yet.</div>';
        }

        if (window.marked) {
            return `<div class="markdown-body analysis-markdown">${window.marked.parse(responseSource)}</div>`;
        }

        return `<pre class="log-pre">${escapeHtml(responseSource)}</pre>`;
    }

    // ---------------------------------------------------------------
    // Session grouping — one card per run_id, using its most recent job
    // ---------------------------------------------------------------
    function groupJobsBySession(jobs) {
        const byRunId = new Map();
        for (const job of jobs) {
            const runId = job.run_id;
            if (!runId) continue;
            const existing = byRunId.get(runId);
            if (!existing || String(job.start_time || '') > String(existing.start_time || '')) {
                byRunId.set(runId, job);
            }
        }
        return Array.from(byRunId.values())
            .sort((a, b) => String(b.start_time || '').localeCompare(String(a.start_time || '')));
    }

    // ---------------------------------------------------------------
    // Scaffolding asset parsing — pull Type/Problem/Gain out of the
    // CLAUDE_PROMPT.md text written by _create_scaffolding_from_analysis
    // ---------------------------------------------------------------
    function parseScaffoldMeta(promptContent) {
        const text = String(promptContent || '');
        const typeMatch = text.match(/\*\*Type\*\*:\s*(.+)/);
        const problemMatch = text.match(/\*\*Problem addressed\*\*:\s*(.+)/);
        const gainMatch = text.match(/\*\*Expected Gain\*\*:\s*(.+)/);
        const detailsMatch = text.match(/## AI Scaffolding Details\s*\n\n([\s\S]*)/);

        return {
            type: typeMatch ? typeMatch[1].trim() : 'Unknown',
            problem: problemMatch ? problemMatch[1].trim() : 'Not specified.',
            gain: gainMatch ? gainMatch[1].trim() : 'Not specified.',
            details: detailsMatch ? detailsMatch[1].trim() : text,
        };
    }

    function renderAssetSection(asset, runId) {
        const meta = parseScaffoldMeta(asset.prompt_content);
        const safeAssetName = escapeHtml(asset.name);

        return `
            <section class="recommendation-section">
                <details class="config-collapse">
                    <summary>
                        <span>${safeAssetName} <span class="recommendation-section-tag">${escapeHtml(meta.type)}</span></span>
                        <i class="ph ph-caret-down collapse-caret"></i>
                    </summary>
                    <div class="recommendation-details-body">
                        <div class="recommendation-detail-row">
                            <strong>Problem:</strong> ${escapeHtml(meta.problem)}
                        </div>
                        <div class="recommendation-detail-row">
                            <strong>Expected Gain:</strong> ${escapeHtml(meta.gain)}
                        </div>
                        <div class="recommendation-action-row">
                            <button type="button" class="btn btn-primary recommendation-approve-btn"
                                data-run-id="${escapeHtml(runId)}" data-asset-name="${safeAssetName}">Approve</button>
                            <button type="button" class="btn btn-secondary recommendation-deny-btn"
                                data-run-id="${escapeHtml(runId)}" data-asset-name="${safeAssetName}">Deny</button>
                        </div>
                        <div class="recommendation-hint">
                            Approve opens the Claude Code configuration modal for this asset.
                        </div>
                    </div>
                </details>
            </section>
        `;
    }

    function renderAssetsContainer(runId) {
        return `<div class="recommendation-assets" id="assets-${escapeHtml(runId)}" data-run-id="${escapeHtml(runId)}">
            <div class="empty-state" style="padding: 0.75rem;">Loading recommended assets...</div>
        </div>`;
    }

    async function loadAssetsForSession(runId) {
        if (scaffoldingCache[runId]) return scaffoldingCache[runId];

        const container = document.getElementById(`assets-${runId}`);
        try {
            const res = await fetch(`/api/sessions/${encodeURIComponent(runId)}/scaffolding`);
            if (!res.ok) throw new Error(`Failed to load assets (${res.status})`);
            const data = await res.json();
            const assets = Array.isArray(data.assets) ? data.assets : [];
            scaffoldingCache[runId] = assets;

            if (container) {
                container.innerHTML = assets.length
                    ? assets.map(asset => renderAssetSection(asset, runId)).join('')
                    : '<div class="empty-state" style="padding: 0.75rem;">No recommended assets found for this session.</div>';
                bindAssetActionButtons(container);
            }
            return assets;
        } catch (err) {
            console.error('Failed to load scaffolding assets for', runId, err);
            if (container) {
                container.innerHTML = `<div class="empty-state" style="padding: 0.75rem;">Failed to load recommended assets: ${escapeHtml(err.message)}</div>`;
            }
            return [];
        }
    }

    // ---------------------------------------------------------------
    // Session card rendering
    // ---------------------------------------------------------------
    function renderSessionCard(job, index) {
        const runId = job.run_id;
        const statusLabel = String(job.status || 'unknown').toUpperCase();
        const notesValue = localStorage.getItem(getNotesKey(runId)) || '';

        return `
            <details class="recommendation-session-card" data-run-id="${escapeHtml(runId)}">
                <summary class="recommendation-session-summary">
                    <div class="session-card-left">
                        <div class="session-run-id">${escapeHtml(runId)}</div>
                        <div class="session-meta">
                            <span class="job-status-badge status-success">${escapeHtml(statusLabel)}</span>
                            <span style="margin-left:0.5rem;">completed analysis job</span>
                        </div>
                    </div>
                    <div class="recommendation-session-chevron">
                        <i class="ph ph-caret-down"></i>
                    </div>
                </summary>

                <div class="recommendation-session-body">
                    <section class="recommendation-section">
                        <details class="config-collapse">
                            <summary>
                                <span>ANALYSIS SUMMARY</span>
                                <i class="ph ph-caret-down collapse-caret"></i>
                            </summary>
                            <div class="recommendation-details-body">
                                ${renderAnalysisSummary(job)}
                            </div>
                        </details>
                    </section>

                    <section class="recommendation-section">
                        <div class="recommendation-section-header">
                            <h3>ANALYST NOTES</h3>
                            <span class="recommendation-section-tag">editable</span>
                        </div>
                        <textarea class="recommendation-notes" rows="4"
                            data-recommendation-notes-for="${escapeHtml(runId)}"
                            placeholder="Write analyst notes here...">${escapeHtml(notesValue)}</textarea>
                    </section>

                    <div class="recommendation-section-header" style="margin-top: 0.5rem;">
                        <h3>RECOMMENDED ASSETS</h3>
                    </div>
                    ${renderAssetsContainer(runId)}
                </div>
            </details>
        `;
    }

    function bindNotesAutosave() {
        document.querySelectorAll('.recommendation-notes').forEach(textarea => {
            textarea.addEventListener('input', (event) => {
                const runId = event.target.getAttribute('data-recommendation-notes-for');
                if (!runId) return;
                localStorage.setItem(getNotesKey(runId), event.target.value);
            });
        });
    }

    function bindAssetActionButtons(scope) {
        scope.querySelectorAll('.recommendation-approve-btn').forEach(button => {
            button.addEventListener('click', () => {
                const runId = button.dataset.runId;
                const assetName = button.dataset.assetName;

                if (!runId || !assetName) {
                    console.error('Approve clicked with missing runId/assetName', runId, assetName);
                    return;
                }

                if (typeof window.openAssetConfigModal === 'function') {
                    window.openAssetConfigModal(assetName, runId);
                } else {
                    console.error('openAssetConfigModal is not available — check main.js load order.');
                }
            });
        });

        scope.querySelectorAll('.recommendation-deny-btn').forEach(button => {
            button.addEventListener('click', () => {
                const runId = button.dataset.runId;
                const assetName = button.dataset.assetName;
                window.dispatchEvent(new CustomEvent('recommendations:deny', {
                    detail: { runId, assetName }
                }));
            });
        });
    }

    function bindSessionCardToggles() {
        document.querySelectorAll('.recommendation-session-card').forEach(details => {
            details.addEventListener('toggle', () => {
                if (details.open) {
                    loadAssetsForSession(details.dataset.runId);
                }
            }, { once: false });
        });
    }

    function renderRecommendations(jobs) {
        const emptyState = $('recommendations-empty-state');
        const list = $('recommendations-list');
        if (!emptyState || !list) return;

        const successfulJobs = (Array.isArray(jobs) ? jobs : [])
            .filter(job => String(job.status || '').toLowerCase() === 'success');

        activeSessions = groupJobsBySession(successfulJobs);

        if (!activeSessions.length) {
            emptyState.textContent = 'No successful analysis jobs found. Complete an Analysis Job of your Past Sessions to populate this view.';
            emptyState.style.display = '';
            list.style.display = 'none';
            list.innerHTML = '';
            return;
        }

        emptyState.style.display = 'none';
        list.style.display = 'flex';
        list.innerHTML = activeSessions
            .map((job, index) => renderSessionCard(job, index))
            .join('');

        bindNotesAutosave();
        bindSessionCardToggles();
    }

    async function refreshRecommendationsView() {
        const emptyState = $('recommendations-empty-state');
        const list = $('recommendations-list');

        if (emptyState && list) {
            emptyState.textContent = 'Loading successful analysis jobs...';
            emptyState.style.display = '';
            list.style.display = 'none';
            list.innerHTML = '';
        }

        const response = await fetch('/api/analysis/jobs');
        if (!response.ok) {
            throw new Error(`Failed to load analysis jobs (${response.status})`);
        }

        const data = await response.json();
        renderRecommendations(data.jobs || []);
    }

    function init() {
        const refreshBtn = $('recommendations-refresh-btn');
        const navBtn = $('nav-recommendations-btn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                refreshRecommendationsView().catch(err => {
                    console.error(err);
                    if (typeof window.showAlert === 'function') {
                        window.showAlert('Failed to load recommendations: ' + err.message, 'error');
                    }
                    const emptyState = $('recommendations-empty-state');
                    if (emptyState) {
                        emptyState.textContent = 'Failed to load recommendations.';
                        emptyState.style.display = '';
                    }
                });
            });
        }

        if (navBtn) {
            navBtn.addEventListener('click', () => {
                refreshRecommendationsView().catch(console.error);
            });
        }

        window.refreshRecommendationsView = refreshRecommendationsView;
        refreshRecommendationsView().catch(err => {
            console.error('Recommendations init failed:', err);
        });
    }

    init();
})();