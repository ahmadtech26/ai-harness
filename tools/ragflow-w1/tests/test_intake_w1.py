"""intake_w1.py: the contract check, the refusals, the quarantine copy and its manifest, the screening gate.

The fixture text is invented Arabic, not law text and not client data."""

import contextlib
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import intake_w1
import run_w1
from intake_w1 import Refused

MARKER = 'نصسريللاختبارفقط'  # a word that must never reach the terminal or a manifest
CONTENT = f'يلتزم المؤجر بتسليم العين المؤجرة للمستأجر {MARKER} في الموعد المتفق عليه'


def header(**changes) -> dict:
    value = {
        'w1': 1, 'script_sha256': 'a' * 64, 'queries_sha256': 'b' * 64,
        'started_at': '2026-11-08T08:00:00+00:00', 'finished_at': '2026-11-08T08:05:00+00:00',
        'ragflow_version': 'v0.27.3',
        'datasets': [{'id': 'f' * 32, 'document_count': 5, 'chunk_count': 900, 'embedding_model': 'bge-m3@Ollama',
                      'chunk_method': 'naive', 'parser_config': {'chunk_token_num': 512}}],
        'settings': {'page_size': 8, 'similarity_threshold': 0.2, 'vector_similarity_weight': 0.3, 'top_k': 1024},
        'fields': ['query', 'question'],
        'counts': {'items': 2, 'planned': 4, 'ok': 4, 'error': 0, 'not_run': 0},
    }
    value.update(changes)
    return value


def chunk(rank: int, content: str = CONTENT, **changes) -> dict:
    value = {'rank': rank, 'content': content, 'document_name': 'law.pdf', 'document_id': 'd' * 32,
             'chunk_id': 'c' * 16, 'similarity': 0.5, 'vector_similarity': 0.4, 'term_similarity': 0.6}
    value.update(changes)
    return value


def line(item_id: str = 'civil-code-01', field: str = 'query', sent: str = 'العربون', chunks=None, **changes) -> dict:
    value = {'id': item_id, 'field': field, 'sent': sent, 'status': 'ok', 'error': None,
             'chunks': [chunk(1), chunk(2)] if chunks is None else chunks}
    value.update(changes)
    return value


def default_lines() -> list:
    return [line('civil-code-01', 'query'), line('civil-code-02', 'query'),
            line('civil-code-01', 'question'), line('civil-code-02', 'question')]


def make_results(path: Path, head: dict | None = None, lines: list | None = None, raw_lines: list | None = None) -> Path:
    rows = raw_lines if raw_lines is not None else [json.dumps(head or header(), ensure_ascii=False)] + [
        json.dumps(row, ensure_ascii=False) for row in (default_lines() if lines is None else lines)]
    Path(path).write_bytes(('\n'.join(rows) + '\n').encode('utf-8'))
    return Path(path)


