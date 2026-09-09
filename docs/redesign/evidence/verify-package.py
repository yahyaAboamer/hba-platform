"""Verify original selected design bytes and the handoff's cross references.

This does not execute prototype JS, install dependencies or test the application.
Run: python docs/redesign/evidence/verify-package.py
"""
from pathlib import Path
import csv
import hashlib
import json
import re

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / 'evidence/source-manifest.json').read_text())
issues = []
for entry in manifest['files']:
    p = root / entry['path']
    if not p.is_file():
        issues.append('Missing: ' + entry['path'])
    elif hashlib.sha256(p.read_bytes()).hexdigest() != entry['sha256']:
        issues.append('Changed source asset: ' + entry['path'])

def csv_rows(name):
    with (root/name).open(encoding='utf-8-sig',newline='') as f:
        return list(csv.DictReader(f))

screens = csv_rows('SCREEN_AND_ACTION_MAP.csv')
checks = csv_rows('ACCEPTANCE_CHECKS.csv')
check_ids = {x['id'] for x in checks}
rule_ids = set(re.findall(r'^\| ([A-Z]\d\d) \|', (root/'PRODUCT_RULES.md').read_text(),re.M))
for name, rows in [('screen', screens), ('check', checks)]:
    ids=[x['id'] for x in rows]
    if len(set(ids)) != len(ids): issues.append('Duplicate '+name+' ID')
for row in screens:
    for check in row['checks'].split():
        if check not in check_ids: issues.append(row['id']+': unknown check '+check)
    for rule in row['rules'].split():
        if rule not in rule_ids: issues.append(row['id']+': unknown rule '+rule)

for name in ['START_HERE.md','STATUS.md','PRODUCT_RULES.md','DECISIONS.md',
             'REPOSITORY_AUDIT.md','BACKEND_CONTRACTS.md','DESIGN_REVIEW.md',
             'MIGRATION_AND_RELEASE.md','IMPLEMENTATION_ROADMAP.md',
             'templates/BATCH_REPORT.md','templates/DECISION_RECORD.md',
             'prompts/00_START.md','prompts/RESUME.md']:
    if not (root/name).is_file():issues.append('Missing document: '+name)
for i in range(10):
    matches=list((root/'prompts').glob(f'{i:02d}_*.md'))
    if len(matches)!=1:issues.append(f'Expected one phase {i:02d} prompt')

# Check relative script/stylesheet/image references in the selected HTML exports.
for name in manifest['selected_designs']:
    p=root/name
    if not p.exists():continue
    for ref in re.findall(r'(?:src|href)=["\']([^"\']+)["\']',p.read_text()):
        if re.match(r'^(?:https?:|data:|#|\{|mailto:|tel:)',ref):continue
        clean=ref.split('?')[0].split('#')[0]
        if clean and not (p.parent/clean).exists():issues.append(name+': missing reference '+ref)

report={
    'source_assets_verified': len(manifest['files']),
    'screen_action_rows':len(screens),
    'acceptance_checks':len(checks),
    'numbered_phase_prompts':10,
    'issues':issues,
    'scope':'Package integrity and source references only; not application implementation/test results',
}
print(json.dumps(report,indent=2))
raise SystemExit(1 if issues else 0)
