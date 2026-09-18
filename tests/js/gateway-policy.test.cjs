const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');

const source = readFileSync(join(__dirname, '../../static/js/main.js'), 'utf8');

function restore(defaults, saved) {
    const context = vm.createContext({
        console, _policyDraft: { allow: ['*'], disallow: [] },
        _llmRouteGateway: '', _llmRouteGatewayAdded: false,
        LAST_SETTINGS_STORAGE_KEY: 'settings', LAST_SETTINGS_SESSION_STORAGE_KEY: 'fallback',
        localStorage: { getItem: () => saved ? JSON.stringify(saved) : null },
        sessionStorage: { getItem: () => null },
        document: { getElementById: id => id === 'cli-config-defaults' ? { textContent: JSON.stringify(defaults) } : null },
        providerSelect: null, ollamaUrlInput: null, sslVerifyToggle: null,
        maxTurnsInput: null, toolTimeoutInput: null, kaliCommandType: null,
        toolsJsonArea: null, modelSelect: null, toolCheckboxes: [], policyEntryTypeInputs: [],
        normalizeProvider: value => value, normalizePolicy: value => value,
        updateShellSequenceDependency() {}, renderInlineToolGuideControls() {}, updatePolicyEntryEditor() {},
    });
    vm.runInContext(source.slice(source.indexOf('    function restoreLastSettings('),
        source.indexOf('    function updateShellSequenceDependency(')), context);
    vm.runInContext(source.slice(source.indexOf('    function ensureLlmGatewayExcluded('),
        source.indexOf('    policyEntryTypeInputs.forEach(input => {', source.indexOf('    function ensureLlmGatewayExcluded('))), context);
    assert.equal(context.restoreLastSettings(), true);
    return context;
}

test('First visit loads provisioned policy and remembers the managed gateway', () => {
    const context = restore({
        policyDraft: { allow: ['10.0.0.0/24'], disallow: ['192.168.80.2'] },
        llmRouteGateway: '192.168.80.2', llmRouteGatewayAdded: true,
    });
    assert.deepEqual(Array.from(context._policyDraft.disallow), ['192.168.80.2']);
    assert.equal(context._llmRouteGatewayAdded, true);
});

test('Desktop gateway changes replace managed browser exclusions and preserve custom targets', () => {
    const context = restore({ llmRouteGateway: '192.168.80.3' }, {
        policyDraft: { allow: ['10.0.0.0/24'], disallow: ['10.0.0.10', '192.168.80.2'] },
        llmRouteGateway: '192.168.80.2', llmRouteGatewayAdded: true,
    });
    assert.deepEqual(Array.from(context._policyDraft.allow), ['10.0.0.0/24']);
    assert.deepEqual(Array.from(context._policyDraft.disallow), ['10.0.0.10', '192.168.80.3']);
});

test('A gateway exclusion originally entered by the user survives a route change', () => {
    const context = restore({ llmRouteGateway: '192.168.80.3' }, {
        policyDraft: { allow: ['*'], disallow: ['192.168.80.2'] },
        llmRouteGateway: '192.168.80.2', llmRouteGatewayAdded: false,
    });
    assert.deepEqual(Array.from(context._policyDraft.disallow), ['192.168.80.2', '192.168.80.3']);
});
