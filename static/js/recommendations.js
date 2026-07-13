(function () {
    'use strict';

    let activeSuccessfulJobs = [];
    const scaffoldingCache = {}; // runId -> assets array

    const $ = (id) => document.getElementById(id);

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
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
    // Scaffolding asset fetch + parsing
    // ---------------------------------------------------------------
    async function fetchScaffoldingForRunId(runId) {
        if (scaffoldingCache[runId]) return scaffoldingCache[runId];
        try {
            const res = await fetch(`/api/sessions/${encodeURIComponent(runId)}/scaffolding`);
            if (!res.ok) throw new Error(`Failed to load assets (${res.status})`);
            const data = await res.json();
            const assets = Array.isArray(data.assets) ? data.assets : [];
            scaffoldingCache[runId] = assets;
            return assets;
        } catch (err) {
            console.error('Failed to load scaffolding for', runId, err);
            scaffoldingCache[runId] = [];
            return [];
        }
    }

    function parseAssetMeta(promptContent) {
        const text = String(promptContent || '');
        const typeMatch = text.match(/\*\*Type\*\*:\s*(.+)/);
        const problemMatch = text.match(/\*\*Problem addressed\*\*:\s*(.+)/);
        const gainMatch = text.match(/\*\*Expected Gain\*\*:\s*(.+)/);

        return {
            type: typeMatch ? typeMatch[1].trim() : 'Unknown',
            problem: problemMatch ? problemMatch[1].trim() : 'Not specified.',
            gain: gainMatch ? gainMatch[1].trim() : 'Not specified.',
        };
    }

    function splitAssetsByKind(assets) {
        const markdown = [];
        const mcp = [];
        for (const asset of assets) {
            const meta = parseAssetMeta(asset.prompt_content);
            const bucket = /markdown|playbook/i.test(meta.type) ? markdown : mcp;
            bucket.push({ ...asset, meta });
        }
        return { markdown, mcp };
    }

    // ---------------------------------------------------------------
    // Rendering
    // ---------------------------------------------------------------
    function renderAssetRow(asset, runId, kind) {
        return `
            <div class="recommendation-details-top" style="border-top: 1px solid var(--panel-border); padding-top: 0.6rem; margin-top: 0.6rem;">
                <div class="recommendation-details-main">
                    <div class="recommendation-detail-row">
                        <strong>${escapeHtml(asset.name)}</strong>
                    </div>
                    <div class="recommendation-detail-row">
                        <strong>Problem:</strong> ${escapeHtml(asset.meta.problem)}
                    </div>
                    <div class="recommendation-detail-row">
                        <strong>Expected Gain:</strong> ${escapeHtml(asset.meta.gain)}
                    </div>
                </div>
                <div class="recommendation-action-row">
                    <button type="button" class="btn btn-primary recommendation-approve-btn"
                        data-run-id="${escapeHtml(runId)}" data-asset-name="${escapeHtml(asset.name)}" data-kind="${kind}">Review</button>
                    <button type="button" class="btn btn-secondary recommendation-deny-btn"
                        data-run-id="${escapeHtml(runId)}" data-asset-name="${escapeHtml(asset.name)}" data-kind="${kind}">Reject</button>
                </div>
            </div>
        `;
    }

    function renderAssetSection(title, assets, runId, kind, emptyLabel) {
        const rows = assets.length
            ? assets.map(asset => renderAssetRow(asset, runId, kind)).join('')
            : `<div class="recommendation-hint">${emptyLabel}</div>`;

        return `
            <section class="recommendation-section">
                <details class="config-collapse">
                    <summary>
                        <span>${title}</span>
                        <i class="ph ph-caret-down collapse-caret"></i>
                    </summary>
                    <div class="recommendation-details-body">
                        ${rows}
                    </div>
                </details>
            </section>
        `;
    }

    function renderRecommendationCard(job, assetsByKind) {
        const runLabel = job.run_id || job.session_id || job.job_id;
        const statusLabel = String(job.status || 'unknown').toUpperCase();
        const notesValue = job.analyst_notes || '';
        const { markdown, mcp } = assetsByKind;

        return `
            <details class="recommendation-session-card" data-job-id="${escapeHtml(job.job_id)}">
                <summary class="recommendation-session-summary">
                    <div class="session-card-left">
                        <div class="session-run-id">(${escapeHtml(runLabel)})</div>
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
                    <div class="recommendation-top-row">
                        <div class="recommendation-summary-col">
                            <div class="recommendation-section-header">
                                <h3>Analysis Summary</h3>
                                <span class="recommendation-section-tag">readonly</span>
                            </div>
                            ${renderAnalysisSummary(job)}
                        </div>

                        <div class="recommendation-notes-col">
                            <div class="recommendation-section-header">
                                <h3>Analyst Notes</h3>
                                <div class="recommendation-notes-actions">
                                    <button type="button" class="btn btn-secondary btn-compact recommendation-notes-edit-btn" data-run-id="${escapeHtml(job.run_id)}">
                                        <i class="ph ph-pencil-simple"></i> Edit
                                    </button>
                                    <button type="button" class="btn btn-secondary btn-compact recommendation-notes-save-btn" data-run-id="${escapeHtml(job.run_id)}" style="display:none;">
                                        <i class="ph ph-floppy-disk"></i> Save
                                    </button>
                                    <button type="button" class="btn btn-secondary btn-compact recommendation-notes-delete-btn" data-run-id="${escapeHtml(job.run_id)}">
                                        <i class="ph ph-trash"></i>
                                    </button>
                                </div>
                            </div>
                            <textarea class="recommendation-notes" rows="6" disabled
                                data-recommendation-notes-for="${escapeHtml(job.run_id)}"
                                placeholder="Write analyst notes here...">${escapeHtml(notesValue)}</textarea>
                        </div>
                    </div>

                    ${renderAssetSection('MARKDOWN PLAYBOOK GENERATION', markdown, job.run_id, 'markdown', 'No markdown playbooks recommended for this session.')}
                    ${renderAssetSection('MCP TOOL GENERATION', mcp, job.run_id, 'mcp', 'No MCP tools recommended for this session.')}
                </div>
            </details>
        `;
    }

    function bindNotesControls() {
        document.querySelectorAll('.recommendation-notes-edit-btn').forEach(button => {
            button.addEventListener('click', () => {
                const runId = button.dataset.runId;
                const textarea = document.querySelector(`.recommendation-notes[data-recommendation-notes-for="${runId}"]`);
                const saveBtn = document.querySelector(`.recommendation-notes-save-btn[data-run-id="${runId}"]`);
                if (!textarea) return;
                textarea.disabled = false;
                textarea.focus();
                button.style.display = 'none';
                if (saveBtn) saveBtn.style.display = '';
            });
        });

        document.querySelectorAll('.recommendation-notes-save-btn').forEach(button => {
            button.addEventListener('click', async () => {
                const runId = button.dataset.runId;
                const textarea = document.querySelector(`.recommendation-notes[data-recommendation-notes-for="${runId}"]`);
                const editBtn = document.querySelector(`.recommendation-notes-edit-btn[data-run-id="${runId}"]`);
                if (!textarea) return;

                try {
                    const res = await fetch(`/api/sessions/${encodeURIComponent(runId)}/notes`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ notes: textarea.value })
                    });
                    if (!res.ok) throw new Error(`Failed to save notes (${res.status})`);
                    textarea.disabled = true;
                    button.style.display = 'none';
                    if (editBtn) editBtn.style.display = '';
                } catch (err) {
                    console.error(err);
                    if (typeof window.showAlert === 'function') {
                        window.showAlert('Failed to save analyst notes: ' + err.message, 'error');
                    }
                }
            });
        });

        document.querySelectorAll('.recommendation-notes-delete-btn').forEach(button => {
            button.addEventListener('click', async () => {
                const runId = button.dataset.runId;
                const textarea = document.querySelector(`.recommendation-notes[data-recommendation-notes-for="${runId}"]`);
                const editBtn = document.querySelector(`.recommendation-notes-edit-btn[data-run-id="${runId}"]`);
                const saveBtn = document.querySelector(`.recommendation-notes-save-btn[data-run-id="${runId}"]`);

                try {
                    const res = await fetch(`/api/sessions/${encodeURIComponent(runId)}/notes`, { method: 'DELETE' });
                    if (!res.ok) throw new Error(`Failed to delete notes (${res.status})`);
                    if (textarea) {
                        textarea.value = '';
                        textarea.disabled = true;
                    }
                    if (saveBtn) saveBtn.style.display = 'none';
                    if (editBtn) editBtn.style.display = '';
                } catch (err) {
                    console.error(err);
                    if (typeof window.showAlert === 'function') {
                        window.showAlert('Failed to delete analyst notes: ' + err.message, 'error');
                    }
                }
            });
        });
    }

    function bindActionButtons() {
        document.querySelectorAll('.recommendation-approve-btn').forEach(button => {
            button.addEventListener('click', () => {
                const runId = button.dataset.runId;
                const assetName = button.dataset.assetName;

                if (!runId || !assetName) {
                    console.error('Review clicked with missing runId/assetName', runId, assetName);
                    return;
                }

                if (typeof window.openAssetConfigModal === 'function') {
                    window.openAssetConfigModal(assetName, runId);
                } else {
                    console.error('openAssetConfigModal is not available — check main.js load order.');
                }
            });
        });

        document.querySelectorAll('.recommendation-deny-btn').forEach(button => {
            button.addEventListener('click', () => {
                const runId = button.dataset.runId;
                const assetName = button.dataset.assetName;
                const kind = button.dataset.kind;
                window.dispatchEvent(new CustomEvent('recommendations:deny', {
                    detail: { runId, assetName, kind }
                }));
            });
        });
    }

    async function renderRecommendations(jobs) {
        const emptyState = $('recommendations-empty-state');
        const list = $('recommendations-list');
        if (!emptyState || !list) return;

        activeSuccessfulJobs = (Array.isArray(jobs) ? jobs : [])
            .filter(job => String(job.status || '').toLowerCase() === 'success');

        if (!activeSuccessfulJobs.length) {
            emptyState.textContent = 'No successful analysis jobs found. Complete an Analysis Job of your Past Sessions to populate this view.';
            emptyState.style.display = '';
            list.style.display = 'none';
            list.innerHTML = '';
            return;
        }

        emptyState.style.display = 'none';
        list.style.display = 'flex';
        list.innerHTML = `<div class="empty-state">Loading recommended assets...</div>`;

        const uniqueRunIds = [...new Set(activeSuccessfulJobs.map(job => job.run_id).filter(Boolean))];
        await Promise.all(uniqueRunIds.map(runId => fetchScaffoldingForRunId(runId)));

        list.innerHTML = activeSuccessfulJobs.map(job => {
            const assets = scaffoldingCache[job.run_id] || [];
            const assetsByKind = splitAssetsByKind(assets);
            return renderRecommendationCard(job, assetsByKind);
        }).join('');

        bindNotesControls();
        bindActionButtons();
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
        await renderRecommendations(data.jobs || []);
    }

    function init() {
        const refreshBtn = $('recommendations-refresh-btn');
        const navBtn = $('nav-recommendations-btn');
        if (refreshBtn) {
            refreshBtn.addEventListener('click', () => {
                refreshRecommendationsView().catch(err => {
                    console.error(err);
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