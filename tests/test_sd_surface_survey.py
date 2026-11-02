"""Constructed card trees verify bounded read-only acquisition behavior."""
import hashlib
from pathlib import Path
import unittest
import uuid

from project_paths import PROJECT_ROOT
from tools.research.sd_surface_survey import card_inventory


class SdSurfaceSurveyTests(unittest.TestCase):
    def tree(self):
        root = PROJECT_ROOT / 'artifacts/tests' / ('sd-survey-' + uuid.uuid4().hex)
        (root / 'DCIM').mkdir(parents=True)
        return root

    def test_media_only_has_prefix_identity_and_is_unchanged(self):
        root = self.tree()
        raw = bytes(range(256)) * 3
        path = root / 'DCIM/fixture.ARW'
        path.write_bytes(raw)
        report = card_inventory(root)
        record = report['files'][0]
        self.assertEqual(record['prefix64_sha256'], hashlib.sha256(raw[:64]).hexdigest())
        self.assertIsNone(record['sha256'])
        self.assertEqual(path.read_bytes(), raw)

    def test_metadata_has_full_identity_and_unknown_root_trees_are_skipped(self):
        root = self.tree()
        (root / 'AVF_INFO').mkdir()
        raw = b'constructed index' * 20
        (root / 'AVF_INFO/fixture.BNP').write_bytes(raw)
        (root / 'System Volume Information').mkdir()
        (root / 'System Volume Information/private.bin').write_bytes(b'excluded')
        result = card_inventory(root)
        self.assertEqual(len(result['files']), 1)
        self.assertEqual(result['files'][0]['sha256'], hashlib.sha256(raw).hexdigest())
        self.assertEqual(result['skipped'][0]['reason'], 'outside declared camera trees')

    def test_large_metadata_is_not_fully_acquired(self):
        root = self.tree()
        path = root / 'DCIM/large.BIN'
        with path.open('wb') as stream:
            stream.seek(8 * 1024 * 1024)
            stream.write(b'x')
        record = card_inventory(root)['files'][0]
        self.assertIsNone(record['sha256'])
        self.assertEqual(len(record['prefix64_hex']), 128)
