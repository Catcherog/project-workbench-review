import hashlib,json,tempfile,unittest
from pathlib import Path
from am_training_data_r10.synthetic import generate,profile_from_owner_messages
from am_training_data_r10.profile import InsufficientStyleEvidence
from am_training_data_r10.scenarios import FAMILIES,semantic_case,render,alternate_style

def source(texts):
    return [{'text':t,'text_sha256':hashlib.sha256(t.encode()).hexdigest(),'exclude_reasons':[],'raw_expires_at_ms':2000} for t in texts]

class TrainingCandidateTests(unittest.TestCase):
    def profile(self):
        return profile_from_owner_messages(source(['确认后同步一下。','如果没有问题，再告诉我一下。']),now_ms=1000)
    def test_empty_source_rejects_generation(self):
        p=profile_from_owner_messages([],now_ms=1000)
        self.assertEqual(p['observed_preferences'],[])
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaisesRegex(InsufficientStyleEvidence,'风格依据不足'):generate(p,Path(t)/'data',4)
            self.assertFalse((Path(t)/'data').exists())
    def test_filtered_expired_tampered_or_bot_text(self):
        r=source(['<forwarded_messages>原话','[Image: x]','@AM 查询','来自 Grok 助手：代发','请确认'])
        r[-1]['text_sha256']='f'*64
        r += [{'text':'过期','text_sha256':'x','raw_expires_at_ms':1000}]
        self.assertEqual(profile_from_owner_messages(r,now_ms=1000)['eligible_count'],0)
    def test_duplicate_source_count(self):
        self.assertEqual(profile_from_owner_messages(source(['确认后同步一下。']*3),now_ms=1000)['eligible_count'],1)
    def test_style_changes_output_without_changing_facts(self):
        a=self.profile();b=profile_from_owner_messages(source(['请详细分点说明。首先列出状态，其次列出待确认事项。'*6]),now_ms=1000)
        self.assertNotEqual(a['style'],b['style'])
        for family in FAMILIES:
            c=semantic_case(family,2);x=render(c,a['style']);y=render(c,b['style'])
            self.assertNotEqual(x,y)
            for s in c['statements']:self.assertIn(s,x);self.assertIn(s,y)
    def test_followup_does_not_invent_missing_subject(self):
        c=semantic_case('followup_preview',0);a=render(c,self.profile()['style'])
        self.assertNotIn('样机',a);self.assertNotIn('回样',a);self.assertIn('主题缺失',a)
        c=semantic_case('followup_preview',1)
        self.assertEqual(c['facts']['followup_topic'],'回样时间')
        self.assertIn('试制件的回样时间',render(c,self.profile()['style']))
    def test_full_generation_uses_profile_with_identical_factual_inputs(self):
        a=self.profile()
        b=profile_from_owner_messages(source(['请详细分点说明。首先说明状态，其次列出下一步。'*6]),now_ms=1000)
        with tempfile.TemporaryDirectory() as t:
            ma=generate(a,Path(t)/'a',4);mb=generate(b,Path(t)/'b',4)
            for name in ma['files']:
                self.assertNotEqual(ma['files'][name],mb['files'][name])
            for split in ('train','dev'):
                x=[json.loads(l) for l in (Path(t)/f'a/sft.{split}.jsonl').read_text().splitlines()]
                y=[json.loads(l) for l in (Path(t)/f'b/sft.{split}.jsonl').read_text().splitlines()]
                for first,second in zip(x,y):
                    self.assertEqual(first['messages'][:-1],second['messages'][:-1])
                    self.assertNotEqual(first['messages'][-1],second['messages'][-1])
    def test_date_types_remain_distinct(self):
        a=render(semantic_case('missing_owner',0),self.profile()['style'])
        self.assertIn('检查点',a);self.assertNotIn('日前确认',a)
        c=semantic_case('project_summary',0)
        self.assertIn('planned_test_completion_date',c['facts']);self.assertNotIn('plan',c['facts'])
    def test_unit_and_meeting_topic_supported(self):
        c=semantic_case('estimate_unit',0)
        self.assertNotIn('2点',render(c,self.profile()['style']));self.assertIsNone(c['facts']['unit'])
        self.assertEqual(semantic_case('meeting_invite',0)['facts']['meeting_topic'],'问题确认')
    def test_style_alternative_retains_all_semantic_statements(self):
        for family in FAMILIES:
            c=semantic_case(family,0);s=self.profile()['style']
            for statement in c['statements']:
                self.assertIn(statement,render(c,s));self.assertIn(statement,render(c,alternate_style(s)))
    def test_split_reproducibility_and_no_fake_gold(self):
        with tempfile.TemporaryDirectory() as t:
            a=generate(self.profile(),Path(t)/'a',4);b=generate(self.profile(),Path(t)/'b',4)
            self.assertEqual(a['files'],b['files']);self.assertFalse(a['training_eligible'])
            self.assertTrue(set(a['train_families']).isdisjoint(a['dev_families']))
            p=json.loads((Path(t)/'a/provenance.json').read_text());self.assertEqual(len(p),80)
            self.assertTrue(all(x['previous_sample_id'] and not x['human_approved'] for x in p))
            for split in ('train','dev'):
                pairs=[json.loads(l) for l in (Path(t)/f'a/dpo.{split}.jsonl').read_text().splitlines()]
                for pair in pairs:
                    self.assertNotEqual(pair['chosen'],pair['rejected']);m=pair['metadata']
                    if m['preference_kind']=='style_only':self.assertEqual(m['chosen_semantic_sha256'],m['rejected_semantic_sha256'])
            with self.assertRaises(FileExistsError):generate(self.profile(),Path(t)/'a',4)
    def test_unbound_observation_rejected(self):
        p=self.profile();p['observed_preferences'][0]['source_text_hashes']=['f'*64]
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(InsufficientStyleEvidence):generate(p,Path(t)/'data',4)

if __name__=='__main__':unittest.main()
