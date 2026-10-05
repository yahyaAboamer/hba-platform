# Historical evidence archive — 4 October 2026

Completed visual batches, older mockup screenshots and local audit packages
were removed from the working folder after being archived and checked byte
for byte. Current Operations work, approved HTML exports, their source assets,
and the comparison harness's `shots/app` and `shots/export` baselines stay in
the repository.

The archives are local files outside this repository. A fresh clone does not
contain them; retain or copy these ZIPs when handing the archived evidence to
another machine. No private evidence was committed or uploaded.

## Historical visual evidence

[Historical visual evidence ZIP](C:/Users/AboAmer/.codex/visualizations/2026/10/04/01a10753-a49a-71f2-ba44-811608dba300/project-cleanup-audit/execution/archives/historical-visual-evidence.zip)
contains 441 original paths backed by 391 unique content objects. Duplicate
storage was reduced by 2,491,075 bytes. The archive includes:

- `docs/repair/batch-2/visual/shots/batch-e/` through the stored batches f, g,
  h, i, j, m, n and p;
- the 39 older PNG captures in `docs/design/`, excluding Operations;
- the superseded browser-window captures and original README under
  `docs/repair/batch-2/screens/`.

[Original-path manifest](archive-manifest.json) maps every original visual
file path to its size and SHA-256 object. Old documents' capture paths refer
to these archive entries. Capture scripts can still create new batch folders;
archiving their past output did not change those scripts.

## Private local evidence

[Private local evidence ZIP](C:/Users/AboAmer/.codex/visualizations/2026/10/04/01a10753-a49a-71f2-ba44-811608dba300/project-cleanup-audit/execution/archives/private-local-evidence.zip)
contains 14 original files from `HBA_Readiness_Audit/`, `design-preview/`, and
the root `orders_audit.md` scratchpad. It preserves the original supplied
audit, its screenshots and failure probes, old preview HTML and the additive
`design-preview/seed-05a.py` helper. It is private evidence: keep the ZIP and
its restored contents out of commits and application uploads.

[Superseded import-package ZIP](C:/Users/AboAmer/.codex/visualizations/2026/10/04/01a10753-a49a-71f2-ba44-811608dba300/project-cleanup-audit/execution/superseded-import-package.zip)
preserves eight provenance files from `HBA_Design_Parity_Code_Package/`. This
ZIP has ordinary file paths, rather than the deduplicated object format. Its
code commits are already ancestors of the current branch and its two working
documents remain in `docs/`.

## Opening an archived capture

Use the restore utility from the repository root. It validates all selected
paths and hashes before writing, and refuses to overwrite existing files.
Choose a separate review directory to avoid refilling the working folder:

```powershell
.venv/Scripts/python.exe -B docs/cleanup/restore-evidence.py `
  'C:/Users/AboAmer/.codex/visualizations/2026/10/04/01a10753-a49a-71f2-ba44-811608dba300/project-cleanup-audit/execution/archives/historical-visual-evidence.zip' `
  --destination 'C:/Users/AboAmer/.codex/visualizations/2026/10/04/01a10753-a49a-71f2-ba44-811608dba300/project-cleanup-audit/execution/evidence-review' `
  --path 'docs/repair/batch-2/visual/shots/batch-p/ranking-390.png'
```

Use an exact original path from the manifest. Multiple `--path` arguments
restore several files; omitting `--path` restores the full chosen archive.
The same utility opens the private evidence ZIP, whose manifest is inside it.

The six retired frontend source files remain recoverable from Git history.
The removed function bodies also have local source backups in the cleanup
execution folder; no branch or history was rewritten.
