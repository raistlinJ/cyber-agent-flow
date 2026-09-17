# Marked

Pinned browser bundle from [Marked v18.0.13](https://github.com/markedjs/marked/releases/tag/v18.0.13),
distributed under the included MIT license. Served locally so analysis results do
not depend on CDN availability. No Node.js install is required to run the app.

Source: `https://registry.npmjs.org/marked/-/marked-18.0.13.tgz`
(files `package/lib/marked.umd.js` and `package/LICENSE`).
The package's SHA-512 integrity was verified against its npm registry metadata.

When updating, replace the bundle and license from a pinned release and run
`node --test tests/js/*.test.cjs` and
`venv/bin/python -m pytest tests/test_analysis_jobs.py -q`.
Keep all analysis rendering behind `renderSafeAnalysisMarkdown`; Marked itself
does not sanitize HTML.
