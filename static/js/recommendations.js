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
        const notesValue = localStorage.getItem(getNotesKey(job.job_id)) || '';

        return `
            <details class="recommendation-session-card" ${index === 0 ? 'open' : ''} data-job-id="${escapeHtml(job.job_id)}">
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
                    <section class="recommendation-section">
                        <div class="recommendation-section-header">
                            <h3>ANALYSIS SUMMARY</h3>
                            <span class="recommendation-section-tag">readonly</span>
                        </div>
                        ${renderAnalysisSummary(job)}
                    </section>

                    <section class="recommendation-section">
                        <div class="recommendation-section-header">
                            <h3>ANALYST NOTES</h3>
                            <span class="recommendation-section-tag">editable</span>
                        </div>
                        <textarea class="recommendation-notes" rows="4"
                            data-recommendation-notes-for="${escapeHtml(job.job_id)}"
                            placeholder="Write analyst notes here...">${escapeHtml(notesValue)}</textarea>
                    </section>

                    <section class="recommendation-section">
                        <details class="config-collapse" open>
                            <summary>
                                <span>MARKDOWN PLAYBOOK GENERATION</span>
                                <i class="ph ph-caret-down collapse-caret"></i>
                            </summary>
                            <div class="recommendation-details-body">
                                <div class="recommendation-detail-row">
                                    <strong>Purpose:</strong> hardening + exploit documentation
                                </div>
                                <div class="recommendation-detail-row">
                                    <strong>Reasoning:</strong> derived from the successful analysis job
                                </div>
                                <div class="recommendation-action-row">
                                    <button type="button" class="btn btn-primary recommendation-approve-btn" data-job-id="${escapeHtml(job.job_id)}" data-kind="markdown">Approve</button>
                                    <button type="button" class="btn btn-secondary recommendation-deny-btn" data-job-id="${escapeHtml(job.job_id)}" data-kind="markdown">Deny</button>
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
                                <div class="recommendation-detail-row">
                                    <strong>Purpose:</strong> automate recon / exploit chain
                                </div>
                                <div class="recommendation-detail-row">
                                    <strong>Reasoning:</strong> repeated pattern detected
                                </div>
                                <div class="recommendation-action-row">
                                    <button type="button" class="btn btn-primary recommendation-approve-btn" data-job-id="${escapeHtml(job.job_id)}" data-kind="mcp">Approve</button>
                                    <button type="button" class="btn btn-secondary recommendation-deny-btn" data-job-id="${escapeHtml(job.job_id)}" data-kind="mcp">Deny</button>
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

    function bindNotesAutosave() {
        document.querySelectorAll('.recommendation-notes').forEach(textarea => {
            textarea.addEventListener('input', (event) => {
                const jobId = event.target.getAttribute('data-recommendation-notes-for');
                if (!jobId) return;
                localStorage.setItem(getNotesKey(jobId), event.target.value);
            });
        });
    }

    function bindActionButtons() {
        document.querySelectorAll('.recommendation-approve-btn').forEach(button => {
            button.addEventListener('click', () => {
                const jobId = button.dataset.jobId;
                const kind = button.dataset.kind;
                window.dispatchEvent(new CustomEvent('recommendations:approve', {
                    detail: { jobId, kind }
                }));
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
            emptyState.textContent = 'No successful analysis jobs found. Complete and wait for an analysis job from Past Sessions to populate this view.';
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

        bindNotesAutosave();
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