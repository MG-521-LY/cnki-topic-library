#!/usr/bin/env python3
"""Install the portable Skill for DeepSeek Harness or Codex; no network or config changes."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

NAME = 'cnki-topic-library'
PARTS = ('SKILL.md', 'agents', 'references', 'scripts', 'tests')


def source_files(source):
    entry = source / 'SKILL.md'
    content = entry.read_text(encoding='utf-8')
    if not re.search(r'^name:\s*cnki-topic-library\s*$', content, re.M) or not content.startswith('---\n'):
        raise ValueError('Source is not the cnki-topic-library Skill')
    files=[]
    for part in PARTS:
        path = source / part
        if not path.exists():
            raise ValueError(f'Missing source component: {part}')
        candidates = [path] if path.is_file() else sorted(path.rglob('*'))
        for file in candidates:
            if '__pycache__' in file.parts or file.suffix == '.pyc':
                continue
            if file.is_symlink():
                raise ValueError('Skill source cannot contain symbolic links')
            if file.is_file():
                relative = file.relative_to(source)
                if not file.resolve().is_relative_to(source.resolve()):
                    raise ValueError('Source file escapes the Skill directory')
                files.append((file, relative))
    return files


def default_root(client):
    if client == 'dsh':
        return Path(os.environ.get('DSH_HOME') or (Path.home() / '.dsh')) / 'skills'
    return Path(os.environ.get('CODEX_HOME') or (Path.home() / '.codex')) / 'skills'


def install(source, skill_root, force=False, dry_run=False):
    source = source.resolve()
    skill_root = skill_root.resolve()
    destination = skill_root / NAME
    if destination.is_symlink():
        raise ValueError('Refusing to replace a symlinked installation')
    if source == destination.resolve() or source.is_relative_to(destination.resolve()) or destination.resolve().is_relative_to(source):
        raise ValueError('Source and destination overlap')
    files = source_files(source)
    if destination.exists() and not destination.is_dir():
        raise ValueError('Destination exists and is not a directory')
    if destination.exists() and not force:
        raise ValueError('Already installed; use --force to back it up and update')
    result={'destination':str(destination),'source':str(source),'files':len(files),'dry_run':dry_run}
    if dry_run:
        return result
    skill_root.mkdir(parents=True,exist_ok=True)
    staging=Path(tempfile.mkdtemp(prefix='.cnki-stage-',dir=skill_root))
    backup=None
    try:
        hashes={}
        for file, relative in files:
            target=staging/relative
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(file,target)
            digest=hashlib.sha256(file.read_bytes()).hexdigest()
            if hashlib.sha256(target.read_bytes()).hexdigest()!=digest:
                raise ValueError('Copied file integrity check failed')
            hashes[relative.as_posix()]=digest
        (staging/'.install-manifest.json').write_text(json.dumps({'skill':NAME,'files':hashes},indent=2),encoding='utf-8')
        if destination.exists():
            stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            backup=skill_root/'.backups'/f'{NAME}-{stamp}'
            backup.parent.mkdir(parents=True,exist_ok=True)
            # Verify both resolved targets are inside the explicit Skill root before moving a directory.
            if destination.parent.resolve()!=skill_root or not backup.resolve().is_relative_to(skill_root):
                raise ValueError('Installation backup path escapes the Skill root')
            destination.rename(backup)
        staging.rename(destination)
        for relative, expected in hashes.items():
            if hashlib.sha256((destination/relative).read_bytes()).hexdigest()!=expected:
                raise ValueError('Installed file integrity check failed')
        result.update(installed=True,backup=str(backup) if backup else None)
        return result
    except Exception:
        if backup and backup.exists() and not destination.exists():
            backup.rename(destination)
        raise
    finally:
        if staging.exists():
            if staging.resolve().parent!=skill_root or not staging.name.startswith('.cnki-stage-'):
                raise ValueError('Refusing to clean an unexpected staging path')
            shutil.rmtree(staging)


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--client',choices=('dsh','codex'),default='dsh')
    parser.add_argument('--dest',type=Path,help='Skill root directory, not the individual Skill folder')
    parser.add_argument('--project',type=Path,help='Project root for a project-scoped installation')
    parser.add_argument('--force',action='store_true',help='Back up an existing Skill before updating')
    parser.add_argument('--dry-run',action='store_true')
    args=parser.parse_args()
    if args.dest and args.project:
        parser.error('--dest and --project are mutually exclusive')
    source=Path(__file__).resolve().parents[1]/'skills'/NAME
    skill_root=args.dest or (args.project/('.dsh' if args.client=='dsh' else '.agents')/'skills' if args.project else default_root(args.client))
    try:
        result=install(source,skill_root,args.force,args.dry_run)
        result['client']=args.client
        print(json.dumps(result,ensure_ascii=False))
        return 0
    except (ValueError,OSError) as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False))
        return 1


if __name__=='__main__':
    sys.exit(main())
