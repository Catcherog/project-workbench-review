"""Read-only discovery of already authorized document mounting targets."""
from __future__ import annotations

import time
import re

from .config import BoundaryError


def discover_targets(business, row, *, project_code, doc_type, guard, deadline, limit=32):
    if doc_type not in ('charter', 'change', 'closure'):
        raise BoundaryError('DOCUMENT_DELIVERY_TYPE_INVALID')
    if guard() is False:
        raise BoundaryError('DOCUMENT_DELIVERY_SCOPE_CHANGED')
    settings = getattr(business, 'settings', None)
    configured = settings.get('targets') if isinstance(settings, dict) else None
    def result(state, targets=(), unresolved=(), labels=None):
        return {'state': state, 'targets': list(targets), 'unresolved': list(unresolved),
                'labels': labels or {}, 'doc_type': doc_type, 'read_only': True}
    if not isinstance(configured, dict):
        return result('not_configured')
    if len(configured) > limit:
        return result('unresolved', unresolved=['configured_target_limit'])
    resolver = getattr(business, 'resolve', None)
    identity_reader = getattr(business, 'document_identity', None)
    if not callable(resolver) or not callable(identity_reader):
        return result('unresolved', unresolved=['target_identity_unavailable'])
    matches = []; unresolved = []; labels = {}
    for alias in sorted(configured):
        if guard() is False:
            raise BoundaryError('DOCUMENT_DELIVERY_SCOPE_CHANGED')
        if time.monotonic() >= deadline:
            unresolved.append('deadline'); break
        try:
            target = resolver(row, alias)
            identity = identity_reader(row, target)
        except BoundaryError:
            # A failure cannot prove that a formal target is absent.
            unresolved.append(alias); continue
        if guard() is False:
            raise BoundaryError('DOCUMENT_DELIVERY_SCOPE_CHANGED')
        if time.monotonic() >= deadline:
            unresolved.append('deadline'); break
        if identity.get('project_code') == project_code and identity.get('doc_type') == doc_type:
            if not all(target.get(k) for k in ('id', 'project_id', 'node_id', 'deliverable_id', 'revision')):
                unresolved.append(alias); continue
            matches.append(dict(target))
            config = configured[alias] if isinstance(configured[alias], dict) else {}
            names = [target.get(k) for k in ('title', 'name', 'label')] + [config.get(k) for k in ('display_name', 'title', 'name', 'label')]
            label = next((n.strip() for n in names if isinstance(n, str) and n.strip()), None)
            if label is None and re.search(r'[\u4e00-\u9fff]', alias):label = alias
            if label:labels[target['id']] = label
    state = ('unresolved' if unresolved else 'ambiguous' if len(matches) > 1
             else 'available' if matches else 'not_configured')
    return result(state, matches, unresolved, labels)


def render_targets(result):
    state = result['state']
    if state == 'not_configured':
        return '当前授权配置中未找到本项目、本文种的正式挂载目标。草稿可以继续整理；请补齐对应项目、节点和交付物绑定。'
    if state == 'unresolved':
        return '正式挂载目标尚未核验完整。已保留草稿，请待目标读取恢复后再核对。'
    lines = ['已核验当前授权配置中的正式目标：' if state == 'available' else '找到多个匹配的正式目标，请明确选择：']
    kind = {'charter': '项目章程', 'change': '变更申请', 'closure': '结项报告'}.get(result.get('doc_type'), '文档')
    for number, target in enumerate(result['targets'], 1):
        label = result.get('labels', {}).get(target['id']) or '已配置的' + kind + '正式目标'
        lines.append((str(number) + '. ' if len(result['targets']) > 1 else '') + label)
    lines.append('选择目标、采用当前文字与正式挂载仍按原流程分别执行。')
    return '\n'.join(lines)
