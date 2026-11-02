"""Conservative checks for explicit, quoted business signals.

This is a bounded completeness check, not a language model or an authority
classifier. A match requires the salient words in both quote and value. A
paraphrase which cannot satisfy that check is routed to review, never repaired
by guessing a project, person, date or formal business state. No source text is
included in diagnostics, and no candidate/action is generated here.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re

from am_info_sync.models import Source
from am_info_sync.policy import can_read


FIELDS = (
    'progress', 'plan', 'forecast', 'review', 'node', 'decision', 'risk', 'owner',
    'response', 'action_request', 'delivery', 'acceptance', 'context', 'constraint',
)


@dataclass(frozen=True)
class SignalRule:
    code: str
    pattern: str
    fields: tuple[str, ...]
    assertion_type: str = 'reported'


# Deliberately narrow phrases. Other languages, paraphrases and implicit facts
# remain model/human-review responsibilities. These rules do not establish
# that an input was fully understood merely because no rule failed.
RULES = (
    SignalRule('response', r'(?:回复|回应|答复)\s*[“"：:]?\s*(?:收到|OK\b|了解|知道了|好的|明白)', ('response',)),
    SignalRule('approval', r'审批(?:已经|已)?通过', ('review',)),
    SignalRule('approval_not_withdrawn', r'不是审批撤回', ('review',)),
    SignalRule('not_project_acceptance', r'不代表(?:项目)?完成', ('acceptance', 'constraint')),
    SignalRule('retire_reminder_request', r'(?:旧的)?待提审提醒可以撤除', ('action_request',), 'proposal'),
    SignalRule('plan', r'计划(?:今天|明天|本周|下周|本月|下月|周[一二三四五六日天])[^，。；;\n]{1,35}', ('plan',)),
    SignalRule('execution', r'正在测试|仍在测试中|实际已开测|已开始测试', ('progress',)),
    SignalRule('execution_evidence_missing', r'(?:没有|未)(?:提供)?(?:实际)?(?:开测|发布)(?:记录|证据)', ('progress',)),
    SignalRule('acceptance_pending', r'实际是否开测尚待核实|可用性尚未确定|业务核验尚未完成|正式可对外使用的版本待确认', ('acceptance',)),
    SignalRule('delivery', r'样机已到仓|材料已交付|稿件与版本已经齐备|测试方案已经发出|已经有测试概述', ('delivery', 'context')),
    SignalRule('disclosure_constraint', r'(?:仍)?禁止对外(?:发送|披露)', ('constraint',)),
    SignalRule('action_request', r'(?:请把|请将|请|需要)[^。；;\n]{0,60}(?:记下来|记录|登记|补充|确认)', ('action_request',), 'proposal'),
)


def _normal(value):
    return re.sub(r'\s+', '', value).casefold()


def coverage_report(text, candidates):
    """Return only codes/counts; never raw text or inferred business facts."""
    missing = set()
    matched = 0
    for rule in RULES:
        for match in re.finditer(rule.pattern, text, re.IGNORECASE):
            matched += 1
            anchor = _normal(match.group())
            if not any(c['field'] in rule.fields
                       and c['assertion_type'] == rule.assertion_type
                       and anchor in _normal(c['quote'])
                       and anchor in _normal(c['value']) for c in candidates):
                missing.add(rule.code)
    # A direct request with explicitly unresolved project identity must remain
    # a source-level review gap even if one project happens to be in context.
    unresolved = bool(re.search(
        r'(?:项目|主体)(?=、|，|和|及|均未|未明|尚未)[^。；;\n]{0,48}(?:未明确|不明确)', text))
    if unresolved and any(re.search(r.pattern, text, re.IGNORECASE)
                          for r in RULES if r.code == 'action_request'):
        missing.add('subject_unresolved')
    for candidate in candidates:
        if (candidate['field'] == 'forecast') != (candidate['assertion_type'] == 'forecast'):
            missing.add('forecast_dimension')
    return {'check': 'explicit_anchor_coverage_v1', 'matched_signals': matched,
            'issues': sorted(missing), 'semantic_acceptance': 'requires_review'}


def pending_reviews(store, principal, *, limit=30):
    """Read current authorized gaps with retention-limited source excerpts.

    One local read transaction covers ACL, gap and current observation. Old
    versions are never used to fill missing current evidence. No raw text is
    persisted by this view, and revoked/disabled sources disappear immediately.
    """
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError('review_limit_invalid')
    items = []
    total = 0
    expires_at_ms = None
    with store.transaction() as db:
        epoch = db.execute('SELECT namespace,revision FROM source_access_version WHERE singleton=1').fetchone()
        access_version = epoch[0] + ':' + str(epoch[1])
        rows = db.execute("""SELECT g.*,s.config_json,s.availability,
            o.text,o.url,o.raw_expires_at_ms,o.purged,o.deleted,o.completeness,
            b.state AS object_state FROM gaps g
            JOIN sources s ON s.source_id=g.source_id
            LEFT JOIN objects b ON b.source_id=g.source_id AND b.object_id=g.object_id
            LEFT JOIN observations o ON o.source_id=b.source_id AND o.object_id=b.object_id
                AND o.version=b.current_version
            WHERE g.state='open' AND g.kind='extraction'
            ORDER BY g.last_seen_ms DESC,g.source_id,g.object_id""")
        now = store.clock()
        for row in rows:
            source = Source.from_dict(json.loads(row['config_json']))
            if row['availability'] == 'denied' or not can_read(source, principal):
                continue
            total += 1
            if len(items) >= limit:
                continue
            raw_available = (row['object_state'] == 'active'
                and row['raw_expires_at_ms'] is not None and row['raw_expires_at_ms'] > now
                and row['purged'] == 0 and row['deleted'] == 0
                and row['completeness'] == 'complete')
            detail = row['detail']
            if detail.startswith('semantic_coverage_incomplete'):
                reason = '明确业务信息未完整保留或分类需核对'
                if 'subject_unresolved' in detail:
                    reason = '行动请求的项目归属尚未明确'
            elif detail == 'semantic_budget_incomplete':
                reason = '本次资料超出单轮完整提取范围'
            elif detail == 'raw_evidence_unavailable':
                reason = '原始资料已不可用，需要重新提供'
            else:
                reason = '资料提取未完成，需要复核来源'
            items.append({'source_id': source.source_id, 'object_id': row['object_id'],
                'reason': reason, 'text': row['text'][:220] if raw_available else '',
                'url': row['url'] if raw_available else None,
                'raw_available': bool(raw_available)})
            if raw_available:
                expires_at_ms = min(expires_at_ms or row['raw_expires_at_ms'], row['raw_expires_at_ms'])
    return {'items': items, 'total': total, 'source_access_version': access_version,
            'raw_expires_at_ms': expires_at_ms}
