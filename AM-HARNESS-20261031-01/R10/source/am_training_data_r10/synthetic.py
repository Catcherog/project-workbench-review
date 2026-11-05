"""Generate reviewable style candidates without copying real business facts.

The split is by scenario family, never by random paraphrase row. These are
templated candidates, not independent human gold or a sealed business test.
"""
from pathlib import Path
from datetime import date,timedelta
import argparse,json,hashlib,re,statistics,time

SYSTEM='你是项目助理。只依据给定事实回答，先说结果，再说必要的下一步。表达自然、简洁，保留预计、如果、待核、未完成等限定。没有实际回执不声称已发送、已批准或已完成；缺失人员和日期不猜测。只输出给用户看的正文。'
FAMILIES=['progress','conditional_purchase','supplier_date','missing_owner','review_pending','project_summary',
    'followup_preview','pause','resume','unknown_send','node_vs_task','estimate_unit','partial_done','conflict',
    'material_gap','meeting_invite','report_summary','outside_item','scope_missing','late_feedback']
DEV={'supplier_date','partial_done','outside_item','late_feedback'}

def digest(value):return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def profile_from_owner_messages(rows,now_ms=None):
    now_ms=int(time.time()*1000) if now_ms is None else now_ms
    eligible=[];excluded={}
    for row in rows:
        text=row['text'];reasons=list(row.get('exclude_reasons',[]))
        expires=row.get('raw_expires_at_ms')
        if type(expires) is not int or expires<=now_ms:reasons.append('raw_expired_or_expiry_unverified')
        if re.search(r'<forwarded_messages>|<file\b|\[Image:|img_v\d|^<p>https?://|^\s*https?://|^批准知识|^确认执行',text,re.I):reasons.append('forward_attachment_or_control')
        if '@AM' in text or text.startswith('/doc'):reasons.append('bot_query')
        if reasons:excluded[row['text_sha256']]=sorted(set(reasons));continue
        eligible.append(row)
    lengths=[len(row['text']) for row in eligible]
    return {'schema':'am-owner-style-profile/1','authorship':'owner_sender; human authorship not independently certified',
        'source_count':len(rows),'eligible_count':len(eligible),'median_chars':statistics.median(lengths) if lengths else None,
        'source_text_hashes':[row['text_sha256'] for row in eligible],'excluded':excluded,
        'observed_preferences':['先交代当前进度或具体事项，再提出需要确认的动作','保留如果、预计、尚未完成等条件',
            '需要对方反馈时直接说明对象、内容和时点','普通跟进允许简短自然语气；正式事项保留必要数量与日期'],
        'limits':['有限日期和既有授权群聊；不是全部历史沟通','转发正文、附件标记、测试和机器人命令排除',
            '只抽象表达习惯，不复制人员、项目、供应商、数量或实际日期到合成数据']}

