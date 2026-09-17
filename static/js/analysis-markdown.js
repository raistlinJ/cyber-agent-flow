// Rebuild model-supplied Markdown using only inert formatting elements.
window.renderSafeAnalysisMarkdown = function (source, inline = false) {
    source = String(source ?? '');
    function plainText() {
        const fallback = document.createElement(inline ? 'span' : 'pre');
        fallback.textContent = source;
        return fallback.outerHTML;
    }
    const parser = window.marked;
    const parse = inline ? parser?.parseInline : parser?.parse;
    if (typeof parse !== 'function') return plainText();
    let html;
    try {
        html = parse.call(parser, source, { async: false });
    } catch (_) {
        return plainText();
    }
    if (typeof html !== 'string') return plainText();
    const template = document.createElement('template');
    template.innerHTML = html;
    const allowed = new Set([
        'P', 'BR', 'HR', 'H1', 'H2', 'H3', 'H4', 'H5', 'H6', 'STRONG', 'EM',
        'B', 'I', 'S', 'DEL', 'BLOCKQUOTE', 'PRE', 'CODE', 'UL', 'OL', 'LI',
        'TABLE', 'THEAD', 'TBODY', 'TR', 'TH', 'TD', 'A',
    ]);
    function clean(node) {
        if (node.nodeType === Node.TEXT_NODE) return document.createTextNode(node.textContent);
        if (node.nodeType !== Node.ELEMENT_NODE) return document.createTextNode('');
        if (!allowed.has(node.tagName)) return document.createTextNode(node.textContent);
        const element = document.createElement(node.tagName.toLowerCase());
        if (node.tagName === 'A' && node.hasAttribute('href')) {
            try {
                const url = new URL(node.getAttribute('href'), window.location.href);
                if (['http:', 'https:', 'mailto:'].includes(url.protocol)) {
                    element.setAttribute('href', url.href);
                    element.setAttribute('rel', 'noreferrer noopener');
                }
            } catch (_) { /* Keep link text when the URL is invalid. */ }
        }
        node.childNodes.forEach(child => element.appendChild(clean(child)));
        return element;
    }
    const output = document.createElement('div');
    template.content.childNodes.forEach(node => output.appendChild(clean(node)));
    return output.innerHTML;
};
