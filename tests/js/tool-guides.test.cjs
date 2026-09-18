const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const vm = require('node:vm');

const source = readFileSync(join(__dirname, '../../static/js/main.js'), 'utf8');

function harness() {
    class Element {
        constructor() { this.children = []; this.listeners = {}; this.checked = false; this.classList = { toggle() {} }; }
        setAttribute() {}
        appendChild(child) { this.children.push(child); }
        addEventListener(name, callback) { (this.listeners[name] ??= []).push(callback); }
        trigger(name) { for (const callback of this.listeners[name] || []) callback({ preventDefault() {}, stopPropagation() {} }); }
        click() { this.checked = !this.checked; this.trigger('click'); this.trigger('change'); }
        querySelector(selector) { return this.children.find(child => selector.includes(child.className)); }
    }
    const tool = new Element();
    tool.value = 'shell';
    const label = new Element();
    tool.closest = () => label;
    const context = vm.createContext({
        toolCheckboxes: [tool], document: { createElement: () => new Element() },
        persistLastSettings() {}, updateToolsJson() {},
    });
    vm.runInContext(source.slice(source.indexOf('    const TOOL_GUIDE_LABELS ='),
        source.indexOf('    function buildSelectedToolsConfig(')), context);
    vm.runInContext(source.slice(source.indexOf("    toolCheckboxes.forEach(cb => cb.addEventListener('change'"),
        source.indexOf('    updateShellSequenceDependency();', source.indexOf("    toolCheckboxes.forEach(cb => cb.addEventListener('change'"))), context);
    context.renderInlineToolGuideControls();
    return { context, tool, guide: label.children[0].children[0], icon: label.children[0].children[1] };
}

test('Selecting a tool selects its guide; deselecting excludes both', () => {
    const { context, tool, guide } = harness();
    assert.equal(guide.disabled, true);
    tool.click();
    assert.equal(guide.checked, true);
    assert.equal(guide.disabled, false);
    assert.deepEqual(Array.from(context.selectedToolGuides()), ['shell']);
    tool.click();
    assert.equal(guide.checked, false);
    assert.deepEqual(Array.from(context.selectedToolGuides()), []);
});

test('Document icon toggles the guide independently, and reselecting the tool includes it again', () => {
    const { context, tool, guide, icon } = harness();
    tool.click();
    icon.trigger('click');
    assert.equal(tool.checked, true);
    assert.equal(guide.checked, false);
    assert.deepEqual(Array.from(context.selectedToolGuides()), []);
    tool.click();
    tool.click();
    assert.equal(guide.checked, true);
});

test('Initially enabled tools include their guide unless explicitly deselected', () => {
    const { context, tool, guide } = harness();
    tool.checked = true;
    vm.runInContext('_toolGuideSelections = {};', context);
    context.renderInlineToolGuideControls();
    assert.equal(guide.checked, true);
    guide.click();
    context.renderInlineToolGuideControls();
    assert.equal(guide.checked, false);
});