def scenario(family,index):
    day=date(2099,1,1)+timedelta(days=index);when=day.isoformat();later=(day+timedelta(days=7)).isoformat()
    project=f'合成项目{index+1:03d}';n=index+2;done=index+1
    definitions={
      'progress':(f'{project}现在进展怎么样？',{'reported':'样机已到','test_started':False,'next_check':when},
        f'{project}样机已到，测试还没开始。请在{when}确认台架档期和开测时间。',f'{project}测试已完成。'),
      'conditional_purchase':('帮我整理采购安排。',{'project':project,'quantity':n,'condition':'样机测试无问题','order_placed':False},
        f'{project}如果样机测试无问题，预计按{n}件下单。目前还未下单。',f'{project}已下单{n}件。'),
      'supplier_date':('交期怎么回复？',{'project':project,'estimated_date':when,'supplier_confirmed':False},
        f'{project}目前预计{when}到料，供应商还未确认。确认后再同步实际预计交期。',f'{project}供应商已确认{when}到料。'),
      'missing_owner':('这件事谁负责？',{'project':project,'owner':None,'next_check':when},
        f'{project}现有资料没有明确负责人，需要在{when}前确认。',f'{project}由同事甲负责。'),
      'review_pending':('这个交付物算完成了吗？',{'project':project,'submitted':True,'reviewed':False,'count':n},
        f'{project}的{n}份材料已提交，审核还未完成，暂不能按验收完成记录。',f'{project}的{n}份材料已验收完成。'),
      'project_summary':('简单说一下计划、进展、卡点和下一步。',{'project':project,'plan':when,'progress':'样机已到','blocker':'台架未排定'},
        f'{project}计划{when}完成测试，目前样机已到。卡在台架尚未排定，下一步需要确认档期及对计划的影响。',f'{project}已按{when}完成测试，没有卡点。'),
      'followup_preview':('准备一条跟进消息。',{'project':project,'target':'同事甲','quantity':n,'deadline':when,'approved':False},
        f'拟发给同事甲：{project}这{n}件样机的回样时间确认了吗？请在{when}前同步一下。正文待你确认后发送。',f'已通知同事甲在{when}前完成{n}件样机。'),
      'pause':('这个事项先怎么处理？',{'project':project,'decision':'暂停','next_check':when,'completed':False},
        f'{project}按当前决定暂停，{when}再检查。事项还未完成。',f'{project}已经完成并关闭。'),
      'resume':('可以说恢复测试了吗？',{'project':project,'status':'待恢复','planned_date':None,'estimate':n},
        f'{project}保留{n}点估分，目前仍为待恢复，恢复时间未定，不能说已恢复测试。',f'{project}已恢复测试，将投入{n}人天。'),
      'unknown_send':('上一条消息发出去了吗？',{'project':project,'delivery':'unknown','message_id':None},
        f'{project}这条消息的发送结果还不明确，尚未取得消息回执，需要先核对原请求，避免重复发送。',f'{project}消息已发送成功，我再发一遍。'),
      'node_vs_task':('子任务勾完就代表节点完成了吗？',{'project':project,'finished_subtasks':done,'all_subtasks':n,'node':'进行中'},
        f'{project}目前{n}项子任务中有{done}项已标记完成，节点仍为进行中，不能写成整个节点已完成。',f'{project}节点已完成。'),
      'estimate_unit':('这些估分是多少人天？',{'project':project,'estimate':n,'unit':None},
        f'{project}记录为{n}点估分，没有注明工时单位，暂不能换算成人天。',f'{project}投入{n}人天。'),
      'partial_done':('这批任务是否都结束了？',{'project':project,'total':n,'done':done,'remaining':1},
        f'{project}共{n}项，已完成{done}项，还剩1项未完成，不能按全部结束记录。',f'{project}共{n}项，已经全部完成。'),
      'conflict':('两个进度反馈不一致怎么办？',{'project':project,'report_a':'已完成','report_b':'仍在测试','accepted_evidence':None},
        f'{project}一份反馈说已完成，另一份说仍在测试，当前没有验收依据。需要核实差异，先保留待核状态。',f'{project}已经完成，另一份反馈可以忽略。'),
      'material_gap':('先给我一份草稿。',{'project':project,'known_quantity':n,'approval':None,'responsible_person':None},
        f'{project}已知数量为{n}件。批准状态和负责人缺少依据，草稿中标为待补，完成核对后再确认。',f'{project}数量为{n}件，已批准，由同事甲负责。'),
      'meeting_invite':('帮我拟一句会议邀请。',{'project':project,'time':when+' 10:00–11:00','sent':False},
        f'拟发送：{project}的问题确认会议安排在{when}10:00–11:00，你方便参加吗？目前只是邀请草稿，还未发送。',f'{project}会议已邀请所有人参加，时间为{when}10:00–11:00。'),
      'report_summary':('这周进度怎么概括？',{'project':project,'submitted':n,'reviewed':done,'next_check':when},
        f'{project}本周提交{n}份材料，其中{done}份已审核。剩余1份待核，{when}再确认结果。',f'{project}本周{n}份材料均已审核。'),
      'outside_item':('这条应该放到哪个项目？',{'topic':project+'模板协调','explicit_outside':True,'linked_project':None},
        f'{project}模板协调已明确登记为项目外事项，当前没有关联项目，按原主题继续跟进。',f'已将{project}模板协调归入项目乙。'),
      'scope_missing':('能直接采用这个结论吗？',{'project':project,'reported_scope':'首轮样机','mass_production_verified':False},
        f'{project}现有结论只覆盖首轮样机，尚未验证量产适用性，不能直接扩展到量产。',f'{project}结论已适用于量产。'),
      'late_feedback':('检查点到了但没反馈，怎么写？',{'project':project,'check_date':when,'new_feedback':None,'next_check':later},
        f'{project}截至{when}还没有收到新反馈，不能据此判定已完成。下一检查点为{later}，先核实当前进度。',f'{project}在{when}已经完成。'),
    }
    question,facts,chosen,rejected=definitions[family]
    return question,facts,chosen,rejected

