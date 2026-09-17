// Controller unit tests with an in-memory DOM and API; no browser/runtime required.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');

function harness() {
    class Element {
        constructor() { this.listeners = {}; this.value = ''; this.textContent = ''; this.children = []; this.open = false; }
        addEventListener(name, callback) { this.listeners[name] = callback; }
        trigger(name) { return this.listeners[name]?.({ preventDefault() {} }); }
        replaceChildren() { this.children = []; }
        appendChild(child) { this.children.push(child); }
        showModal() { this.open = true; }
        close() { this.open = false; this.trigger('close'); }
    }
    const elements = new Map();
    const element = id => {
        if (!elements.has(id)) elements.set(id, new Element());
        return elements.get(id);
    };
    let ready;
    const api = {
        state: { original_messages: [{ role: 'user', content: 'Original requirements' }], turns: [],
            test_report: { status: 'failed' }, busy: false, can_test: false,
            base_url: 'http://localhost:8080', model: 'own-model', ssl_verify: true,
            revision: 'original', artifact_sha256: 'abc' },
        posts: [],
        post: async () => ({ job_id: 'turn1' }),
    };
    const window = {};
    vm.runInNewContext(readFileSync(join(__dirname, '../../static/js/plugin-repair.js'), 'utf8'), {
        window, document: {
            getElementById: element, createElement: () => new Element(), dispatchEvent() {},
            addEventListener: (event, callback) => { if (event === 'DOMContentLoaded') ready = callback; },
        },
        Event: class {}, setTimeout: () => 1, clearTimeout() {},
        fetch: async (url, options) => {
            if (options?.method === 'POST') {
                api.posts.push({ url, options });
                const response = await api.post(url, options);
                return { ok: !response.error, json: async () => response };
            }
            return { ok: true, json: async () => structuredClone(api.state) };
        },
    });
    ready();
    return { api, window, el: name => element(`plugin-repair-${name}`) };
}

const settled = () => new Promise(resolve => setImmediate(resolve));

test('Test is enabled after completion and disabled during prompts and tests', async () => {
    const { api, window, el } = harness();
    await window.openPluginRepair('hello');
    assert.equal(el('test').disabled, true);
    assert.equal(el('send').disabled, false);
    assert.match(el('original').textContent, /Original requirements/);
    el('input').value = 'Fix the greeting';
    api.post = async () => {
        api.state.busy = true;
        api.state.turns = [{ job_id: 'turn1', status: 'running', user_prompt: 'Fix the greeting' }];
        return { job_id: 'turn1' };
    };
    el('form').trigger('submit');
    assert.equal(el('test').disabled, true);
    assert.equal(el('send').disabled, true);
    await settled();
    assert.equal(api.posts.length, 1);
    assert.equal(JSON.parse(api.posts[0].options.body).model, 'own-model');
    assert.equal(el('input').value, '');
    api.state.busy = false;
    api.state.can_test = true;
    api.state.turns[0].status = 'success';
    api.state.turns[0].response = 'Fixed <literal> greeting';
    await el('refresh').trigger('click');
    assert.equal(el('test').disabled, false);
    assert.match(el('history').children[0].textContent, /Fixed <literal> greeting/);
    api.post = async () => { api.state.test_report.status = 'running'; api.state.can_test = false; return { status: 'running' }; };
    el('test').trigger('click');
    assert.equal(el('test').disabled, true);
    await settled();
    assert.match(api.posts[1].url, /\/hello\/tests$/);
    assert.equal(el('send').disabled, true);
    api.state.test_report.status = 'failed';
    api.state.can_test = true;
    await el('refresh').trigger('click');
    assert.equal(el('test').disabled, false);
    assert.equal(el('send').disabled, false);
});

test('A failed submission retains the draft and never enables Test', async () => {
    const { api, window, el } = harness();
    await window.openPluginRepair('hello');
    el('input').value = 'Fix this';
    api.post = async () => ({ error: 'The artifact changed.' });
    el('form').trigger('submit');
    await settled();
    assert.equal(el('input').value, 'Fix this');
    assert.equal(el('test').disabled, true);
    assert.match(el('status').textContent, /artifact changed/);
});

test('Closing and reopening ignores late responses and clears the API key', async () => {
    const { api, window, el } = harness();
    await window.openPluginRepair('hello');
    el('input').value = 'First prompt';
    el('key').value = 'ephemeral-key';
    let finish;
    api.post = () => new Promise(resolve => { finish = resolve; });
    el('form').trigger('submit');
    el('dialog').close();
    assert.equal(el('key').value, '');
    await window.openPluginRepair('hello');
    el('input').value = 'New draft';
    finish({ job_id: 'turn1' });
    await settled();
    assert.equal(el('input').value, 'New draft');
});

test('Documents use Validate and the document conversation endpoints', async () => {
    const { api, window, el } = harness();
    await window.openPluginRepair('knowledge', 'rag_document');
    assert.equal(el('test').textContent, 'Validate');
    assert.equal(el('test').disabled, true);
    el('input').value = 'Expand the source notes';
    api.post = async () => {
        api.state.can_test = true;
        api.state.turns = [{ job_id: 'turn1', status: 'success', user_prompt: 'Expand the source notes', response: 'Updated.' }];
        return { job_id: 'turn1' };
    };
    el('form').trigger('submit');
    await settled();
    assert.match(api.posts[0].url, /\/api\/artifacts\/rag_document\/knowledge\/conversation$/);
    assert.equal(el('test').disabled, false);
    el('test').trigger('click');
    await settled();
    assert.match(api.posts[1].url, /\/api\/artifacts\/rag_document\/knowledge\/validate$/);
});
