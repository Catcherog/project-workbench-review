"""Temporary fixtures only: no fabricated approval enters real training data."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

from am_style_r5.common import R5Error, read_json, seal, write_json
from am_style_r5.dataset import (freeze_group_registry, build_review_batch, feedback_template,
    import_feedback_file, export_gold_snapshot, verify_gold_snapshot)
from am_style_r5.scenarios import calibration_specs

ROOT = Path(__file__).resolve().parents[1]
BASE = {'baseline_train': ROOT / 'baseline/data/r4-gold/sft.train.jsonl',
        'baseline_dev': ROOT / 'baseline/data/r4-gold/sft.dev.jsonl'}

class RegistryJoinTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='r5-join-unit-fixture-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        specs = calibration_specs()
        self.a, self.b = specs[0], specs[3]
        self.master = freeze_group_registry([self.a, self.b], **BASE)
        self.imports = []
        for n, spec in enumerate((self.a, self.b)):
            registry = freeze_group_registry([spec], **BASE)
            batch = build_review_batch([spec], registry, version=f'UNIT-TEST-ONLY-{n}')
            feedback = feedback_template(batch)
            feedback.update(origin='human', reviewer='SYNTHETIC_UNIT_FIXTURE_NOT_REAL',
                            reviewed_at='2026-11-02T00:00:00+08:00')
            row = feedback['ratings'][0]
            row.update(status='reviewed', accepted_candidate='proposed_revision')
            row['assessments']['proposed_revision'].update(facts_pass=True, style_pass=True, acceptable=True)
            path = self.root / f'fixture-feedback-{n}.json'
            write_json(path, feedback)
            self.imports.append(import_feedback_file(batch, path))

    def export(self, registry=None, imports=None, join=True, name='out'):
        return export_gold_snapshot(registry or self.master, imports or self.imports,
            **BASE, output_dir=self.root / name, join_reviewed_registries=join)

    def test_explicit_join_preserves_original_reviews_and_roundtrips(self):
        originals = deepcopy(self.imports)
        snapshot = self.export()
        self.assertEqual(snapshot['counts']['train'], 11)
        self.assertEqual(snapshot['counts']['dev'], 1)
        self.assertEqual(self.imports, originals)
        self.assertEqual(verify_gold_snapshot(self.root / 'out/snapshot.json'), snapshot)
        for split in ('train', 'dev'):
            self.assertTrue((self.root / 'out' / f'sft.{split}.jsonl').read_bytes().startswith(BASE[f'baseline_{split}'].read_bytes()))

    def test_default_rejects_mixed_registries(self):
        with self.assertRaisesRegex(R5Error, 'different frozen registries'):
            self.export(join=False)

    def test_any_accepted_context_or_split_change_is_rejected(self):
        for field in ('frame_sha256', 'prompt_sha256', 'policy_sha256', 'split', 'group_id'):
            registry = deepcopy(self.master)
            registry['scenarios'][self.a['id']][field] = '0' * 64 if field.endswith('sha256') else 'dev' if field == 'split' else 'another-group'
            registry = seal(registry)
            with self.subTest(field=field), self.assertRaises((ValueError, KeyError)):
                self.export(registry=registry, name=field)

    def test_changed_original_feedback_is_not_reinterpreted(self):
        (self.root / 'fixture-feedback-0.json').write_text('{}')
        with self.assertRaisesRegex(R5Error, 'feedback file changed'):
            self.export()

    def test_duplicate_accepted_rows_still_rejected(self):
        with self.assertRaisesRegex(R5Error, 'duplicate feedback import'):
            self.export(imports=[self.imports[0], self.imports[0]])

    def test_resealed_snapshot_cannot_change_context_or_join_mode(self):
        self.export()
        path = self.root / 'out/snapshot.json'
        snapshot = read_json(path)
        snapshot['review_registry_join'] = 'accept_anything'
        path.write_text(__import__('json').dumps(seal(snapshot)))
        with self.assertRaisesRegex(R5Error, 'unsupported reviewed-registry join'):
            verify_gold_snapshot(path)
