import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
SCRIPT=ROOT/'scripts/install.py'
spec=importlib.util.spec_from_file_location('skill_install',SCRIPT)
installer=importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)
SOURCE=ROOT/'skills/cnki-topic-library'


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.base=Path(self.temp.name)
        self.dest=self.base/'custom-skill-root'

    def tearDown(self):
        self.temp.cleanup()

    def call(self,*args,ok=True,env=None):
        r=subprocess.run([sys.executable,str(SCRIPT),*map(str,args)],capture_output=True,encoding='utf-8',env=env)
        self.assertEqual(r.returncode==0,ok,r.stdout+r.stderr)
        return json.loads(r.stdout)

    def test_install_and_execute_installed_helper(self):
        result=self.call('--client','dsh','--dest',self.dest)
        path=Path(result['destination'])
        self.assertTrue((path/'SKILL.md').exists())
        self.assertTrue((path/'references/deepseek-harness.md').exists())
        manifest=json.loads((path/'.install-manifest.json').read_text())
        self.assertEqual(len(manifest['files']),result['files'])
        r=subprocess.run([sys.executable,str(path/'scripts/library_jobs.py'),'init','--task',str(self.base/'task'),'--topic','测试主题','--count','5'],capture_output=True,encoding='utf-8')
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertEqual(json.loads(r.stdout)['target'],5)

    def test_existing_install_refused_without_force(self):
        self.call('--dest',self.dest)
        marker=self.dest/'cnki-topic-library/user-note.txt'
        marker.write_text('keep me')
        self.call('--dest',self.dest,ok=False)
        self.assertEqual(marker.read_text(),'keep me')

    def test_force_update_keeps_backup_including_user_files(self):
        self.call('--dest',self.dest)
        marker=self.dest/'cnki-topic-library/user-note.txt'
        marker.write_text('keep me')
        result=self.call('--dest',self.dest,'--force')
        self.assertEqual((Path(result['backup'])/'user-note.txt').read_text(),'keep me')
        self.assertTrue((Path(result['destination'])/'SKILL.md').exists())

    def test_dry_run_creates_no_files(self):
        result=self.call('--dest',self.dest,'--dry-run')
        self.assertTrue(result['dry_run'])
        self.assertFalse(self.dest.exists())

    def test_project_scope_is_direct_directory_bundle(self):
        for client,folder in (('dsh','.dsh'),('codex','.agents')):
            result=self.call('--client',client,'--project',self.base/client)
            self.assertEqual(Path(result['destination']),self.base/client/folder/'skills/cnki-topic-library')
            self.assertTrue((Path(result['destination'])/'SKILL.md').exists())

    def test_environment_roots_are_respected(self):
        env=dict(os.environ,DSH_HOME=str(self.base/'dsh-home'),CODEX_HOME=str(self.base/'codex-home'))
        for client in ('dsh','codex'):
            result=self.call('--client',client,env=env)
            self.assertEqual(Path(result['destination']),self.base/f'{client}-home'/'skills/cnki-topic-library')

    def test_overlap_is_rejected(self):
        with self.assertRaises(ValueError):
            installer.install(SOURCE,SOURCE.parent)

    def test_symlinked_destination_is_rejected(self):
        self.dest.mkdir()
        target=self.base/'actual-target'
        target.mkdir()
        try:
            (self.dest/'cnki-topic-library').symlink_to(target,target_is_directory=True)
        except OSError:
            self.skipTest('OS does not permit creating directory symlinks')
        self.call('--dest',self.dest,'--force',ok=False)


if __name__=='__main__':
    unittest.main(verbosity=2)
