import concurrent.futures
import csv
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/library_jobs.py'
spec = importlib.util.spec_from_file_location('library_jobs', SCRIPT)
jobs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jobs)


def pdf_bytes(label='paper one'):
    """Small valid one-page PDF with correct offsets and a unique text stream."""
    stream = f'BT /F1 12 Tf 40 700 Td ({label}) Tj ET'.encode()
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>',
               b'<< /Type /Pages /Kids [3 0 R] /Count 1 >>',
               b'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
               b'<< /Length ' + str(len(stream)).encode() + b' >>\nstream\n' + stream + b'\nendstream']
    content = bytearray(b'%PDF-1.4\n')
    offsets = [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(content))
        content.extend(f'{index} 0 obj\n'.encode() + obj + b'\nendobj\n')
    xref = len(content)
    content.extend(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        content.extend(f'{offset:010d} 00000 n \n'.encode())
    content.extend(f'trailer\n<< /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    return bytes(content)


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.task = self.base / 'task'
        self.call('init', '--topic', '生成式AI与自主学习', '--count', '2')

    def tearDown(self):
        self.temp.cleanup()

    def call(self, command, *args, ok=True):
        result = subprocess.run([sys.executable, str(SCRIPT), command, '--task', str(self.task), *map(str, args)],
                                capture_output=True, encoding='utf-8')
        self.assertEqual(result.returncode == 0, ok, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def input(self, name, data):
        path = self.base / name
        path.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        return path

    def seed(self, count=6):
        rows = [dict(title=f'研究{i}', authors=f'作者{i}', year=2024, field='教育学', doc_type='期刊',
                     doi=f'10.1000/{i}', citations=i*10, abstract=f'实证考察AI对自主学习的影响，样本组{i}。') for i in range(count)]
        result = self.call('ingest', '--input', self.input('papers.json', rows))
        ids = [p['id'] for p in result['papers']]
        reviews = [dict(id=pid, decision='include', relevance=95-i, evidence='abstract', reason='研究对象和效应符合主题') for i, pid in enumerate(ids)]
        self.call('review', '--input', self.input('reviews.json', reviews))
        return ids

    def file(self, name, contents):
        path = self.base / name
        path.write_bytes(contents)
        return path

    def state(self):
        return json.loads((self.task / 'task.json').read_text(encoding='utf-8'))

    def test_full_download_replacement_resume_and_export(self):
        self.seed()
        queue = self.call('next', '--limit', '5')['papers']
        self.assertEqual(len(queue), 2)
        a, b = [x['id'] for x in queue]
        self.call('record', '--id', a, '--status', 'in_progress')
        self.call('record', '--id', a, '--status', 'downloaded', '--file', self.file('a.pdf', pdf_bytes('a')))
        self.call('record', '--id', b, '--status', 'no_access', '--reason', '机构不包含此篇')
        replacement = self.call('next')['papers'][0]['id']
        self.assertNotIn(replacement, {a, b})
        self.call('record', '--id', replacement, '--status', 'in_progress')
        self.assertEqual(self.call('next')['papers'], [])
        self.assertEqual(self.call('status')['interrupted'], [replacement])
        self.call('record', '--id', replacement, '--status', 'downloaded', '--file', self.file('b.pdf', pdf_bytes('b')))
        exported = self.call('export')
        self.assertEqual(exported['summary']['verified_downloaded'], 2)
        self.assertTrue(exported['summary']['complete'])
        self.assertEqual(self.call('next')['papers'], [])
        self.assertTrue(all(Path(p).exists() for p in exported['files']))
        self.assertIn('2 / 2', (self.task / 'report.md').read_text(encoding='utf-8'))

    def test_duplicate_file_never_counts_twice(self):
        ids = self.seed()
        file = self.file('a.pdf', pdf_bytes())
        self.call('record', '--id', ids[0], '--status', 'downloaded', '--file', file)
        self.call('record', '--id', ids[1], '--status', 'downloaded', '--file', file, ok=False)
        self.assertEqual(self.call('status')['verified_downloaded'], 1)

    def test_html_and_truncated_files_rejected(self):
        ids = self.seed()
        for name, content in [('error.pdf', b'<html>login</html>' * 100), ('short.pdf', b'%PDF-1.4'),
                              ('truncated.pdf', pdf_bytes()[:-15])]:
            self.call('record', '--id', ids[0], '--status', 'downloaded', '--file', self.file(name, content), ok=False)
        self.assertEqual(self.call('status')['verified_downloaded'], 0)

    def test_modified_or_deleted_files_demoted(self):
        ids = self.seed()
        file = self.file('a.pdf', pdf_bytes())
        self.call('record', '--id', ids[0], '--status', 'downloaded', '--file', file)
        file.write_bytes(pdf_bytes('modified'))
        self.assertEqual(self.call('status')['verified_downloaded'], 0)
        self.call('record', '--id', ids[0], '--status', 'downloaded', '--file', file)
        file.unlink()
        self.assertEqual(self.call('status')['verified_downloaded'], 0)

    def test_waiting_user_pauses_entire_queue(self):
        ids = self.seed()
        self.call('record', '--id', ids[0], '--status', 'waiting_user', '--reason', '验证码')
        self.assertEqual(self.call('next')['papers'], [])
        self.call('record', '--id', ids[1], '--status', 'in_progress', ok=False)
        self.call('record', '--id', ids[0], '--status', 'pending')
        self.assertTrue(self.call('next')['papers'])

    def test_invalid_batch_is_atomic(self):
        before = (self.task / 'task.json').read_bytes()
        self.call('ingest', '--input', self.input('bad.json', [dict(title='ok'), dict(title='bad', citations=-1)]), ok=False)
        self.assertEqual(before, (self.task / 'task.json').read_bytes())
        ids = self.seed()
        before = (self.task / 'task.json').read_bytes()
        reviews = [dict(id=ids[0], decision='exclude', relevance=1, reason='排除', evidence='title'),
                   dict(id='unknown', decision='include', relevance=90, reason='无效ID', evidence='title')]
        self.call('review', '--input', self.input('badreview.json', reviews), ok=False)
        self.assertEqual(before, (self.task / 'task.json').read_bytes())

    def test_title_evidence_is_capped_and_abstract_cannot_be_fabricated(self):
        result = self.call('ingest', '--input', self.input('title.json', [dict(title='只有题名', authors='甲')]))
        pid = result['papers'][0]['id']
        review = dict(id=pid, decision='include', relevance=98, reason='对象匹配，尚未获取摘要', evidence='title')
        self.call('review', '--input', self.input('r.json', [review]))
        self.assertEqual(self.state()['papers'][0]['relevance'], 70)
        review['evidence'] = 'abstract'
        self.call('review', '--input', self.input('r.json', [review]), ok=False)

    def test_reingest_deduplicates_and_invalidates_changed_review(self):
        ids = self.seed()
        row = dict(title='研究0', authors='作者0', doi='https://doi.org/10.1000/0', abstract='新摘要', query='另一检索式')
        result = self.call('ingest', '--input', self.input('update.json', [row]))
        self.assertEqual(result['merged'], 1)
        self.assertEqual(result['papers'][0]['id'], ids[0])
        self.assertNotIn('decision', self.state()['papers'][0])
        self.assertEqual(len(self.state()['papers']), 6)

    def test_same_title_different_author_remains_distinct(self):
        rows = [dict(title='同名研究', authors=x, year=2024) for x in ('甲', '乙')]
        result = self.call('ingest', '--input', self.input('titles.json', rows))
        self.assertEqual(result['added'], 2)
        result = self.call('ingest', '--input', self.input('titles.json', rows))
        self.assertEqual(result['merged'], 2)

    def test_excluded_success_is_not_counted_and_file_preserved(self):
        ids = self.seed()
        file = self.file('a.pdf', pdf_bytes())
        self.call('record', '--id', ids[0], '--status', 'downloaded', '--file', file)
        self.call('review', '--input', self.input('exclude.json', [dict(id=ids[0], decision='exclude', relevance=10, evidence='abstract', reason='研究关系不满足条件')]))
        self.assertEqual(self.call('status')['verified_downloaded'], 0)
        self.assertTrue(file.exists())

    def test_heat_missing_ties_and_year_cohorts(self):
        ids = self.seed(6)
        state = self.state()
        self.assertEqual(state['papers'][0]['heat_evidence']['downloads']['percentile'], .5)
        self.assertEqual(state['papers'][0]['heat_evidence']['citations']['percentile'], 0)
        self.assertEqual(state['papers'][-1]['heat_evidence']['citations']['percentile'], 1)
        self.assertTrue(state['papers'][0]['heat_evidence']['downloads']['missing'])
        result = self.call('ingest', '--input', self.input('recent.json', [dict(title='新文章', authors='新作者', year=2026, field='教育学', doc_type='期刊', citations=999)]))
        recent = self.state()['papers'][-1]
        self.assertEqual(recent['heat'], .5)
        self.assertEqual(recent['heat_evidence']['citations']['sample_size'], 1)
        self.assertEqual(jobs.metric('1.2万'), 12000)
        for row in state['papers']:
            row['citations'] = 10
        jobs.score_all(state)
        self.assertTrue(all(p['heat'] == .5 for p in state['papers']))

    def test_report_csv_formula_and_url_sanitization(self):
        result = self.call('ingest', '--input', self.input('formula.json', [dict(title='=HYPERLINK("x")', authors='甲',
                    url='https://kns.cnki.net/detail?filename=A123&token=secret&dbname=CJFD')]))
        self.call('export')
        rows = list(csv.DictReader(io.StringIO((self.task / 'library.csv').read_text(encoding='utf-8-sig'))))
        self.assertTrue(rows[0]['title'].startswith("'="))
        self.assertNotIn('secret', rows[0]['url'])
        self.assertEqual(self.state()['papers'][0]['cnki_id'], 'A123')

    def test_caj_requires_explicit_opt_in(self):
        file = self.file('paper.caj', b'CAJ' + b'\0' * 1024)
        with self.assertRaises(ValueError):
            jobs.verify_file(file)
        self.assertEqual(jobs.verify_file(file, True)['format'], 'caj')

    def test_nonfinite_scores_rejected(self):
        ids = self.seed()
        for value in [float('nan'), float('inf'), -1, 101]:
            r = dict(id=ids[0], decision='include', relevance=value, reason='理由', evidence='abstract')
            self.call('review', '--input', self.input('nan.json', [r]), ok=False)

    def test_default_target_and_existing_task_protected(self):
        other = self.base / 'new'
        result = subprocess.run([sys.executable, str(SCRIPT), 'init', '--task', str(other), '--topic', '任何专业'], capture_output=True, encoding='utf-8')
        self.assertEqual(json.loads(result.stdout)['target'], 100)
        self.call('init', '--topic', 'overwrite', ok=False)
        self.assertEqual(self.state()['topic'], '生成式AI与自主学习')

    def test_actual_os_lock_rejects_parallel_writer(self):
        with jobs.task_lock(self.task):
            self.call('status', ok=False)
        self.assertEqual(self.call('status')['candidates'], 0)

    def test_every_count_below_100_is_accepted(self):
        for count in range(1, 100):
            with self.subTest(count=count):
                result = self.call('set-target', '--count', count)
                self.assertEqual(result['summary']['target'], count)
                self.assertEqual(result['summary']['remaining'], count)
        self.assertEqual(len(self.state()['target_history']), 99)

    def test_target_changes_preserve_files_and_resume_when_increased(self):
        ids = self.seed()
        files = [self.file(f'file{i}.pdf', pdf_bytes(f'file {i}')) for i in range(2)]
        for pid, file in zip(ids, files):
            self.call('record', '--id', pid, '--status', 'downloaded', '--file', file)
        result = self.call('set-target', '--count', '1')
        self.assertTrue(result['summary']['complete'])
        self.assertEqual(result['summary']['verified_downloaded'], 2)
        self.assertEqual(self.call('next')['papers'], [])
        self.assertTrue(all(f.exists() for f in files))
        result = self.call('set-target', '--count', '3')
        self.assertEqual(result['summary']['remaining'], 1)
        self.assertEqual(len(self.call('next', '--limit', '5')['papers']), 1)
        self.assertEqual(self.state()['topic'], '生成式AI与自主学习')

    def test_target_rejects_invalid_numbers_without_changing_state(self):
        before = (self.task / 'task.json').read_bytes()
        for count in ('0', '-1', '1.5', 'no', '10001'):
            result = subprocess.run([sys.executable, str(SCRIPT), 'set-target', '--task', str(self.task), '--count', count],
                                    capture_output=True, encoding='utf-8')
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(before, (self.task / 'task.json').read_bytes())

    def test_new_task_custom_count_is_respected(self):
        for count in (1, 5, 20, 30, 99):
            target = self.base / f'custom{count}'
            result = subprocess.run([sys.executable, str(SCRIPT), 'init', '--task', str(target), '--topic', '近5年研究', '--count', str(count)],
                                    capture_output=True, encoding='utf-8')
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['target'], count)

    def test_default_100_stops_at_exactly_100_with_failure_replacement(self):
        data = {'version': 1, 'topic': '跨专业主题', 'target': 100, 'min_relevance': 65,
                'allow_caj': False, 'papers': [], 'search_log': []}
        payload = [dict(title=f'论文{i}', authors=f'作者{i}', doi=f'10.1234/{i}',
                        year=2024, abstract='研究对象、方法和结果的实际摘要', citations=i) for i in range(120)]
        jobs.ingest(data, payload)
        jobs.review(data, [dict(id=p['id'], decision='include', relevance=90, evidence='abstract',
                               reason='摘要中的研究对象符合需求') for p in data['papers']])
        state_path = self.task / 'task.json'
        jobs.write_json(state_path, data)
        for index, paper in enumerate(jobs.ranked(data)[:101]):
            args = argparse_namespace(id=paper['id'], status='no_access' if index == 0 else 'downloaded',
                                      file=None if index == 0 else self.file(f'paper{index}.pdf', pdf_bytes(f'paper {index}')),
                                      reason='学校无权限' if index == 0 else None)
            jobs.record(data, args)
        jobs.write_json(state_path, data)
        self.assertEqual(self.call('status')['verified_downloaded'], 100)
        self.assertEqual(self.call('next', '--limit', '100')['papers'], [])
        self.assertEqual(self.call('export')['summary']['remaining'], 0)


def argparse_namespace(**kwargs):
    from argparse import Namespace
    return Namespace(**kwargs)


if __name__ == '__main__':
    unittest.main(verbosity=2)
