document.addEventListener('DOMContentLoaded', () => {
    const el = id => document.getElementById(`plugin-repair-${id}`);
    const dialog = el('dialog');
    let folder = null;
    let kind = 'mcp_tool';
    let context = null;
    let timer = null;
    let pending = false;
    let historyText = '';
    let session = 0;
    const status = message => { el('status').textContent = message; };
    const endpoint = () => kind === 'mcp_tool' ? `/api/plugins/mcp-tools/${encodeURIComponent(folder)}` : `/api/artifacts/${encodeURIComponent(kind)}/${encodeURIComponent(folder)}`;
    const checkLabel = () => kind === 'mcp_tool' ? 'Test' : 'Validate';

    function controls() {
        const testing = context?.test_report?.status === 'running';
        const busy = pending || context?.busy || testing;
        el('send').disabled = !context || busy;
        el('test').disabled = !context?.can_test || busy;
        for (const id of ['input', 'url', 'model', 'key', 'ssl']) el(id).disabled = !context || busy;
        const active = context?.turns?.findLast(turn => turn.status === 'running');
        el('cancel').hidden = !active;
        el('cancel').disabled = pending;
    }

    async function jsonRequest(url, options) {
        const response = await fetch(url, options);
        const data = await response.json();
        if (!response.ok) throw new Error(data.error || 'Request failed.');
        return data;
    }

    function render() {
        el('original').textContent = context.original_messages.map(message => `${message.role}:\n${message.content}`).join('\n\n');
        el('results').textContent = JSON.stringify(context.test_report, null, 2);
        const nextHistory = JSON.stringify(context.turns);
        if (nextHistory !== historyText) {
            historyText = nextHistory;
            el('history').replaceChildren();
            for (const turn of context.turns) {
                const entry = document.createElement('div');
                entry.className = 'plugin-repair-turn';
                entry.textContent = `You:\n${turn.user_prompt}\n\nClaude (${turn.status}):\n${turn.response || turn.error || turn.status_detail || ''}`;
                el('history').appendChild(entry);
            }
            el('history').scrollTop = el('history').scrollHeight;
        }
        const latest = context.turns.at(-1);
        if (context.busy) status(`Claude is updating the artifact. ${checkLabel()} will be available when the prompt completes.`);
        else if (context.test_report.status === 'running') status('Tests are running…');
        else if (latest?.status === 'failed') status(`Prompt failed: ${latest.error || 'Please try again.'}`);
        else if (latest?.status === 'canceled') status('Prompt canceled. Send another prompt to continue.');
        else if (latest?.status === 'success') status(`Prompt complete. Checks: ${context.test_report.status}${context.test_report.outdated ? ` (outdated — click ${checkLabel()} to check the updated artifact)` : ''}.`);
        else status(`Describe the change you want. ${checkLabel()} becomes available after your first prompt completes.`);
        controls();
    }

    async function refresh(initial = false) {
        clearTimeout(timer);
        const selected = folder;
        const currentSession = session;
        try {
            const data = await jsonRequest(`${endpoint()}/conversation`);
            if (selected !== folder || currentSession !== session || !dialog.open) return;
            context = data;
            if (initial) {
                el('url').value = context.base_url;
                el('model').value = context.model || '';
                el('ssl').checked = context.ssl_verify;
            }
            render();
            if (context.busy || context.test_report.status === 'running') {
                timer = setTimeout(() => refresh(), 2000);
            }
        } catch (error) {
            if (selected !== folder || currentSession !== session || !dialog.open) return;
            context = null;
            controls();
            status(`${error.message} Use Refresh to reconnect.`);
        }
    }

    window.openPluginRepair = async (name, artifactKind = 'mcp_tool') => {
        clearTimeout(timer);
        session += 1;
        folder = name;
        kind = artifactKind;
        el('test').textContent = checkLabel();
        el('description').textContent = kind === 'mcp_tool'
            ? 'Continue from the generation prompt and latest test results. Test plans and fixtures stay unchanged.'
            : 'Continue from the generation prompt and latest validation results. Validate the updated files after your prompt completes.';
        context = null;
        pending = false;
        historyText = '';
        el('title').textContent = `Continue with Claude: ${name}`;
        el('input').value = '';
        el('key').value = '';
        el('history').replaceChildren();
        el('original').textContent = '';
        el('results').textContent = '';
        controls();
        status('Loading generation context…');
        if (!dialog.open) dialog.showModal();
        await refresh(true);
    };

    async function action(task) {
        if (pending) return;
        const selected = folder;
        const currentSession = session;
        pending = true;
        controls();
        let error = null;
        try {
            await task();
        } catch (failure) {
            error = failure;
        } finally {
            if (selected === folder && currentSession === session && dialog.open) {
                pending = false;
                await refresh();
                if (error) status(error.message);
                controls();
            }
            document.dispatchEvent(new Event('plugin-artifact-updated'));
        }
    }

    el('form').addEventListener('submit', event => {
        event.preventDefault();
        if (!context || el('send').disabled || !el('input').value.trim()) return;
        const payload = {
            prompt: el('input').value, base_url: el('url').value, model: el('model').value,
            api_key: el('key').value, ssl_verify: el('ssl').checked,
            revision: context.revision, artifact_sha256: context.artifact_sha256,
        };
        const currentSession = session;
        action(async () => {
            status('Sending prompt…');
            await jsonRequest(`${endpoint()}/conversation`, {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
            });
            if (currentSession === session) el('input').value = '';
        });
    });
    el('test').addEventListener('click', () => {
        if (el('test').disabled) return;
        action(() => jsonRequest(`${endpoint()}/${kind === 'mcp_tool' ? 'tests' : 'validate'}`, { method: 'POST' }));
    });
    el('cancel').addEventListener('click', () => {
        const active = context?.turns?.findLast(turn => turn.status === 'running');
        if (active) action(() => jsonRequest(`/api/plugins/jobs/${encodeURIComponent(active.job_id)}/cancel`, { method: 'POST' }));
    });
    el('refresh').addEventListener('click', () => refresh(!context));
    dialog.addEventListener('close', () => {
        session += 1;
        clearTimeout(timer);
        el('key').value = '';
        document.dispatchEvent(new Event('plugin-artifact-updated'));
    });
});
