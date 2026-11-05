"""Traceable, bounded style observations; no business text in the profile."""
import hashlib
import re
import statistics
import time


class InsufficientStyleEvidence(ValueError):
    pass


def profile_from_owner_messages(rows, now_ms=None):
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    eligible, excluded, seen = [], {}, set()
    for row in rows:
        text = row.get('text', '')
        ident = hashlib.sha256(text.encode()).hexdigest()
        reasons = list(row.get('exclude_reasons', []))
        expiry = row.get('raw_expires_at_ms')
        if type(expiry) is not int or expiry <= now_ms:
            reasons.append('raw_expired_or_expiry_unverified')
        if row.get('text_sha256') != ident:
            reasons.append('source_text_hash_mismatch')
        if re.search(r'<forwarded_messages>|<file\b|\[Image:|img_v\d|https?://|^批准知识|^确认执行|来自.*助手|测试消息', text, re.I):
            reasons.append('forward_attachment_control_or_automation')
        if '@AM' in text or text.startswith('/doc'):
            reasons.append('bot_query')
        if not text.strip():
            reasons.append('empty_text')
        if reasons:
            excluded[ident] = sorted(set(reasons))
        elif ident not in seen:
            seen.add(ident)
            eligible.append((ident, text))
    profile = {
        'schema': 'am-owner-style-profile/2', 'status': 'insufficient_style_evidence',
        'authorship': 'owner_sender; human authorship not independently certified',
        'source_count': len(rows), 'eligible_count': len(eligible),
        'source_text_hashes': [ident for ident, _ in eligible], 'excluded': excluded,
        'observed_preferences': [], 'style': None,
        'limits': ['有限授权来源；特征是规则归纳，不是本人逐项确认',
                   '事实边界是独立规则，不从语气推断业务事实或权限',
                   '只保留匿名来源标识，不复制业务正文到合成数据'],
    }
    if not eligible:
        return profile
    median = statistics.median(len(text) for _, text in eligible)
    observations = []

    def observe(key, pattern, summary):
        matches = [ident for ident, text in eligible if re.search(pattern, text)]
        if matches:
            observations.append({'key': key, 'summary': summary,
                                 'sample_ids': ['style-' + ident[:16] for ident in matches],
                                 'source_text_hashes': matches, 'count': len(matches)})
        return len(matches)

    casual = observe('casual_request', r'一下|同步|告诉我|你要来吗|你看看|确认了吗', '直接请求确认或同步，常用短句')
    formal = observe('polite_request', r'请|麻烦|劳烦|烦请', '用礼貌请求表达下一步')
    observe('qualified_state', r'如果|预计|还未|尚未|未完成|待补', '保留条件、预计或缺项限定')
    observe('status_before_request', r'(?:已|目前|现在|还未).{0,80}(?:请|需要|同步|确认|修改)', '先交代状态，再提出请求')
    observe('structured_detail', r'\n|首先|其次|一、|二、|分点|详细', '部分事项使用分行或较详细说明')
    observations.append({'key': 'length', 'summary': '有效文本长度中位数', 'median_chars': median,
                         'sample_ids': ['style-' + ident[:16] for ident, _ in eligible],
                         'source_text_hashes': [ident for ident, _ in eligible], 'count': len(eligible)})
    profile.update(status='usable_observed_style', median_chars=median,
                   observed_preferences=observations,
                   style={'layout': 'compact' if median <= 80 else 'structured',
                          'request_register': 'direct' if casual >= formal else 'polite'})
    return profile


def require_style(profile):
    if (profile.get('status') != 'usable_observed_style' or not profile.get('eligible_count')
            or not profile.get('source_text_hashes') or not profile.get('observed_preferences')):
        raise InsufficientStyleEvidence('风格依据不足：不能生成声称由个人风格驱动的候选')
    style = profile.get('style') or {}
    if style.get('layout') not in {'compact', 'structured'} or style.get('request_register') not in {'direct', 'polite'}:
        raise InsufficientStyleEvidence('风格配置缺失或无效')
    sources = set(profile['source_text_hashes'])
    if any(not p.get('source_text_hashes') or not set(p['source_text_hashes']) <= sources
           for p in profile['observed_preferences']):
        raise InsufficientStyleEvidence('风格归纳缺少对应来源')
    return style
