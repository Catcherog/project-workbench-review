import unittest,tempfile,json
from pathlib import Path
from am_training_data_r10.synthetic import generate,profile_from_owner_messages,FAMILIES,DEV,digest

class TrainingCandidateTests(unittest.TestCase):
    def test_forwarded_and_assistant_text_never_define_owner_style(self):
        rows=[{'text':text,'text_sha256':digest(text),'exclude_reasons':[],'raw_expires_at_ms':2000}
              for text in ['<forwarded_messages>别人的原话','[Image: x]','@AM 请查询','这件事进展怎么样，回样时间确认后同步一下。']]
        profile=profile_from_owner_messages(rows,now_ms=1000)
        self.assertEqual(profile['eligible_count'],1)
        self.assertEqual(profile['source_text_hashes'],[rows[-1]['text_sha256']])

    def test_expired_or_unverified_raw_text_cannot_define_style(self):
        rows=[{'text':'真实原文','text_sha256':'hash','exclude_reasons':[],**expiry}
              for expiry in ({},{'raw_expires_at_ms':1000},{'raw_expires_at_ms':True})]
        self.assertEqual(profile_from_owner_messages(rows,now_ms=1000)['eligible_count'],0)

    def test_family_split_keeps_related_variants_together_and_no_fake_gold(self):
        profile=profile_from_owner_messages([])
        with tempfile.TemporaryDirectory() as directory:
            out=Path(directory)/'data';manifest=generate(profile,out,4)
            self.assertFalse(manifest['training_eligible'])
            self.assertEqual(manifest['independent_test_cases'],0)
            self.assertTrue(set(manifest['train_families']).isdisjoint(manifest['dev_families']))
            rows=json.loads((out/'provenance.json').read_text())
            self.assertTrue(all(row['split']==('dev' if row['family'] in DEV else 'train') for row in rows))
            self.assertTrue(all(not row['human_approved'] for row in rows))
            pairs=[json.loads(line) for line in (out/'dpo.train.jsonl').read_text().splitlines()]
            self.assertEqual({row['metadata']['preference_kind'] for row in pairs},{'style_only','factual_boundary'})
            self.assertTrue(all(row['chosen']!=row['rejected'] for row in pairs))

    def test_generation_is_reproducible_and_cannot_overwrite_reviewed_corpus(self):
        with tempfile.TemporaryDirectory() as directory:
            profile=profile_from_owner_messages([])
            a=generate(profile,Path(directory)/'a',4);b=generate(profile,Path(directory)/'b',4)
            self.assertEqual(a['files'],b['files'])
            with self.assertRaises(FileExistsError):generate(profile,Path(directory)/'a',4)