class Folder(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.root = self.tmp / 'quarantine' / 'ragflow-export'
        self.root.mkdir(parents=True)
        self.package = self.tmp / 'package'  # absent unless a test writes it
        self.file = self.tmp / 'inbox' / 'w1-results.jsonl'
        self.file.parent.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def fresh(self):
        """A new, empty quarantine and inbox inside one test."""
        self.tearDown()
        Folder.setUp(self)

    def intake(self, handover='test-1', client='no', **changes):
        return intake_w1.intake(self.file, handover, client, 'declared: own copy', 'test', '2026-11-08',
                                changes.get('root', self.root), self.package)

    def refused(self, pattern: str, **changes):
        with self.assertRaisesRegex(Refused, pattern) as caught:
            self.intake(**changes)
        self.assertNotIn(MARKER, str(caught.exception))
        self.assertEqual([], list(self.root.iterdir()), 'a refusal writes nothing')
        return caught.exception


class ContractTests(Folder):
    def test_a_valid_file_passes_and_counts_its_lines(self):
        results = intake_w1.read_results(make_results(self.file))
        self.assertEqual(4, len(results.lines))
        self.assertEqual({'query': {'lines': 2, 'ok': 2, 'error': 0, 'chunks': 4},
                          'question': {'lines': 2, 'ok': 2, 'error': 0, 'chunks': 4}},
                         intake_w1.summary(results)['per_field'])

    def test_the_header_must_come_first(self):
        make_results(self.file, raw_lines=[json.dumps(line()), json.dumps(header())])
        self.refused('header')

    def test_a_blank_line_before_the_header_is_refused(self):
        make_results(self.file, raw_lines=['', json.dumps(header())])
        self.refused('line 1')

    def test_missing_and_extra_header_keys_are_refused(self):
        head = header()
        del head['settings']
        make_results(self.file, head)
        self.refused('missing keys: settings')
        for key in ('base_url', 'host', 'name'):
            make_results(self.file, header(**{key: 'x'}))
            self.refused('keys outside the contract')

    def test_counts_hold_only_the_contract_s_whole_numbers(self):
        cases = [({'items': 2, 'planned': 4, 'ok': 4, 'error': 0, 'not_run': 0, 'ملاحظة': 1}, 'outside the contract'),
                 ({'items': 2, 'planned': 4, 'ok': 4, 'error': 0, 'not_run': 'قضية موكلي'}, 'whole number'),
                 ({'items': 2, 'planned': 4, 'ok': 4, 'error': 0}, 'missing keys: not_run')]
        for counts, pattern in cases:
            make_results(self.file, header(counts=counts))
            self.refused(pattern)

    def test_settings_hold_only_run_w1_s_names_and_value_types(self):
        cases = [({'page_size': 8, 'اسم المجموعة قضايا المكتب الخاصة': 1}, 'outside the contract'),
                 ({'page_size': 'قضايا المكتب'}, 'settings.page_size'),
                 ({'keyword': 1}, 'settings.keyword'),
                 ({'cross_languages': [1]}, 'settings.cross_languages')]
        for settings, pattern in cases:
            make_results(self.file, header(settings=settings))
            self.refused(pattern)

    def test_every_setting_run_w1_sends_is_accepted(self):
        args = run_w1.build_parser().parse_args(['--base-url', 'https://x', '--api-key-file', 'k',
                                                 '--rerank-id', 'bge-reranker-v2-m3@Ollama'])
        make_results(self.file, header(settings=run_w1.retrieval_settings(args)))

        self.assertEqual(set(run_w1.retrieval_settings(args)), intake_w1.SETTING_KEYS)
        self.intake()

    def test_an_ok_line_with_an_error_is_refused(self):
        make_results(self.file, lines=[line(error='HTTP 500')])

        self.refused('must not carry an error')

    def test_a_dataset_name_is_refused(self):
        head = header()
        head['datasets'][0]['name'] = 'قضايا موكلي'
        make_results(self.file, head)
        self.refused(r'datasets\[1\]: keys outside the contract: name')

    def test_an_unfinished_run_is_refused(self):
        make_results(self.file, header(finished_at=None))
        self.refused('did not finish')

    def test_a_null_version_needs_a_note(self):
        make_results(self.file, header(ragflow_version=None))
        self.refused('ragflow_version_note')
        make_results(self.file, header(ragflow_version=None, ragflow_version_note='the version request failed'))
        self.intake()

    def test_ranks_must_run_1_to_n_in_order(self):
        for ranks in ((2, 3), (1, 3), (2, 1)):
            make_results(self.file, lines=[line(chunks=[chunk(r) for r in ranks])])
            self.refused('ranks must be 1, 2, 3')

    def test_a_missing_chunk_key_is_refused(self):
        bad = chunk(1)
        del bad['term_similarity']
        make_results(self.file, lines=[line(chunks=[bad])])
        self.refused('missing keys: term_similarity')

    def test_a_second_line_for_the_same_field_and_id_is_refused(self):
        make_results(self.file, lines=[line(), line()])
        self.refused('same field and id')

    def test_a_field_the_header_does_not_list_is_refused(self):
        make_results(self.file, header(fields=['query']), lines=[line(field='question')])
        self.refused('header\'s fields')

    def test_an_error_line_carries_a_short_error_and_no_chunks(self):
        make_results(self.file, lines=[line(status='error', error='HTTP 500', chunks=[])])
        self.intake()
        self.fresh()
        make_results(self.file, lines=[line(status='error', error='HTTP 500')])
        self.refused('no chunks')
        make_results(self.file, lines=[line(status='error', error='x' * 501, chunks=[])])
        self.refused('short "error"')

    def test_an_id_that_is_not_an_eval_set_id_is_refused(self):
        make_results(self.file, lines=[line(item_id='../../x')])
        self.refused('eval-set id')

    def test_a_line_over_the_size_limit_is_refused(self):
        make_results(self.file)
        with mock.patch.object(intake_w1, 'MAX_LINE_BYTES', 200):
            self.refused('longer than')

    def test_text_that_is_not_utf8_or_not_json_is_refused(self):
        self.file.write_bytes(json.dumps(header()).encode() + b'\n{"id": "\xff"}\n')
        self.refused('not UTF-8')
        self.file.write_bytes(json.dumps(header()).encode() + b'\n{not json\n')
        self.refused('not JSON')


class ScreeningPatternTests(Folder):
    KEY = 'ragflow-' + 'Ab3dEf6hIj9kLm2nOp5qRs8tUv1wXy4zAb7cDe0fGh'

    def test_keys_and_auth_headers_are_refused_anywhere(self):
        cases = [
            (lines_with(chunk(1, content=f'{CONTENT} {self.KEY}')), 'RAGFlow API key'),
            (lines_with(chunk(1, document_name=self.KEY)), 'RAGFlow API key'),
            ([line(status='error', error='Bearer abcdefghijklmnop', chunks=[])], 'Bearer token'),
            ([line(status='error', error='bad Authorization header', chunks=[])], 'Authorization'),
        ]
        for lines, pattern in cases:
            make_results(self.file, lines=lines)
            error = self.refused(pattern)
            self.assertNotIn(self.KEY, str(error))
            self.assertNotIn('abcdefghijklmnop', str(error))
        make_results(self.file, header(settings={'page_size': 8, 'rerank_id': 'Bearer ' + self.KEY[8:]}))
        self.refused('Bearer token')

    def test_a_long_random_token_outside_document_names_is_refused(self):
        token = self.KEY[8:]  # a key without its prefix
        make_results(self.file, header(ragflow_version_note=token, ragflow_version=None))
        self.refused('random-looking token')
        make_results(self.file, lines=lines_with(chunk(1, document_name='Civil_Code_2019_FINAL_v3_Amended_text.pdf')))
        self.intake()  # a document name may look like that

    def test_a_long_token_in_chunk_text_is_counted_not_refused(self):
        # The front-matter line in Walid's criminal-procedure file, as a returned chunk would carry it.
        content = "source_review_file: 'IQRA_LAW_Criminal_Procedure_Articles_1-370_REVIEW.md'\nالمادة 1"
        make_results(self.file, lines=lines_with(chunk(1, content=content)))

        counts = self.intake()['pattern_counts']['content']

        self.assertEqual(1, counts['long_mixed_token'])

    def test_the_redacted_bearer_that_run_w1_writes_is_accepted(self):
        make_results(self.file, lines=[line(status='error', error='server said: Bearer [REDACTED] refused', chunks=[])])
        self.intake()

    def test_urls_and_addresses_are_refused(self):
        cases = [
            (header(), lines_with(chunk(1, content=f'{CONTENT} https://ragflow.example.org/x')), 'a URL'),
            (header(), [line(status='error', error='cannot reach localhost:9380', chunks=[])], 'localhost'),
            (header(ragflow_version_note='192.168.1.20:9380 failed', ragflow_version=None), None, 'IP address'),
            (header(), [line(status='error', error='connect 10.0.0.5 failed', chunks=[])], 'IP address'),
        ]
        for head, lines, pattern in cases:
            make_results(self.file, head, lines)
            self.refused(pattern)

    def test_an_ipv6_address_outside_chunk_text_is_refused(self):
        for error in ('cannot reach [fe80::1]:9380', 'connect ::1 failed', 'host 2001:db8:0:0:0:0:0:1 down'):
            make_results(self.file, lines=[line(status='error', error=error, chunks=[])])
            self.refused('IP address')

    def test_the_header_times_are_not_taken_for_ipv6_addresses(self):
        make_results(self.file, header(started_at='2026-11-08T08:00:00+00:00', finished_at='2026-11-08T09:10:11+03:00'))

        self.intake()

    def test_clause_numbers_in_chunk_text_are_not_taken_for_addresses(self):
        make_results(self.file, lines=lines_with(chunk(1, content=f'{CONTENT} البند 1.2.3.4 من الملحق')))
        self.intake()


def lines_with(first_chunk: dict) -> list:
    return [line(chunks=[first_chunk, chunk(2)])]


class QuarantineTests(Folder):
    def test_the_file_is_copied_with_its_manifest_and_nothing_of_its_text_is_printed(self):
        make_results(self.file)
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = intake_w1.main(['--file', str(self.file), '--handover-id', 'walid-2026-11-08',
                                   '--client-data-declared', 'no', '--received', '2026-11-08',
                                   '--quarantine-root', str(self.root), '--package', str(self.package)])
        self.assertEqual(0, code)
        folder = self.root / 'walid-2026-11-08'
        self.assertEqual(self.file.read_bytes(), (folder / 'w1-results.jsonl').read_bytes())
        manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(hashlib.sha256(self.file.read_bytes()).hexdigest(), manifest['files'][0]['sha256'])
        self.assertEqual('W1 evaluation evidence', manifest['declared_type'])
        self.assertEqual('no', manifest['client_data_declared'])
        self.assertEqual('2026-11-08', manifest['date_received'])
        self.assertIn('rights_status', manifest)
        self.assertIn('origin', manifest)
        self.assertEqual('pending', manifest['screening']['status'])
        self.assertIn('REQ-RAG-047', manifest['use'])
        self.assertNotIn(MARKER, out.getvalue())
        self.assertNotIn(MARKER, (folder / 'manifest.json').read_text(encoding='utf-8'))
        self.assertNotIn('يلتزم', out.getvalue())

    def test_pattern_counts_are_counts_only(self):
        make_results(self.file, lines=lines_with(chunk(1, content='المدعي والموكل ٠٧٩١٢٣٤٥٦٧ رقم 15/2020')))
        counts = self.intake()['pattern_counts']['content']
        self.assertEqual(1, counts['word_almuddai'])
        self.assertEqual(1, counts['word_almuwakkil'])
        self.assertEqual(1, counts['phone_number'])
        self.assertEqual(1, counts['case_number'])

    def test_document_names_and_errors_are_counted_on_their_own(self):
        make_results(self.file, lines=[
            line(chunks=[chunk(1, content='نص', document_name='مذكرة المدعي موكلي 0791234567.pdf')]),
            line('civil-code-02', status='error', error='المدعي 15/2020', chunks=[])])

        counts = self.intake()['pattern_counts']

        self.assertEqual((1, 1, 1), (counts['document_name']['word_almuddai'], counts['document_name']['word_muwakkili'],
                                     counts['document_name']['phone_number']))
        self.assertEqual((1, 1), (counts['error']['word_almuddai'], counts['error']['case_number']))
        self.assertEqual(0, sum(counts['content'].values()))

    def test_the_header_is_counted_on_its_own(self):
        make_results(self.file, header(ragflow_version=None, ragflow_version_note='طلب موكلي 0791234567'))

        counts = self.intake()['pattern_counts']['header']

        self.assertEqual((1, 1), (counts['word_muwakkili'], counts['phone_number']))

    def test_the_header_hashes_are_compared_with_the_package_we_sent(self):
        self.package.mkdir()
        (self.package / 'run_w1.py').write_bytes(b'print(1)\n')
        (self.package / 'w1-queries.jsonl').write_bytes(b'{}\n')
        make_results(self.file, header(script_sha256=hashlib.sha256(b'print(1)\n').hexdigest(),
                                       queries_sha256=hashlib.sha256(b'{}\n').hexdigest()))
        contract = self.intake()['contract']
        self.assertTrue(contract['script_matches_ours'])
        self.assertTrue(contract['queries_match_ours'])
        self.fresh()
        self.package.mkdir()
        (self.package / 'run_w1.py').write_bytes(b'print(2)\n')
        make_results(self.file)
        manifest = self.intake()
        self.assertFalse(manifest['contract']['script_matches_ours'])
        self.assertTrue(any('script_sha256 differs' in w for w in manifest['warnings']))

    def test_client_data_is_refused_and_the_declaration_is_required(self):
        make_results(self.file)
        self.refused('declared to hold client data', client='yes')
        self.refused('required', client=None)

    def test_an_existing_non_empty_folder_is_refused_and_an_empty_one_is_used(self):
        make_results(self.file)
        (self.root / 'test-1').mkdir()
        self.intake()
        with self.assertRaisesRegex(Refused, 'not an empty folder'):
            self.intake()

    def test_the_folder_must_be_a_quarantine_outside_every_repository(self):
        make_results(self.file)
        elsewhere = self.tmp / 'elsewhere'
        elsewhere.mkdir()
        with self.assertRaisesRegex(Refused, 'not inside a folder named "quarantine"'):
            self.intake(root=elsewhere)
        repo_root = self.tmp / 'repo' / 'quarantine'
        repo_root.mkdir(parents=True)
        (self.tmp / 'repo' / '.git').mkdir()
        with self.assertRaisesRegex(Refused, 'inside the repository'):
            self.intake(root=repo_root)

    def test_a_link_named_quarantine_to_another_folder_is_refused(self):
        make_results(self.file)
        elsewhere = self.tmp / 'elsewhere'
        elsewhere.mkdir()
        (self.tmp / 'links').mkdir()
        link = link_folder(elsewhere, self.tmp / 'links' / 'quarantine')

        with self.assertRaisesRegex(Refused, 'not inside a folder named "quarantine"'):
            self.intake(root=link)

    def test_a_bad_handover_id_is_refused(self):
        make_results(self.file)
        for handover in ('Bad_Slug', '../x', 'con', '', 'a' * 65, '-x'):
            with self.assertRaisesRegex(Refused, 'handover-id'):
                self.intake(handover=handover)


class ScreeningGateTests(Folder):
    def setUp(self):
        super().setUp()
        make_results(self.file)
        self.intake()
        self.stored = self.root / 'test-1' / 'w1-results.jsonl'

    def test_a_pending_screen_blocks_scoring(self):
        with self.assertRaisesRegex(Refused, '"pending", not "clear"'):
            intake_w1.check_cleared(self.stored)

    def test_a_clear_screen_lets_it_be_scored(self):
        intake_w1.record_screening('test-1', 'the owner', 'clear', self.root, on='2026-11-08')
        manifest = intake_w1.check_cleared(self.stored)
        self.assertEqual({'status': 'clear', 'by': 'the owner', 'on': '2026-11-08'},
                         {k: manifest['screening'][k] for k in ('status', 'by', 'on')})

    def test_a_flagged_screen_blocks_scoring(self):
        intake_w1.record_screening('test-1', 'the lawyer', 'flagged', self.root)
        with self.assertRaisesRegex(Refused, '"flagged"'):
            intake_w1.check_cleared(self.stored)

    def test_a_flagged_screen_cannot_be_recorded_clear_afterwards(self):
        intake_w1.record_screening('test-1', 'the lawyer', 'flagged', self.root)

        with self.assertRaisesRegex(Refused, 'already recorded as "flagged"'):
            intake_w1.record_screening('test-1', 'someone', 'clear', self.root)
        with self.assertRaisesRegex(Refused, '"flagged"'):
            intake_w1.check_cleared(self.stored)

    def test_each_screen_is_kept_in_the_history(self):
        intake_w1.record_screening('test-1', 'the owner', 'clear', self.root, on='2026-11-08')
        intake_w1.record_screening('test-1', 'the lawyer', 'flagged', self.root, on='2026-11-09')

        manifest = intake_w1.load_manifest(self.root / 'test-1')

        self.assertEqual([('clear', 'the owner'), ('flagged', 'the lawyer')],
                         [(row['status'], row['by']) for row in manifest['screening_history']])

    def test_a_cleared_pair_copied_out_of_quarantine_is_not_scored(self):
        intake_w1.record_screening('test-1', 'the owner', 'clear', self.root)
        outside = self.tmp / 'not-a-q' / 'test-1'
        outside.mkdir(parents=True)
        for name in ('w1-results.jsonl', 'manifest.json'):
            shutil.copy(self.root / 'test-1' / name, outside / name)

        with self.assertRaisesRegex(Refused, 'not inside a folder named "quarantine"'):
            intake_w1.check_cleared(outside / 'w1-results.jsonl')

    def test_a_manifest_that_no_longer_records_the_client_data_flag_as_no_blocks_scoring(self):
        intake_w1.record_screening('test-1', 'the owner', 'clear', self.root)
        path = self.root / 'test-1' / 'manifest.json'
        manifest = json.loads(path.read_text(encoding='utf-8'))
        manifest['client_data_declared'] = 'yes'
        path.write_text(json.dumps(manifest), encoding='utf-8')

        with self.assertRaisesRegex(Refused, 'client-data flag'):
            intake_w1.check_cleared(self.stored)

    def test_a_changed_file_blocks_scoring(self):
        intake_w1.record_screening('test-1', 'the owner', 'clear', self.root)
        self.stored.write_bytes(self.stored.read_bytes() + b'\n')
        with self.assertRaisesRegex(Refused, 'no longer matches'):
            intake_w1.check_cleared(self.stored)

    def test_only_the_quarantined_copy_is_scored(self):
        intake_w1.record_screening('test-1', 'the owner', 'clear', self.root)
        with self.assertRaisesRegex(Refused, 'quarantined copy'):
            intake_w1.check_cleared(self.file.with_name('other.jsonl'))


def link_folder(target: Path, link: Path) -> Path:
    """A link to a folder: a symbolic link, or on Windows without that privilege a junction (no privilege needed;
    os.path.realpath resolves both)."""
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError:
        import _winapi  # Windows only; reached only where a symbolic link needs a privilege
        _winapi.CreateJunction(str(target), str(link))
    return link


if __name__ == '__main__':
    unittest.main()
