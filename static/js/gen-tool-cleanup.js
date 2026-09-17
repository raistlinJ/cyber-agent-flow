document.addEventListener('DOMContentLoaded', () => {
    const el = name => document.getElementById(`gen-tool-cleanup-${name}`);
    let pending = false;
    function updateHint() {
        el('image-hint').hidden = el('scope').value === 'containers';
    }
    el('scope').addEventListener('change', () => {
        updateHint();
        el('status').textContent = '';
        el('results').hidden = true;
    });
    async function cleanup(dryRun) {
        if (pending) return;
        pending = true;
        for (const name of ['preview', 'run', 'scope']) el(name).disabled = true;
        el('results').hidden = true;
        el('status').textContent = dryRun ? 'Checking generated tool test resources…' : 'Cleaning generated tool test resources…';
        const options = { remove_containers: el('scope').value !== 'images', remove_images: el('scope').value !== 'containers', dry_run: dryRun };
        try {
            const response = await fetch('/api/plugins/test-runtime/cleanup', {
                method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(options),
            });
            const report = await response.json();
            if (!response.ok) throw new Error(report.error || 'Unable to clean generated tool test resources.');
            const containers = report.containers || [];
            const images = report.images || [];
            const skipped = report.skipped || [];
            const errors = report.errors || [];
            el('status').textContent = `${dryRun ? 'Would remove' : 'Removed'} ${containers.length} container(s) and ${images.length} image(s).` +
                (skipped.length ? ` ${skipped.length} resource(s) kept.` : '') + (errors.length ? ` ${errors.length} removal(s) failed; see details.` : '');
            const lines = [
                ...containers.map(item => `Container: ${item.name} (${item.state})`),
                ...images.map(item => `Image: ${item.tags?.join(', ') || item.id}`),
                ...skipped.map(item => `Kept ${item.resource}: ${item.reason}`),
                ...errors.map(item => `Failed ${item.resource}: ${item.error}`),
            ];
            if (!dryRun && images.length) lines.push('Rebuild before testing: python gen-tool_tests.py build');
            el('results').textContent = lines.join('\n');
            el('results').hidden = !lines.length;
            if (!dryRun) document.dispatchEvent(new Event('plugin-artifact-updated'));
        } catch (error) {
            el('status').textContent = error.message;
        } finally {
            pending = false;
            for (const name of ['preview', 'run', 'scope']) el(name).disabled = false;
        }
    }
    el('preview').addEventListener('click', () => cleanup(true));
    el('run').addEventListener('click', () => cleanup(false));
    updateHint();
});
