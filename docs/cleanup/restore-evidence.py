"""Restore selected historical evidence from the deduplicated cleanup ZIP.

This checks hashes and never overwrites an existing file. The default
destination is the current directory; use --destination for a separate review
folder, and --path repeatedly to restore only the entries needed.
"""

import argparse
import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--destination', type=Path, default=Path.cwd())
    parser.add_argument('--path', action='append', default=[])
    args = parser.parse_args()
    destination = args.destination.resolve()
    requested = set(args.path)
    with zipfile.ZipFile(args.archive) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('format') != 'hba-deduplicated-evidence-v1':
            parser.error('Unsupported evidence archive format')
        entries = [e for e in manifest['entries'] if not requested or e['path'] in requested]
        missing = requested - {e['path'] for e in entries}
        if missing:
            parser.error('Paths not in archive: ' + ', '.join(sorted(missing)))
        verified = []
        for entry in entries:
            relative = PurePosixPath(entry['path'])
            if relative.is_absolute() or '..' in relative.parts or '\\' in entry['path'] or ':' in entry['path'] or not relative.parts or relative.parts[0] in ('.git', '.venv'):
                parser.error('Unsafe archive path: ' + entry['path'])
            target = (destination / entry['path']).resolve()
            if not target.is_relative_to(destination) or target.exists():
                parser.error('Target outside destination or already exists: ' + str(target))
            raw = archive.read(entry['object'])
            if len(raw) != entry['bytes'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
                parser.error('Evidence hash mismatch: ' + entry['path'])
            verified.append((target, raw))
        for target, raw in verified:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open('xb') as stream:
                stream.write(raw)
    print(f'Restored {len(verified)} verified evidence files.')


if __name__ == '__main__':
    main()
