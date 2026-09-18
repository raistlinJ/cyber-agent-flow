const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');

const source = readFileSync(join(__dirname, '../../static/js/main.js'), 'utf8');

function harness() {
    const element = () => ({ style: {}, disabled: false, value: '' });
    const alerts = [];
    const context = vm.createContext({
        _serviceRunning: true, _awaitingToolTimeoutDecision: false,
        _toolTimeoutDecisionVersion: 0, _activeToolState: null, _activeToolEntry: null,
        toolTimeoutModalOverlay: element(), toolTimeoutWaitSelect: element(),
        backgroundToolTimeoutBtn: element(), killToolTimeoutBtn: element(),
        progressModal: element(), toolTimeoutMessage: element(), toolTimeoutCommand: element(),
        markActiveToolWaiting() {}, finalizeActiveToolEntry() {}, clearActiveToolStatus() {},
        appendLog() {}, formatElapsedDuration: String, escapeHtml: String,
        renderActiveToolEntry() {}, showAlert: message => alerts.push(message),
    });
    // Exercise the real modal and event handlers without initializing unrelated UI.
    vm.runInContext(source.slice(source.indexOf('    function closeToolTimeoutModal('),
        source.indexOf("    toolTimeoutWaitSelect.addEventListener('change'")), context);
    vm.runInContext(source.slice(source.indexOf('    function renderEvent('),
        source.indexOf('    function updateContextBar(')), context);
    context.renderEvent({ type: 'tool_timeout_decision', command: 'example' });
    return { context, alerts };
}

test('Tool completion dismisses the checkpoint before the chat turn ends', () => {
    for (const exit_code of [0, 1]) {
        const { context, alerts } = harness();
        assert.equal(context.toolTimeoutModalOverlay.style.display, 'flex');
        context.renderEvent({ type: 'tool_result', exit_code, duration_ms: 100 });
        assert.equal(context.toolTimeoutModalOverlay.style.display, 'none');
        assert.equal(context._awaitingToolTimeoutDecision, false);
        assert.deepEqual(alerts, []);
    }
});

test('An already-resolved checkpoint response dismisses the modal without an alert', async () => {
    const { context, alerts } = harness();
    context.fetch = async () => ({ json: async () => ({
        success: false, code: 'no_pending_tool_timeout',
        error: 'No pending tool timeout decision to resolve.',
    }) });
    await context.resolveToolTimeoutDecision('wait', 60);
    assert.equal(context.toolTimeoutModalOverlay.style.display, 'none');
    assert.deepEqual(alerts, []);
});

for (const outcome of ['success', 'error', 'network failure']) {
    test(`Late ${outcome} cannot affect a newer checkpoint`, async () => {
        const { context, alerts } = harness();
        let finish;
        context.fetch = () => new Promise((resolve, reject) => {
            finish = () => outcome === 'network failure'
                ? reject(new Error('Connection lost'))
                : resolve({ json: async () => ({ success: outcome === 'success', error: 'Old error' }) });
        });
        const pending = context.resolveToolTimeoutDecision('kill');
        context.renderEvent({ type: 'tool_result', exit_code: 0 });
        context.renderEvent({ type: 'tool_timeout_decision', command: 'next command' });
        finish();
        await pending;
        assert.equal(context.toolTimeoutModalOverlay.style.display, 'flex');
        assert.equal(context._awaitingToolTimeoutDecision, true);
        assert.equal(context.killToolTimeoutBtn.disabled, false);
        assert.deepEqual(alerts, []);
    });
}

test('Other submission failures remain visible and allow retry', async () => {
    const { context, alerts } = harness();
    context.fetch = async () => ({ json: async () => ({ success: false, error: 'Invalid action' }) });
    await context.resolveToolTimeoutDecision('wait', 60);
    assert.equal(context.toolTimeoutModalOverlay.style.display, 'flex');
    assert.equal(context.toolTimeoutWaitSelect.disabled, false);
    assert.deepEqual(alerts, ['Invalid action']);
});
