import hashlib
import io
import json
import os
import re
import tempfile
import unicodedata
import unittest
from pathlib import Path

from ragflow_export import exporter
from ragflow_export.client import RagflowClient
from ragflow_export.errors import AuthError, FilterError, IncompleteExport, OutDirRefused, UnsafeIdentifier
from ragflow_export.exporter import ExportOptions
from tests.fake_ragflow import API_KEY, FakeRagflow, refresh_counts

# Written from the research's list of confirmed routes, independently of the client's own table.
CONFIRMED_ROUTES = [
    re.compile(r'/api/v1/datasets'),
    re.compile(r'/api/v1/datasets/[^/]+/documents'),
    re.compile(r'/api/v1/datasets/[^/]+/documents/[^/]+'),
    re.compile(r'/api/v1/datasets/[^/]+/documents/[^/]+/chunks'),
]
DOWNLOAD = re.compile(r'/api/v1/datasets/[^/]+/documents/[^/]+')
LISTING = re.compile(r'/api/v1/datasets(/[^/]+/documents)?')


def all_files(root: Path) -> dict[str, str]:
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in sorted(root.rglob('*')) if p.is_file()}


def link_folder(link: Path, target: Path) -> None:
    """A folder link: a junction on Windows (no privilege needed), a symlink elsewhere."""
    if os.name == 'nt':
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def edit_done_record(doc_dir: Path, **changes) -> None:
    path = doc_dir / 'done.json'
    record = json.loads(path.read_text(encoding='utf-8'))
    for key, value in changes.items():
        if isinstance(value, dict):
            record[key].update(value)
        else:
            record[key] = value
    path.write_text(json.dumps(record), encoding='utf-8')


