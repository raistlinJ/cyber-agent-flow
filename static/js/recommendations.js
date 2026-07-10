(function () {
    'use strict';

    const STORAGE_PREFIX = 'recommendations-notes:';
    let activeSuccessfulJobs = [];

    const $ = (id) => document.getElementById(id);

    function escapeHtml(value) {
        return String(value || '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function getNotesKey(jobId) {
        return `${STORAGE_PREFIX}${jobId}`;
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

    function renderRecommendationCard(job, index) {
        const runLabel = job.run_id || job.session_id || job.job_id || `Session_${index + 1}`;
        const statusLabel = String(job.status || 'unknown').toUpperCase();
        // const notesValue = localStorage.getItem(getNotesKey(job.job_id)) || '';----------------------------REMOVE LATER
        const notesValue = job.analyst_notes || '';

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

                    <section class="recommendation-section">
                        <details class="config-collapse">
                            <summary>
                                <span>MARKDOWN PLAYBOOK GENERATION</span>
                                <i class="ph ph-caret-down collapse-caret"></i>
                            </summary>
                            <div class="recommendation-details-body">
                                <div class="recommendation-details-top">
                                    <div class="recommendation-details-main">
                                        <div class="recommendation-detail-row">
                                            <strong>Purpose:</strong> hardening + exploit documentation
                                        </div>
                                        <div class="recommendation-detail-row">
                                            <strong>Reasoning:</strong> derived from the successful analysis job
                                        </div>
                                    </div>
                                    <div class="recommendation-action-row">
                                        <button type="button" class="btn btn-primary recommendation-approve-btn" data-job-id="${escapeHtml(job.job_id)}" data-kind="markdown">Review</button>
                                        <button type="button" class="btn btn-secondary recommendation-deny-btn" data-job-id="${escapeHtml(job.job_id)}" data-kind="markdown">Reject</button>
                                    </div>
                                </div>
                                <div class="recommendation-hint">
                                    Triggers the same analysis-job workflow you already use.
                                </div>
                            </div>
                        </details>
                    </section>

                    <section class="recommendation-section">
                        <details class="config-collapse">
                            <summary>
                                <span>MCP TOOL GENERATION</span>
                                <i class="ph ph-caret-down collapse-caret"></i>
                            </summary>
                            <div class="recommendation-details-body">
                                <div class="recommendation-details-top">
                                    <div class="recommendation-details-main">
                                        <div class="recommendation-detail-row">
                                            <strong>Purpose:</strong> automate recon / exploit chain
                                        </div>
                                        <div class="recommendation-detail-row">
                                            <strong>Reasoning:</strong> repeated pattern detected
                                        </div>
                                    </div>
                                    <div class="recommendation-action-row">
                                        <button type="button" class="btn btn-primary recommendation-approve-btn" data-job-id="${escapeHtml(job.job_id)}" data-kind="mcp">Review</button>
                                        <button type="button" class="btn btn-secondary recommendation-deny-btn" data-job-id="${escapeHtml(job.job_id)}" data-kind="mcp">Reject</button>
                                    </div>
                                </div>
                                <div class="recommendation-hint">
                                    Uses the same executor path as analysis jobs.
                                </div>
                            </div>
                        </details>
                    </section>
                </div>
            </details>
        `;
    }
//--------------------------------------------------------------------------------------REMOVE LATER    
    // function bindNotesControls() {
    //     document.querySelectorAll('.recommendation-notes-edit-btn').forEach(button => {
    //         button.addEventListener('click', () => {
    //             const jobId = button.dataset.jobId;
    //             const textarea = document.querySelector(`.recommendation-notes[data-recommendation-notes-for="${jobId}"]`);
    //             const saveBtn = document.querySelector(`.recommendation-notes-save-btn[data-job-id="${jobId}"]`);
    //             if (!textarea) return;
    //             textarea.disabled = false;
    //             textarea.focus();
    //             button.style.display = 'none';
    //             if (saveBtn) saveBtn.style.display = '';
    //         });
    //     });

    //     document.querySelectorAll('.recommendation-notes-save-btn').forEach(button => {
    //         button.addEventListener('click', () => {
    //             const jobId = button.dataset.jobId;
    //             const textarea = document.querySelector(`.recommendation-notes[data-recommendation-notes-for="${jobId}"]`);
    //             const editBtn = document.querySelector(`.recommendation-notes-edit-btn[data-job-id="${jobId}"]`);
    //             if (!textarea) return;
    //             localStorage.setItem(getNotesKey(jobId), textarea.value);
    //             textarea.disabled = true;
    //             button.style.display = 'none';
    //             if (editBtn) editBtn.style.display = '';
    //         });
    //     });

    //     document.querySelectorAll('.recommendation-notes-delete-btn').forEach(button => {
    //         button.addEventListener('click', () => {
    //             const jobId = button.dataset.jobId;
    //             const textarea = document.querySelector(`.recommendation-notes[data-recommendation-notes-for="${jobId}"]`);
    //             const editBtn = document.querySelector(`.recommendation-notes-edit-btn[data-job-id="${jobId}"]`);
    //             const saveBtn = document.querySelector(`.recommendation-notes-save-btn[data-job-id="${jobId}"]`);
    //             localStorage.removeItem(getNotesKey(jobId));
    //             if (textarea) {
    //                 textarea.value = '';
    //                 textarea.disabled = true;
    //             }
    //             if (saveBtn) saveBtn.style.display = 'none';
    //             if (editBtn) editBtn.style.display = '';
    //         });
    //     });
    // }
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
                const jobId = button.dataset.jobId;
                const job = activeSuccessfulJobs.find(j => j.job_id === jobId);
                const runId = job && job.run_id;

                if (!runId) {
                    console.error('Review clicked with no run_id for job', jobId);
                    return;
                }

                if (typeof window.openAssetConfigModal === 'function') {
                    window.openAssetConfigModal('hello_world_test', runId);
                } else {
                    console.error('openAssetConfigModal is not available — check main.js load order.');
                }
            });
        });

        document.querySelectorAll('.recommendation-deny-btn').forEach(button => {
            button.addEventListener('click', () => {
                const jobId = button.dataset.jobId;
                const kind = button.dataset.kind;
                window.dispatchEvent(new CustomEvent('recommendations:deny', {
                    detail: { jobId, kind }
                }));
            });
        });
    }

    function renderRecommendations(jobs) {
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
        list.innerHTML = activeSuccessfulJobs
            .map((job, index) => renderRecommendationCard(job, index))
            .join('');

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
        renderRecommendations(data.jobs || []);
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