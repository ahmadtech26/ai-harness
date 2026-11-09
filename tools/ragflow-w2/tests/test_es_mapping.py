"""Tests for patch_es_mapping.py on invented fixtures and, when present, the v0.27.3 source tree copy of
conf/mapping.json (byte for byte the pinned image's, README.md «Hosted run», H1).

Run from tools/ragflow-w2:  python -B -X utf8 -m unittest discover -s tests -t .
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

TOOL_DIR = Path(__file__).resolve().parents[1]
WORKSPACE = TOOL_DIR.parents[2]
REAL_SOURCE = WORKSPACE / '.hq' / 'scratch' / 'ragflow-src-v0.27.3' / 'x' / 'conf' / 'mapping.json'
REAL_SHA256 = '49877a9153c466479ce75a81e5da49e952567ca9c3cb1d46e2b20c2a6bab8097'  # the image's file, copied out of it

_spec = importlib.util.spec_from_file_location('patch_es_mapping', TOOL_DIR / 'patch_es_mapping.py')
tool = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(tool)

WANTED = {'type': 'dense_vector', 'index': True, 'similarity': 'cosine', 'dims': 4096}


def vec(dims: int) -> dict:
    return {'dense_vector': {'match': f'*_{dims}_vec', 'mapping': {'type': 'dense_vector', 'index': True,
                                                                  'similarity': 'cosine', 'dims': dims}}}


def doc(templates: list | None = None, properties: dict | None = None) -> dict:
    """A small mapping shaped like v0.27.3's: settings, one property, and dynamic templates ending in the vectors and
    *_bin. json.dumps(indent=2) of it is formatted as the real file is (the real file is exactly that dump)."""
    if templates is None:
        templates = [{'int': {'match': '*_int', 'mapping': {'type': 'integer', 'store': 'true'}}},
                     {'kwd': {'match_pattern': 'regex', 'match': '^(.*_(kwd|id|ids|uid|uids)|uid|id)$',
                              'mapping': {'type': 'keyword', 'similarity': 'boolean', 'store': True}}},
                     vec(1024), vec(1536),
                     {'binary': {'match': '*_bin', 'mapping': {'type': 'binary'}}}]
    return {'settings': {'index': {'number_of_shards': 2, 'number_of_replicas': 0, 'refresh_interval': '1000ms'}},
            'mappings': {'properties': properties if properties is not None else
                         {'lat_lon': {'type': 'geo_point', 'store': 'true'}},
                         'date_detection': 'true', 'dynamic_templates': templates}}


# Templates takes() cannot read (Elasticsearch 8.9 and later accept a list for match; a regex may not compile): each
# counts as one that would take the field, the tool's cautious default, rather than a traceback.
UNREADABLE_MATCH = {'a list of patterns': {'lst': {'match': ['*_x'], 'mapping': {'type': 'float'}}},
                    'a regex that does not compile': {'bad': {'match_pattern': 'regex', 'match': '(q_4096_vec',
                                                              'mapping': {'type': 'float'}}}}


def dump(document: dict) -> str:
    return json.dumps(document, indent=2) + '\n'


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src = self.dir / 'src' / 'mapping.json'
        self.src.parent.mkdir()
        self.out = self.dir / 'es-mapping'

    def tearDown(self):
        self.tmp.cleanup()

    def put(self, data: bytes | str) -> bytes:
        data = data.encode('utf-8') if isinstance(data, str) else data
        self.src.write_bytes(data)
        return data

    def run_tool(self, *argv) -> tuple[int, str]:
        out = io.StringIO()
        code = tool.main([str(a) for a in argv], stdout=out)
        return code, out.getvalue()

    def write(self, *extra) -> tuple[int, str]:
        return self.run_tool('write', '--source', self.src, '--out', self.out, *extra)

    def written(self) -> list[str]:
        return sorted(p.name for p in self.out.iterdir()) if self.out.is_dir() else []


class Fixture(Base):
    """The tool's rules on an invented file; its pinned source sha256 is made the fixture's for each test."""

    def put_pinned(self, data: bytes | str):
        data = self.put(data)
        patcher = mock.patch.object(tool, 'SOURCE_SHA256', sha(data))
        patcher.start()
        self.addCleanup(patcher.stop)
        return data

    def test_one_template_is_added_right_after_the_1536_one_and_nothing_else_changes(self):
        original = self.put_pinned(dump(doc()))

        code, out = self.write()

        self.assertEqual(0, code, out)
        self.assertEqual(['mapping-patch.json', 'mapping.diff', 'mapping.json'], self.written())
        patched = (self.out / 'mapping.json').read_bytes()
        expected = doc()
        expected['mappings']['dynamic_templates'].insert(4, vec(4096))
        self.assertEqual(dump(expected).encode('utf-8'), patched)  # the same formatting as the source
        self.assertEqual(json.loads(original)['settings'], json.loads(patched)['settings'])
        self.assertEqual(WANTED, json.loads(patched)['mappings']['dynamic_templates'][4]['dense_vector']['mapping'])
        self.assertEqual(0, patched.count(b'\r'))

    def test_the_inserted_block_is_the_1536_block_with_two_numbers_changed(self):
        original = self.put_pinned(dump(doc())).decode('utf-8').split('\n')

        code, out = self.write()

        self.assertEqual(0, code, out)
        patched = (self.out / 'mapping.json').read_text(encoding='utf-8').split('\n')
        first = original.index('          "match": "*_1536_vec",') - 2
        block = original[first:first + 11]
        self.assertEqual(['      {', '      },'], [block[0], block[-1]])
        self.assertEqual(original[:first + 11] + original[first + 11:], patched[:first + 11] + patched[first + 22:])
        self.assertEqual([line.replace('1536', '4096') for line in block], patched[first + 11:first + 22])

    def test_the_record_and_the_diff(self):
        original = self.put_pinned(dump(doc()))

        code, out = self.write()

        self.assertEqual(0, code, out)
        record = json.loads((self.out / 'mapping-patch.json').read_text(encoding='utf-8'))
        patched = (self.out / 'mapping.json').read_bytes()
        first = original.decode('utf-8').split('\n').index('          "match": "*_1536_vec",') - 2 + 11 + 1
        self.assertEqual({'file': 'conf/mapping.json', 'source_sha256': sha(original), 'patched_sha256': sha(patched),
                          'inserted_lines': [first, first + 10], 'after_template': '*_1536_vec',
                          'template': vec(4096), 'field': 'q_4096_vec'}, record)
        diff = (self.out / 'mapping.diff').read_text(encoding='utf-8').split('\n')
        self.assertEqual(['--- a/conf/mapping.json', '+++ b/conf/mapping.json'], diff[:2])
        body = [line for line in diff[2:] if line and not line.startswith('@@')]
        self.assertEqual([], [line for line in body if line.startswith('-')])
        added = [line[1:] for line in body if line.startswith('+')]
        self.assertEqual(patched.decode('utf-8').split('\n')[first - 1:first + 10], added)
        self.assertIn('q_4096_vec', out)
        self.assertIn(sha(patched), out)

    def test_a_source_other_than_the_pinned_one_is_refused(self):
        self.put(dump(doc()))  # SOURCE_SHA256 stays v0.27.3's

        code, out = self.write()

        self.assertEqual(2, code, out)
        self.assertTrue(out.startswith('refused: '), out)
        self.assertIn(REAL_SHA256, out)
        self.assertEqual([], self.written())

    def test_cr_bytes_and_non_utf8_are_refused(self):
        for data, why in ((dump(doc()).replace('\n', '\r\n').encode('utf-8'), 'CR byte'),
                          (dump(doc()).encode('utf-8') + b'\xff\n', 'not UTF-8')):
            with self.subTest(why=why):
                self.put_pinned(data)
                code, out = self.write()
                self.assertEqual(2, code, out)
                self.assertTrue(out.startswith('refused: '), out)
                self.assertIn(why, out)
                self.assertEqual([], self.written())

    def test_the_second_pass_passes_the_one_block_after_1536(self):
        original = dump(doc())
        lines = original.split('\n')
        at = tool.locate(lines)

        tool.verify(original, '\n'.join(lines[:at] + list(tool.BLOCK) + lines[at:]), at)  # no Refused

    def test_the_second_pass_text_layer_refuses_a_change_the_json_does_not_show(self):
        original = dump(doc())
        lines = original.split('\n')
        at = tool.locate(lines)
        self.assertEqual('    ]', lines[-4])  # the templates' closing bracket, then '  }', '}' and the final ''
        wrong = {'a space after a bracket': lines[:at] + list(tool.BLOCK) + lines[at:-4] + ['    ]  '] + lines[-3:],
                 'a blank line after the block': lines[:at] + list(tool.BLOCK) + [''] + lines[at:]}

        for name, patched in wrong.items():
            with self.subTest(name=name):
                right = '\n'.join(lines[:at] + list(tool.BLOCK) + lines[at:])
                self.assertEqual(json.loads(right), json.loads('\n'.join(patched)))  # the JSON layer cannot see it
                with self.assertRaisesRegex(tool.Refused, 'block inserted at line'):
                    tool.verify(original, '\n'.join(patched), at)

    def test_the_second_pass_json_layer_refuses_a_block_in_the_wrong_place(self):
        original = dump(doc())
        lines = original.split('\n')
        early = tool.locate(lines) - 11  # before the *_1536_vec block: the text is consistent with that line

        with self.assertRaisesRegex(tool.Refused, 'parsed result'):
            tool.verify(original, '\n'.join(lines[:early] + list(tool.BLOCK) + lines[early:]), early)

    def test_a_source_without_the_1536_template_or_with_two_is_refused(self):
        plain = doc()['mappings']['dynamic_templates']
        for templates, found in (([t for t in plain if t != vec(1536)], 0), (plain[:4] + [vec(1536)] + plain[4:], 2)):
            with self.subTest(found=found):
                self.put_pinned(dump(doc(templates)))
                code, out = self.write()
                self.assertEqual(2, code, out)
                self.assertIn(f'the *_1536_vec block (its exact v0.27.3 lines) is found {found} time(s)', out)
                self.assertEqual([], self.written())

    def test_a_source_that_already_names_4096_is_refused(self):
        plain = doc()['mappings']['dynamic_templates']
        self.put_pinned(dump(doc(plain[:4] + [vec(4096)] + plain[4:])))

        code, out = self.write()

        self.assertEqual(2, code, out)
        self.assertIn('the source already names *_4096_vec', out)
        self.assertEqual([], self.written())

    def test_an_earlier_template_that_would_take_q_4096_vec_is_refused(self):
        plain = doc()['mappings']['dynamic_templates']
        for earlier in ({'flt': {'match': '*_vec', 'mapping': {'type': 'float'}}},
                        {'any': {'match_pattern': 'regex', 'match': '^q_.*$', 'mapping': {'type': 'float'}}},
                        {'typed': {'match_mapping_type': 'double', 'mapping': {'type': 'float'}}}):
            with self.subTest(earlier=earlier):
                self.put_pinned(dump(doc(plain[:1] + [earlier] + plain[1:])))
                code, out = self.write()
                self.assertEqual(2, code, out)
                self.assertIn('q_4096_vec', out)
                self.assertEqual([], self.written())

    def test_a_list_match_or_a_broken_regex_is_refused_not_a_crash(self):
        plain = doc()['mappings']['dynamic_templates']
        for name, earlier in UNREADABLE_MATCH.items():
            with self.subTest(name=name):
                self.put_pinned(dump(doc(plain[:1] + [earlier] + plain[1:])))
                code, out = self.write()
                self.assertEqual(2, code, out)
                self.assertIn('refused: the first template that would take q_4096_vec is', out)
                self.assertEqual([], self.written())

    def test_a_copy_that_reads_back_with_other_bytes_is_removed_and_refused(self):
        self.put_pinned(dump(doc()))
        real = Path.write_bytes

        def corrupting(path, data):
            return real(path, data + b' ' if path.name == 'mapping.json' else data)

        with mock.patch.object(Path, 'write_bytes', corrupting):
            code, out = self.write()

        self.assertEqual(2, code, out)
        self.assertIn('the written mapping.json reads back with another sha256', out)
        self.assertEqual([], self.written())

    def test_a_symlink_in_out_is_foreign_even_with_replace(self):
        # A real symlink needs a privilege on Windows, so the check the tool makes, is_symlink(), is answered here.
        self.put_pinned(dump(doc()))
        self.assertEqual(0, self.write()[0])
        real = Path.is_symlink

        with mock.patch.object(Path, 'is_symlink', lambda path: path.name == 'mapping.json' or real(path)):
            code, out = self.write('--replace')

        self.assertEqual(2, code, out)
        self.assertIn('--out holds entries this tool does not write, left alone: mapping.json', out)

    def test_a_property_named_q_4096_vec_is_refused(self):
        self.put_pinned(dump(doc(properties={'q_4096_vec': {'type': 'float'}})))

        code, out = self.write()

        self.assertEqual(2, code, out)
        self.assertIn('q_4096_vec', out)

    def test_the_out_folder_rules(self):
        self.put_pinned(dump(doc()))
        self.assertEqual(0, self.write()[0])
        first = (self.out / 'mapping.json').read_bytes()

        code, out = self.write()  # not empty, no --replace
        self.assertEqual(2, code, out)

        code, out = self.write('--replace')
        self.assertEqual(0, code, out)
        self.assertEqual(first, (self.out / 'mapping.json').read_bytes())

        (self.out / 'notes.txt').write_text('mine', encoding='utf-8')
        code, out = self.write('--replace')  # a foreign entry, even with --replace
        self.assertEqual(2, code, out)
        self.assertTrue((self.out / 'notes.txt').exists())

        code, out = self.run_tool('write', '--source', self.src, '--out', self.src.parent, '--replace')
        self.assertEqual(2, code, out)  # --source inside --out
        code, out = self.run_tool('write', '--source', self.src, '--out', self.src)
        self.assertEqual(2, code, out)  # --out is a file


class Check(Base):
    def check(self, path: Path) -> tuple[int, str]:
        return self.run_tool('check', '--copy', path)

    def approved(self, data: bytes):
        patcher = mock.patch.object(tool, 'PATCHED_SHA256', sha(data))
        patcher.start()
        self.addCleanup(patcher.stop)

    def copy_of(self, document: dict) -> Path:
        path = self.dir / 'copy.json'
        path.write_text(dump(document), encoding='utf-8')
        return path

    def patched_doc(self) -> dict:
        document = doc()
        document['mappings']['dynamic_templates'].insert(4, vec(4096))
        return document

    def test_the_approved_copy_passes(self):
        path = self.copy_of(self.patched_doc())
        self.approved(path.read_bytes())

        code, out = self.check(path)

        self.assertEqual(0, code, out)
        self.assertTrue(out.rstrip('\n').split('\n')[-1].startswith('ES MAPPING OK: '), out)
        self.assertNotIn('BAD', out)

    def test_another_sha256_fails_even_when_the_template_is_right(self):
        path = self.copy_of(self.patched_doc())  # PATCHED_SHA256 stays the real one

        code, out = self.check(path)

        self.assertEqual(1, code, out)
        self.assertIn('BAD  sha256', out)
        self.assertIn('ES MAPPING NOT APPROVED', out)

    def test_a_wrong_template_fails_even_with_the_approved_sha256(self):
        cases = {'dims': ('dims', 4095), 'similarity': ('similarity', 'dot_product'), 'index': ('index', False),
                 'type': ('type', 'float'), 'extra option': ('index_options', {'type': 'hnsw'})}
        for name, (key, value) in cases.items():
            with self.subTest(name=name):
                document = self.patched_doc()
                document['mappings']['dynamic_templates'][4]['dense_vector']['mapping'][key] = value
                path = self.copy_of(document)
                self.approved(path.read_bytes())
                code, out = self.check(path)
                self.assertEqual(1, code, out)
                self.assertIn('BAD  template', out)

    def test_a_missing_misplaced_doubled_or_shadowed_template_fails(self):
        plain = doc()['mappings']['dynamic_templates']
        shadow = {'flt': {'match': '*_vec', 'mapping': {'type': 'float'}}}
        unjudgeable = {'odd': {'match_pattern': 'glob', 'match': 'nothing', 'mapping': {'type': 'float'}}}
        cases = {'missing': plain,
                 'after *_bin': plain + [vec(4096)],
                 'twice': plain[:4] + [vec(4096), vec(4096)] + plain[4:],
                 '*_1536_vec twice, the second right before': plain[:4] + [vec(1536), vec(4096)] + plain[4:],
                 'shadowed': plain[:1] + [shadow] + plain[1:4] + [vec(4096)] + plain[4:],
                 'after a template it cannot judge': plain[:1] + [unjudgeable] + plain[1:4] + [vec(4096)] + plain[4:]}
        for name, templates in cases.items():
            with self.subTest(name=name):
                path = self.copy_of(doc(templates))
                self.approved(path.read_bytes())
                code, out = self.check(path)
                self.assertEqual(1, code, out)
                self.assertIn('BAD  ', out)

    def test_earlier_templates_that_do_not_take_the_field_leave_the_copy_approved(self):
        # Elasticsearch matches the whole field name: a simple pattern by its * wildcards only (a dot is a dot), a
        # regex from its first character to its last. None of these takes q_4096_vec.
        plain = doc()['mappings']['dynamic_templates']
        earlier = [{'part': {'match': 'q_4096', 'mapping': {'type': 'float'}}},
                   {'tail': {'match': '4096_vec', 'mapping': {'type': 'float'}}},
                   {'dots': {'match': 'q.4096.vec', 'mapping': {'type': 'float'}}},
                   {'re_part': {'match_pattern': 'regex', 'match': 'q_4096', 'mapping': {'type': 'float'}}},
                   {'re_tail': {'match_pattern': 'regex', 'match': '_4096_vec', 'mapping': {'type': 'float'}}}]
        path = self.copy_of(doc(plain[:1] + earlier + plain[1:4] + [vec(4096)] + plain[4:]))
        self.approved(path.read_bytes())

        code, out = self.check(path)

        self.assertEqual(0, code, out)
        self.assertNotIn('BAD', out)

    def test_a_list_match_or_a_broken_regex_fails_as_a_template_that_would_take_the_field(self):
        plain = doc()['mappings']['dynamic_templates']
        for name, earlier in UNREADABLE_MATCH.items():
            with self.subTest(name=name):
                path = self.copy_of(doc(plain[:1] + [earlier] + plain[1:4] + [vec(4096)] + plain[4:]))
                self.approved(path.read_bytes())
                code, out = self.check(path)
                self.assertEqual(1, code, out)
                self.assertIn('BAD  template *_4096_vec: the first template that would take q_4096_vec is', out)
                self.assertTrue(out.splitlines()[-1].startswith('ES MAPPING NOT APPROVED: '), out)

    def test_a_copy_that_is_not_json_fails_and_a_missing_one_is_refused(self):
        path = self.dir / 'copy.json'
        path.write_bytes(b'{"settings": \n')
        self.approved(path.read_bytes())
        code, out = self.check(path)
        self.assertEqual(1, code, out)
        self.assertIn('BAD  ', out)

        code, out = self.check(self.dir / 'absent.json')
        self.assertEqual(2, code, out)
        self.assertTrue(out.startswith('refused: '), out)


@unittest.skipUnless(REAL_SOURCE.is_file(), 'the v0.27.3 source tree copy is not here')
class RealSource(Base):
    def test_the_pinned_source_is_the_tree_copy(self):
        self.assertEqual(REAL_SHA256, tool.SOURCE_SHA256)
        self.assertEqual(REAL_SHA256, sha(REAL_SOURCE.read_bytes()))

    def test_the_tree_copy_gives_the_approved_copy_which_check_passes(self):
        original = self.put(REAL_SOURCE.read_bytes())

        code, out = self.write()

        self.assertEqual(0, code, out)
        patched = (self.out / 'mapping.json').read_bytes()
        self.assertEqual(tool.PATCHED_SHA256, sha(patched))
        self.assertEqual(len(original) + len(b''.join(line + b'\n' for line in patched.split(b'\n')[203:214])),
                         len(patched))
        templates = json.loads(patched)['mappings']['dynamic_templates']
        before = json.loads(original)['mappings']['dynamic_templates']
        self.assertEqual(len(before) + 1, len(templates))
        self.assertEqual('*_1536_vec', templates[17]['dense_vector']['match'])
        self.assertEqual(vec(4096), templates[18])
        self.assertEqual(before, templates[:18] + templates[19:])
        expected = copy.deepcopy(before[17])
        expected['dense_vector']['match'], expected['dense_vector']['mapping']['dims'] = '*_4096_vec', 4096
        self.assertEqual(expected, templates[18])  # the same options as the existing templates
        record = json.loads((self.out / 'mapping-patch.json').read_text(encoding='utf-8'))
        self.assertEqual([204, 214], record['inserted_lines'])
        diff = (self.out / 'mapping.diff').read_text(encoding='utf-8').split('\n')
        self.assertEqual('@@ -201,6 +201,17 @@', diff[2])  # three lines of context either side, 11 added

        code, out = self.run_tool('check', '--copy', self.out / 'mapping.json')
        self.assertEqual(0, code, out)

    def test_check_fails_the_shipped_file(self):
        code, out = self.run_tool('check', '--copy', REAL_SOURCE)

        self.assertEqual(1, code, out)
        self.assertIn('BAD  template', out)


if __name__ == '__main__':
    unittest.main()