class ExportCase(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (self.root / 'quarantine').mkdir()
        self.out = self.root / 'quarantine' / 'export'
        self.fake = self.enterContext(FakeRagflow())
        self.sleeps: list[float] = []
        self.log: list[str] = []

    def client(self, base_url: str | None = None, key: str = API_KEY, **kwargs) -> RagflowClient:
        return RagflowClient(base_url or self.fake.base_url, key, sleep=self.sleeps.append, **kwargs)

    def options(self, **kwargs) -> ExportOptions:
        kwargs.setdefault('out_dir', self.out)
        kwargs.setdefault('page_size', 3)
        return ExportOptions(**kwargs)

    def export(self, client: RagflowClient | None = None, **kwargs) -> dict:
        return exporter.export(client or self.client(), self.options(**kwargs), log=self.log.append)

    def manifest(self) -> dict:
        return json.loads((self.out / 'manifest.json').read_text(encoding='utf-8'))

    def state(self) -> dict:
        return json.loads((self.out / 'export-state.json').read_text(encoding='utf-8'))

    def document_entry(self, doc_id: str) -> dict:
        for dataset in self.manifest()['datasets']:
            for doc in dataset['documents']:
                if doc['id'] == doc_id:
                    return doc
        raise AssertionError(f'{doc_id} not in manifest')

    def make_incomplete(self) -> str:
        path = '/api/v1/datasets/ds02clients/documents/doc03odd/chunks'
        self.fake.broken[path] = 500
        with self.assertRaises(IncompleteExport):
            self.export()
        return path


class FullExportTests(ExportCase):
    def test_writes_originals_chunks_and_a_manifest_with_counts_and_hashes(self):
        self.export()

        blobs = self.fake.data['blobs']
        self.assertEqual(self.manifest()['counts'], {
            'datasets': 3, 'documents': 5, 'documents_exported': 5, 'chunks': 11,
            'original_bytes': sum(len(b) for b in blobs.values())})
        for doc_id, blob in blobs.items():
            entry = self.document_entry(doc_id)
            saved = (self.out / entry['original']['path']).read_bytes()
            self.assertEqual(saved, blob, doc_id)
            self.assertEqual(entry['original']['sha256'], hashlib.sha256(blob).hexdigest(), doc_id)

    def test_keeps_arabic_chunk_text_exactly_as_served(self):
        self.export()

        entry = self.document_entry('doc01lease')
        raw = (self.out / entry['chunks']['path']).read_bytes()
        saved = [json.loads(line)['content'] for line in raw.decode('utf-8').splitlines()]
        served = [c['content'] for c in self.fake.data['chunks']['doc01lease']]
        self.assertEqual(saved, served)
        self.assertIn('يُعاقَبُ'.encode('utf-8'), raw)
        self.assertEqual(entry['chunks']['sha256'], hashlib.sha256(raw).hexdigest())

    def test_sha256sums_lists_every_file_but_itself_and_the_manifest(self):
        self.export()

        listed = {}
        for line in (self.out / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
            digest, name = line.split('  ', 1)
            listed[name] = digest
        expected = {k: v for k, v in all_files(self.out).items() if k not in ('SHA256SUMS', 'manifest.json')}
        self.assertEqual(listed, expected)
        sums_digest = hashlib.sha256((self.out / 'SHA256SUMS').read_bytes()).hexdigest()
        self.assertEqual(self.manifest()['sha256sums_sha256'], sums_digest)

    def test_sends_only_get_requests_to_the_confirmed_routes(self):
        self.export()

        self.assertEqual({r.method for r in self.fake.requests}, {'GET'})
        stray = [p for p in self.fake.paths() if not any(r.fullmatch(p) for r in CONFIRMED_ROUTES)]
        self.assertEqual(stray, [])

    def test_probes_the_version_only_when_asked_and_marks_the_route_unconfirmed(self):
        self.export(probe_version=True)

        self.assertIn('/api/v1/system/version', self.fake.paths())
        version = self.manifest()['server_version']
        self.assertEqual((version['value'], version['confirmed']), ('v0.27.3-fake', False))

    def test_writes_the_quarantine_readme(self):
        self.export()

        readme = (self.out / 'README.md').read_text(encoding='utf-8')
        self.assertIn('client facts', readme)
        self.assertIn('must not enter the library', readme)
        self.assertIn('موكلين', readme)
        self.assertIn(self.fake.base_url, readme)

    def test_document_names_cannot_place_files_outside_the_export(self):
        self.export()

        self.assertEqual([p.name for p in self.root.iterdir()], ['quarantine'])
        self.assertEqual([p.name for p in (self.root / 'quarantine').iterdir()], ['export'])
        hostile = self.document_entry('doc04hostile')
        self.assertEqual(hostile['original']['path'], 'datasets/ds02clients/documents/doc04hostile/original.pdf')
        self.assertEqual(hostile['name'], '../../hostile.pdf')
        self.assertTrue(self.document_entry('doc03odd')['original']['path'].endswith('/original.docx'))

    def test_leaves_no_temporary_files(self):
        self.fake.truncate['doc02memo'] = 1

        self.export()

        self.assertEqual([p for p in self.out.rglob('*') if p.name.endswith(exporter.TMP_SUFFIX)], [])

    def test_records_a_count_mismatch_as_a_warning(self):
        self.fake.reported_chunk_count['doc02memo'] = 5

        self.export()

        warnings = [w for w in self.manifest()['warnings'] if w.get('document_id') == 'doc02memo']
        self.assertEqual(len(warnings), 1)
        self.assertIn('chunk', warnings[0]['message'])

    def test_logs_identifiers_but_no_names(self):
        self.export()

        text = '\n'.join(self.log)
        self.assertIn('doc01lease', text)
        names = [d['name'] for d in self.fake.data['datasets']]
        names += [d['name'] for docs in self.fake.data['documents'].values() for d in docs]
        self.assertEqual([n for n in names if n in text], [])


class FailureTests(ExportCase):
    def test_an_auth_failure_writes_nothing(self):
        with self.assertRaises(AuthError):
            self.export(self.client(key='not-the-key'))

        self.assertFalse(self.out.exists())

    def test_a_json_error_instead_of_file_bytes_leaves_the_export_incomplete(self):
        self.fake.download_json_error.add('doc02memo')

        with self.assertRaises(IncompleteExport) as caught:
            self.export()

        self.assertEqual([f['document_id'] for f in caught.exception.failures], ['doc02memo'])
        self.assertFalse((self.out / 'manifest.json').exists())
        self.assertEqual(list((self.out / 'datasets/ds01laws/documents/doc02memo').glob('original*')), [])
        self.assertEqual(self.state()['status'], 'incomplete')

    def test_an_unsafe_document_id_is_a_failure_and_nothing_is_written_for_it(self):
        self.fake.data['documents']['ds02clients'].append({'id': '../../escape', 'name': 'x.pdf', 'run': 'DONE'})
        self.fake.data['blobs']['../../escape'] = b'x'
        refresh_counts(self.fake.data)

        with self.assertRaises(IncompleteExport) as caught:
            self.export()

        self.assertEqual([f['document_id'] for f in caught.exception.failures], ['../../escape'])
        self.assertEqual([p for p in self.root.rglob('*escape*')], [])

    def test_the_key_appears_in_no_file_and_no_log(self):
        self.fake.echo_auth.add('/api/v1/datasets/ds02clients/documents/doc03odd/chunks')

        with self.assertRaises(IncompleteExport) as caught:
            self.export()

        self.assertIn('fake rejected header', json.dumps(self.state(), ensure_ascii=False))
        leaks = [name for name, _ in all_files(self.out).items() if API_KEY.encode() in (self.out / name).read_bytes()]
        self.assertEqual(leaks, [])
        self.assertNotIn(API_KEY, '\n'.join(self.log) + str(caught.exception))


class RefusalTests(ExportCase):
    def test_refuses_to_overwrite_a_complete_export(self):
        self.export()
        before, sent = all_files(self.out), len(self.fake.requests)

        for resume in (False, True):
            with self.subTest(resume=resume), self.assertRaises(OutDirRefused):
                self.export(resume=resume)

        self.assertEqual((all_files(self.out), len(self.fake.requests)), (before, sent))

    def test_refuses_a_folder_it_did_not_create(self):
        self.out.mkdir()
        (self.out / 'notes.txt').write_text('ملاحظات', encoding='utf-8')

        with self.assertRaises(OutDirRefused):
            self.export()

        self.assertEqual(all_files(self.out).keys(), {'notes.txt'})
        self.assertEqual(self.fake.requests, [])

    def test_accepts_an_existing_empty_folder(self):
        self.out.mkdir()

        self.export()

        self.assertTrue((self.out / 'manifest.json').is_file())

    def test_refuses_an_unfinished_export_without_resume(self):
        self.make_incomplete()

        with self.assertRaises(OutDirRefused):
            self.export()

    def test_refuses_to_resume_when_there_is_nothing_to_resume(self):
        with self.assertRaises(OutDirRefused):
            self.export(resume=True)

        self.assertFalse(self.out.exists())

    def test_refuses_a_folder_outside_a_quarantine_unless_told(self):
        elsewhere = self.root / 'elsewhere'
        elsewhere.mkdir()

        with self.assertRaises(OutDirRefused):
            self.export(out_dir=elsewhere / 'export')
        self.export(out_dir=elsewhere / 'export', allow_non_quarantine_out=True)

        self.assertTrue((elsewhere / 'export' / 'manifest.json').is_file())

    def test_refuses_when_the_parent_folder_is_missing(self):
        with self.assertRaises(OutDirRefused):
            self.export(out_dir=self.root / 'quarantine' / 'missing' / 'export')

        self.assertEqual([p.name for p in (self.root / 'quarantine').iterdir()], [])

    def test_refuses_a_quarantine_folder_inside_a_repository(self):
        repo = self.root / 'repo'
        (repo / '.git').mkdir(parents=True)
        (repo / 'quarantine').mkdir()

        with self.assertRaises(OutDirRefused):
            self.export(out_dir=repo / 'quarantine' / 'export')

        self.assertEqual(self.fake.requests, [])

    def test_refuses_an_out_folder_that_links_out_of_the_quarantine(self):
        target = self.root / 'elsewhere' / 'tracked'
        target.mkdir(parents=True)
        link_folder(self.out, target)

        with self.assertRaises(OutDirRefused):
            self.export()

        self.assertEqual(list(target.iterdir()), [])


class IdentifierCollisionTests(ExportCase):
    def test_document_ids_that_differ_only_in_letter_case_are_refused(self):
        # doc01lease is left without a done record, so on a case-insensitive disk nothing else would stop
        # DOC01LEASE from writing into the folder they share.
        self.fake.broken['/api/v1/datasets/ds01laws/documents/doc01lease/chunks'] = 500
        self.fake.data['documents']['ds01laws'].append({'id': 'DOC01LEASE', 'name': 'other.txt', 'run': 'DONE'})
        self.fake.data['blobs']['DOC01LEASE'] = b'another document'
        refresh_counts(self.fake.data)

        with self.assertRaises(IncompleteExport) as caught:
            self.export()

        self.assertEqual([f['document_id'] for f in caught.exception.failures], ['doc01lease', 'DOC01LEASE'])
        saved = (self.out / 'datasets/ds01laws/documents/doc01lease/original.txt').read_bytes()
        self.assertEqual(saved, self.fake.data['blobs']['doc01lease'])

    def test_dataset_ids_that_differ_only_in_letter_case_are_refused_before_anything_is_written(self):
        self.fake.data['datasets'].append({'id': 'DS01LAWS', 'name': 'نسخة', 'language': 'Arabic'})
        self.fake.data['documents']['DS01LAWS'] = []
        refresh_counts(self.fake.data)

        with self.assertRaises(UnsafeIdentifier):
            self.export()

        self.assertFalse(self.out.exists())

    def test_a_done_record_that_names_another_document_is_refused(self):
        broken = self.make_incomplete()
        edit_done_record(self.out / 'datasets/ds01laws/documents/doc01lease', document_id='doc99other')
        del self.fake.broken[broken]

        with self.assertRaises(IncompleteExport) as caught:
            self.export(resume=True)

        self.assertEqual([f['document_id'] for f in caught.exception.failures], ['doc01lease'])


class ResumeTests(ExportCase):
    def test_resumes_without_listing_or_downloading_finished_work_again(self):
        broken = self.make_incomplete()
        del self.fake.broken[broken]
        self.fake.requests.clear()

        self.export(resume=True)

        self.assertEqual([p for p in self.fake.paths() if DOWNLOAD.fullmatch(p)],
                         ['/api/v1/datasets/ds02clients/documents/doc03odd'])
        self.assertEqual([p for p in self.fake.paths() if LISTING.fullmatch(p)], [])
        self.assertEqual(self.manifest()['counts']['documents_exported'], 5)

    def test_resumes_after_an_interruption_mid_download(self):
        class Interrupting(RagflowClient):
            def download_document(self, dataset_id, document_id, dest):
                if document_id == 'doc04hostile':
                    dest.with_name(dest.name + exporter.TMP_SUFFIX).write_bytes(b'partial')
                    raise KeyboardInterrupt
                return super().download_document(dataset_id, document_id, dest)

        with self.assertRaises(KeyboardInterrupt):
            self.export(Interrupting(self.fake.base_url, API_KEY, sleep=self.sleeps.append))

        self.export(resume=True)

        entry = self.document_entry('doc04hostile')
        blob = self.fake.data['blobs']['doc04hostile']
        self.assertEqual((self.out / entry['original']['path']).read_bytes(), blob)
        self.assertEqual([p for p in self.out.rglob('*') if p.name.endswith(exporter.TMP_SUFFIX)], [])

    def test_downloads_again_a_finished_document_whose_file_no_longer_matches(self):
        broken = self.make_incomplete()
        original = self.out / 'datasets/ds01laws/documents/doc01lease/original.txt'
        original.write_bytes(original.read_bytes() + b'tampered')
        del self.fake.broken[broken]
        self.fake.requests.clear()

        self.export(resume=True)

        self.assertIn('/api/v1/datasets/ds01laws/documents/doc01lease', self.fake.paths())
        self.assertEqual(original.read_bytes(), self.fake.data['blobs']['doc01lease'])
        self.assertTrue(any(w.get('document_id') == 'doc01lease' for w in self.manifest()['warnings']))

    def test_does_not_trust_a_done_record_that_points_outside_its_folder(self):
        broken = self.make_incomplete()
        outside = self.root / 'outside.txt'
        outside.write_bytes(b'not part of the export')
        edit_done_record(self.out / 'datasets/ds01laws/documents/doc01lease',
                         original={'path': str(outside), 'sha256': hashlib.sha256(outside.read_bytes()).hexdigest()})
        del self.fake.broken[broken]

        self.export(resume=True)

        self.assertEqual(self.document_entry('doc01lease')['original']['path'],
                         'datasets/ds01laws/documents/doc01lease/original.txt')

    def test_refuses_to_resume_against_another_server_or_filter(self):
        self.make_incomplete()

        with FakeRagflow() as other, self.assertRaises(OutDirRefused):
            self.export(self.client(base_url=other.base_url), resume=True)
        with self.assertRaises(OutDirRefused):
            self.export(resume=True, dataset_filter=('ds01laws',))


class FilterTests(ExportCase):
    def test_selects_datasets_by_id_and_by_arabic_name(self):
        self.export(dataset_filter=('ds01laws', 'ملفات الموكلين (وهمية)'))

        manifest = self.manifest()
        self.assertEqual([d['id'] for d in manifest['datasets']], ['ds01laws', 'ds02clients'])
        self.assertEqual((manifest['counts']['datasets'], manifest['datasets_visible']), (2, 3))
        self.assertFalse((self.out / 'datasets' / 'ds03empty').exists())

    def test_a_name_matches_whatever_its_unicode_normal_form(self):
        decomposed = unicodedata.normalize('NFD', 'مكتبة القوانين التجريبية'.replace('ا', 'أ', 1))
        self.fake.data['datasets'][0]['name'] = unicodedata.normalize('NFC', decomposed)

        self.export(dataset_filter=(decomposed,))

        self.assertEqual([d['id'] for d in self.manifest()['datasets']], ['ds01laws'])

    def test_a_filter_that_matches_nothing_is_refused_and_writes_nothing(self):
        with self.assertRaises(FilterError):
            self.export(dataset_filter=('ds01laws', 'no-such-dataset'))

        self.assertFalse(self.out.exists())
        self.assertEqual(set(self.fake.paths()), {'/api/v1/datasets'})


class DryRunTests(ExportCase):
    def dry_run(self, **kwargs) -> str:
        stream = io.StringIO()
        exporter.dry_run(self.client(), self.options(**kwargs), out=stream)
        return stream.getvalue()

    def test_lists_without_downloading_or_writing(self):
        text = self.dry_run()

        self.assertFalse(self.out.exists())
        self.assertEqual([p for p in self.fake.paths() if not LISTING.fullmatch(p)], [])
        self.assertIn('doc05unparsed', text)
        self.assertIn('5 documents', text)
        self.assertIn('start a new export', text)

    def test_shows_names_only_when_asked(self):
        names = [d['name'] for d in self.fake.data['datasets']] + ['نموذج عقد إيجار.txt']

        hidden, shown = self.dry_run(), self.dry_run(show_names=True)

        self.assertEqual([n for n in names if n in hidden], [])
        self.assertEqual([n for n in names if n in shown], names)

    def test_applies_the_dataset_filter(self):
        text = self.dry_run(dataset_filter=('ds03empty',))

        self.assertNotIn('ds01laws', text)
        self.assertIn('0 documents', text)

    def test_says_when_a_real_run_would_refuse(self):
        self.export()

        self.assertIn('refuse', self.dry_run())


if __name__ == '__main__':
    unittest.main()