def generate(profile,out,per_family=120):
    out=Path(out);out.mkdir(parents=True,mode=0o700,exist_ok=False)
    sft={'train':[],'dev':[]};dpo={'train':[],'dev':[]};provenance=[]
    for family in FAMILIES:
        split='dev' if family in DEV else 'train'
        for i in range(per_family):
            question,facts,chosen,rejected=scenario(family,i)
            user=json.dumps({'task':question,'facts':facts,'synthetic':True},ensure_ascii=False,sort_keys=True)
            messages=[{'role':'system','content':SYSTEM},{'role':'user','content':user}]
            sample_id=f'r10-{family}-{i:04d}'
            sft[split].append({'messages':messages+[{'role':'assistant','content':chosen}]})
            provenance.append({'sample_id':sample_id,'family':family,'split':split,'input_sha256':digest(messages),
                'output_sha256':digest(chosen),'style_profile_sha256':digest(profile),'data_classification':'synthetic',
                'generator':'deterministic_scenario_candidates_v1','human_approved':False,'training_eligible':False})
            if i%2==0:
                # Some pairs differ only in expression; others contain explicit
                # factual/authority errors. Do not conflate these preferences.
                style_only=i%4==0
                negative=('关于您提出的这个问题，我为您进行了全面整理。'+chosen+'综上所述，'+chosen) if style_only else rejected
                dpo[split].append({'prompt':messages,'chosen':[{'role':'assistant','content':chosen}],
                    'rejected':[{'role':'assistant','content':negative}],'metadata':{'sample_id':sample_id,
                    'preference_kind':'style_only' if style_only else 'factual_boundary','preference_source':'synthetic_rule',
                    'human_approved':False,'family':family,'split':split}})
    manifest={'schema':'am-synthetic-training-candidates/1','style_profile_sha256':digest(profile),
        'scenario_families':len(FAMILIES),'train_families':sorted(set(FAMILIES)-DEV),'dev_families':sorted(DEV),
        'independent_test_cases':0,'training_executed':False,'human_approved_samples':0,'training_eligible':False,
        'limitations':['Template-generated variants are not independent semantic cases','DPO preferences are synthetic, not user votes',
            'Independent task completion holdout and sample review are required before training','No production model or route changes'],
        'counts':{},'files':{}}
    for kind,groups in [('sft',sft),('dpo',dpo)]:
        for split,rows in groups.items():
            assert len({digest(row) for row in rows})==len(rows)
            name=f'{kind}.{split}.jsonl';content=''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows)
            assert not re.search(r'ou_[a-f0-9]{12}|oc_[a-f0-9]{12}|om_[a-f0-9]{12}|IRAD-2026|RA-2026|AR221',content)
            p=out/name;p.write_text(content);p.chmod(0o600);manifest['counts'][name]=len(rows)
            manifest['files'][name]=hashlib.sha256(p.read_bytes()).hexdigest()
    for name,value in [('profile.json',profile),('provenance.json',provenance),('manifest.json',manifest)]:
        p=out/name;p.write_text(json.dumps(value,ensure_ascii=False,indent=2));p.chmod(0o600)
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--owner-messages',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    profile=profile_from_owner_messages(json.loads(Path(a.owner_messages).read_text()))
    print(json.dumps(generate(profile,a.output),ensure_ascii=False))
