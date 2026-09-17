# Generating reusable artifacts from analysis

Open **Recommendations**, expand a completed analysis, and choose **Create artifact
from this analysis**. Pick a type, name it, add any instructions, select your inference
endpoint/model, and generate. You can also **Review** a recommended asset and change
its output type in the generation dialog.

The generator includes the analysis (or the recommended asset's scaffold), analyst
notes, and your instructions. Claude Code creates files in staging. The controller
checks the format before publication and records the source prompt and generation job.

| Type | Generated files | Checks |
| --- | --- | --- |
| MCP Tool | `manifest.json`, implementation, test suite and fixtures | Manifest, Python syntax, container tests |
| Markdown Playbook | `playbook.md` | Nonempty Markdown file |
| Markdown Document | `document.md` | Nonempty Markdown file |
| Agent Skill | `SKILL.md`, optional `references/` and `assets/` text files | YAML metadata, folder/name agreement, instructions, supported file types |
| RAG Document | `document.md`, `metadata.json`, `chunks.jsonl` | Title/summary/tags, source-derived chunks |
| Reusable Template | `TEMPLATE.md`, `README.md` | `{{variable_name}}` placeholders and their documentation |
| Structured JSON | `data.json`, `README.md` | Nonempty JSON object/array, accompanying documentation |

## Library and storage

Open **Configuration → Artifacts** to see generated output. Tools and playbooks can
be enabled for live sessions. **Documents & Reusable Assets** provides **Preview**,
**Download ZIP**, **Validate**, and **Continue with Claude** for document formats.
The preview displays source text without executing or rendering generated HTML.

Storage locations:

- MCP tools: `plugins/mcp_tools/<name>/`
- Playbooks: `plugins/playbooks/<name>.md`
- Other types: `plugins/artifacts/<kind>/<name>/`
- Document validation reports: `plugins/validation_results/<kind>/<name>.json`
- Generation and conversation records: `runs/<run_id>/plugin_jobs/`

Packages include a controller-written `PROVENANCE.md` with source session and prompt.
For playbooks this is stored as `<name>.PROVENANCE.md` beside the document. ZIP exports
place all files, including provenance, inside a `<name>/` folder. Existing artifacts
are not overwritten without the API's explicit `overwrite: true` flag.

## Skills

Skills use `SKILL.md` with YAML `name` and `description`, following the basic
[Agent Skills format](https://agentskills.io/specification). Names are normalized to
lowercase letters, numbers, and hyphens and match the exported folder. Instructions
may have supporting `.md`, `.txt`, or `.json` files under `references/` or `assets/`.
This first version generates instruction-only skills; scripts remain part of the MCP
tool workflow with container tests. Export the package and install it in a compatible
agent separately. Generating a skill does not install it or grant tool permissions.

## RAG documents

The model creates a knowledge document and metadata containing `title`, `summary`,
and `tags`. The controller derives `chunks.jsonl`, with stable chunk IDs, source file,
title, and chunk text copied from `document.md`. Chunks are at most 1,800 characters
and split at nearby whitespace where possible. IDs include the document name, chunk
index, and a text digest.

Download the ZIP and pass its JSONL to your ingestion pipeline. The app does not yet
provide a vector index, embedding generation, or retrieval service. These are text
exports for RAG ingestion; Word/PDF exports are not included. Format validation checks
chunk consistency, not the truth of generated claims. Review the document against
its recorded source analysis before adding it to a knowledge base.

## Editing and rechecking

**Continue with Claude** restores the original prompt, current files, previous turns,
and latest validation results. After a successful prompt, the **Validate** button
becomes available for documents; tools retain the **Test** button and container runner.
RAG edits regenerate chunks automatically. Failed edits leave the previous artifact
intact. Reports become outdated when their files change.

## API and extensions

- `GET /api/artifacts/types` returns supported types and generation contracts.
- `POST /api/scaffolding/generate` accepts `kind`, `run_id`, `asset_name`, inference
  settings, and optional `instructions`. Add `analysis_job_id` to generate directly
  from a successful analysis in that session instead of an existing scaffold.
- `GET /api/plugins` includes an `artifacts` collection for document types.
- `GET /api/artifacts/<kind>/<name>` previews files and validation status.
- `GET /api/artifacts/<kind>/<name>/download` exports the ZIP package.
- `POST /api/artifacts/<kind>/<name>/validate` validates the saved package.
- `GET/POST /api/artifacts/<kind>/<name>/conversation` restores/continues editing
  using the same revision and fingerprint contract as tools.

`artifact_catalog.py` defines the format catalog, prompts, and validators. Adding a
document kind requires a contract and validator; the type picker and recommendation
groups use that catalog. `artifact_store.py` handles document storage and reports.
