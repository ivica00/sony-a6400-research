"""Constructed dependency and cache identity checks; no original firmware needed."""
import hashlib
import json
import unittest
import uuid

from project_paths import PROJECT_ROOT
from tools.research.dependency_plan import Planner, analyze_function
from tools.research.rea_evidence_cache import EvidenceCache
from test_storage_trace import module_fixture


class DependencyPlannerTests(unittest.TestCase):
    def setUp(self):
        self.root = PROJECT_ROOT / 'artifacts/tests/dependency-plan' / uuid.uuid4().hex
        self.target = 'firmware/fixture.ko'
        (self.root / 'firmware').mkdir(parents=True)
        self.raw = module_fixture()
        (self.root / self.target).write_bytes(self.raw)
        self.entries = [{'path': self.target, 'sha256': hashlib.sha256(self.raw).hexdigest()}]

    def planner(self):
        return Planner(self.root, self.entries, self.root / 'artifacts/cache')

    def test_original_call_relocation_and_data_literal_remain_distinct(self):
        result = analyze_function(self.raw, 'probe')
        self.assertEqual([(c['name'], c['local']) for c in result['calls']], [('external', False)])
        self.assertEqual(result['data_references'][0]['symbol_section'], '.rodata')
        self.assertEqual(result['data_references'][0]['string_candidate'], 'original-string')
        with self.assertRaisesRegex(ValueError, 'absent'):
            analyze_function(self.raw, 'missing')

    def test_cache_reuses_exact_input_and_rejects_corruption(self):
        first = self.planner()
        expected = first.node(self.target, 'probe')
        self.assertEqual(first.misses, 1)
        second = self.planner()
        self.assertEqual(second.node(self.target, 'probe'), expected)
        self.assertEqual(second.hits, 1)
        cache = next((self.root / 'artifacts/cache').rglob('*.json'))
        item = json.loads(cache.read_text())
        item['result']['calls'] = []
        cache.write_text(json.dumps(item))
        third = self.planner()
        self.assertEqual(third.node(self.target, 'probe'), expected)
        self.assertEqual((third.rejected, third.misses), (1, 1))

    def test_changed_input_is_not_hidden_by_cached_result(self):
        self.planner().node(self.target, 'probe')
        (self.root / self.target).write_bytes(self.raw + b'changed')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            self.planner().node(self.target, 'probe')

    def test_external_symbol_is_an_unresolved_provider_not_automatic_success(self):
        graph = self.planner().graph(self.target, ['probe'], cross_module=True)
        self.assertEqual(graph['nodes'][0]['calls'][0]['provider_candidates'], [])
        self.assertEqual(len(graph['nodes']), 1)
        with self.assertRaisesRegex(ValueError, 'limits'):
            self.planner().graph(self.target, ['probe'], depth=6)
        with self.assertRaisesRegex(ValueError, 'under artifacts'):
            Planner(self.root, self.entries, self.root / 'outside')


class RetainedEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.root = PROJECT_ROOT / 'artifacts/tests/rea-evidence' / uuid.uuid4().hex
        self.root.mkdir(parents=True)
        self.digest = 'a' * 64

    def batch(self, name='batch', profile='profile1', status='completed', subject=None, procedure='probe'):
        folder = self.root / name
        folder.mkdir()
        data = {'structuredContent': {'subject': {'digest': {'sha256': subject or self.digest}},
            'provider': {'id': 'ghidra', 'version': '12.1.4'}, 'analysis_profile': {'digest': profile},
            'operation': 'procedure_pseudo_code', 'parameters': {'procedure': procedure},
            'normalized_result': 'constructed'}}
        (folder / 'query.json').write_text(json.dumps(data))
        manifest = {'sha256': self.digest, 'source_sha256_after': self.digest,
            'source_unchanged': True, 'status': status,
            'queries': [{'file': 'query.json', 'procedure': 'probe', 'operation': 'procedure_pseudo_code'}]}
        (folder / 'manifest.json').write_text(json.dumps(manifest))
        return folder

    def lookup(self, cache):
        return cache.lookup(self.digest, 'procedure_pseudo_code', 'probe')

    def test_completed_exact_evidence_retains_original_provenance(self):
        folder = self.batch()
        hit = self.lookup(EvidenceCache(self.root))
        self.assertEqual(hit['source'], str(folder / 'query.json'))
        self.assertEqual(hit['analysis_profile'], 'profile1')

    def test_failed_wrong_subject_and_wrong_query_are_not_reused(self):
        self.batch('failed', status='failed')
        self.batch('other-subject', subject='b' * 64)
        self.batch('other-procedure', procedure='different')
        self.assertIsNone(self.lookup(EvidenceCache(self.root)))

    def test_incompatible_profiles_are_not_silently_interchanged(self):
        self.batch('first')
        self.batch('second', profile='profile2')
        self.assertIsNone(self.lookup(EvidenceCache(self.root)))

    def test_reference_escape_and_post_index_changes_are_rejected(self):
        folder = self.batch()
        cache = EvidenceCache(self.root)
        (folder / 'query.json').write_text('{}')
        self.assertIsNone(self.lookup(cache))
        manifest = json.loads((folder / 'manifest.json').read_text())
        manifest['queries'][0]['file'] = '../../outside.json'
        (folder / 'manifest.json').write_text(json.dumps(manifest))
        cache = EvidenceCache(self.root)
        self.assertIsNone(self.lookup(cache))
        self.assertEqual(len(cache.rejected), 1)


if __name__ == '__main__':
    unittest.main()
