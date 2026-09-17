const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');

function harness() {
    const elements = new Map();
    function el(name) {
        if (!elements.has(name)) elements.set(name, {
            value: name === 'scope' ? 'containers' : '', listeners: {},
            addEventListener(event, handler) { this.listeners[event] = handler; },
            trigger(event) { return this.listeners[event]?.(); },
        });
        return elements.get(name);
    }
    const api = { calls: [], response: { containers: [], images: [], skipped: [], errors: [] }, ok: true, changed: 0 };
    let ready;
    vm.runInNewContext(readFileSync(join(__dirname, '../../static/js/gen-tool-cleanup.js'), 'utf8'), {
        document: {
            getElementById: id => el(id.replace('gen-tool-cleanup-', '')),
            addEventListener: (_, callback) => { ready = callback; },
            dispatchEvent: () => { api.changed++; },
        },
        Event: class {},
        fetch: async (url, options) => {
            api.calls.push({ url, body: JSON.parse(options.body) });
            if (api.wait) await api.wait;
            return { ok: api.ok, json: async () => api.response };
        },
    });
    ready();
    return { el, api };
}

test('Preview is a dry run and image-only selection is honored', async () => {
    const { el, api } = harness();
    assert.equal(el('image-hint').hidden, true);
    el('scope').value = 'images';
    el('scope').trigger('change');
    assert.equal(el('image-hint').hidden, false);
    api.response.images = [{ id: 'image1', tags: ['test:1'] }];
    await el('preview').trigger('click');
    assert.deepEqual(api.calls[0].body, { remove_containers: false, remove_images: true, dry_run: true });
    assert.match(el('status').textContent, /Would remove 0 container\(s\) and 1 image/);
    assert.equal(api.changed, 0);
});

test('Cleanup disables duplicate submissions and reports errors and skipped resources', async () => {
    const { el, api } = harness();
    let release;
    api.wait = new Promise(resolve => { release = resolve; });
    api.response = { containers: [{ name: 'orphan', state: 'dead' }], images: [],
        skipped: [{ resource: 'shared', reason: 'Still referenced' }], errors: [{ resource: 'broken', error: 'Busy' }] };
    const running = el('run').trigger('click');
    assert.equal(el('run').disabled, true);
    await el('run').trigger('click');
    assert.equal(api.calls.length, 1);
    release();
    await running;
    assert.equal(el('run').disabled, false);
    assert.match(el('status').textContent, /1 removal\(s\) failed/);
    assert.match(el('results').textContent, /Kept shared: Still referenced/);
    assert.match(el('results').textContent, /Failed broken: Busy/);
    assert.equal(api.changed, 1);
});

test('Active-run rejection remains visible and permits retry', async () => {
    const { el, api } = harness();
    api.ok = false;
    api.response = { error: 'Test activity is in progress.' };
    await el('run').trigger('click');
    assert.match(el('status').textContent, /in progress/);
    assert.equal(el('run').disabled, false);
    assert.equal(el('results').hidden, true);
});
