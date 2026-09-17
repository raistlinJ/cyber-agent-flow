const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');

const read = path => readFileSync(join(__dirname, '../..', path), 'utf8');
const renderer = read('static/js/analysis-markdown.js');
const main = read('static/js/main.js');
const escapeHtml = value => String(value).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

// Only text nodes and the modal shell are needed for the missing-parser path.
function harness(marked) {
    const modals = [];
    const alerts = [];
    const context = vm.createContext({
        window: { marked }, escapeHtml,
        document: {
            createElement(tag) {
                assert.notEqual(tag, 'template', 'Fallback must not parse model output as HTML');
                return {
                    style: {}, textContent: '', addEventListener() {},
                    get outerHTML() { return `<${tag}>${escapeHtml(this.textContent)}</${tag}>`; },
                };
            },
            body: { appendChild(modal) { modals.push(modal); } },
        },
        showAlert: message => alerts.push(message),
    });
    vm.runInContext(renderer, context);
    // Exercise the actual result-modal entry point and its rendering helpers,
    // without initializing the unrelated session and configuration controls.
    vm.runInContext(main.slice(main.indexOf('    function parseRecommendedToolingAssets('),
        main.indexOf('    async function renderTab(')), context);
    vm.runInContext(main.slice(main.indexOf('    function formatAnalysisOutputLabel('),
        main.indexOf('    window.downloadAnalysisJob =')), context);
    return { context, modals, alerts, render: context.window.renderSafeAnalysisMarkdown };
}

test('Analysis modal opens with escaped response and tooling fields when marked is absent', async () => {
    const { context, modals, alerts } = harness(undefined);
    const response = '## Summary\n<script>alert(1)</script>\n\n## Recommended Tooling Assets\n' +
        '- Type: MCP tool\n- Name: Probe\n- Problem: <img src=x onerror=alert(1)>\n' +
        '- Expected Gain: Less manual work\n- Why Better Than Prompting Alone: Repeatable checks\n';
    context.fetch = async () => ({ json: async () => ({ run_id: 'review', response }) });
    await context.window.viewAnalysisResult('job-1');
    assert.deepEqual(alerts, []);
    assert.equal(modals.length, 1);
    assert.match(modals[0].innerHTML, /&lt;script&gt;alert\(1\)&lt;\/script&gt;/);
    assert.match(modals[0].innerHTML, /<span>&lt;img src=x onerror=alert\(1\)&gt;<\/span>/);
    assert.doesNotMatch(modals[0].innerHTML, /<script>|<img/);
});

for (const [name, marked] of [
    ['missing methods', {}],
    ['non-callable methods', { parse: true, parseInline: true }],
    ['parser failure', { parse() { throw new Error('broken parser'); }, parseInline() { throw new Error('broken parser'); } }],
    ['unexpected output', { parse() { return undefined; }, parseInline() { return undefined; } }],
]) {
    test(`Markdown falls back to readable, escaped text on ${name}`, () => {
        const { render } = harness(marked);
        assert.equal(render('a < b & c'), '<pre>a &lt; b &amp; c</pre>');
        assert.equal(render('a < b & c', true), '<span>a &lt; b &amp; c</span>');
    });
}

test('Bundled Marked exposes the browser API and renders analysis formatting offline', () => {
    const context = vm.createContext({});
    vm.runInContext(read('static/vendor/marked/marked.umd.js'), context);
    assert.equal(typeof context.marked.parse, 'function');
    assert.equal(typeof context.marked.parseInline, 'function');
    assert.match(context.marked.parse('## Findings\n\n- **Passed**\n\n```python\nprint(1)\n```'), /<h2>Findings<\/h2>/);
    assert.match(context.marked.parse('| Check | Result |\n| --- | --- |\n| Probe | Pass |'), /<table>/);
    assert.equal(context.marked.parseInline('**Passed**'), '<strong>Passed</strong>');
});
