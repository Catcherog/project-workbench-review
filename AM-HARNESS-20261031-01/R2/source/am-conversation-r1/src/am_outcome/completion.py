"""Conservative intent resolution from explicit source-grounded targets.

No guessed record counts. Unresolved language stays unresolved; individual
commits are still reported. This bounded resolver does not claim general NLU.
"""
import re


def resolve_goals(text, catalog):
    operations = []
    if re.search(r'登记|建立|创建|新建|记录|记下|保存', text):
        if '跟进' in text and '笔记' not in text: operations.append('create_followup')
        if '笔记' in text: operations.append('save_work_note')
    # A broad request, exclusions, conditional actions or cancellation requires
    # a separate grounded plan; do not claim a complete target set from aliases.
    if len(operations) != 1 or re.search(r'不要|除了|除外|如果|要是|取消|先别|全部|所有', text):
        return [], False
    targets = []
    for project in catalog:
        ident = project.get('id', project.get('key'))
        aliases = [project.get('title'), project.get('business_id'), *(project.get('aliases') or [])]
        hits = [a for a in aliases if isinstance(a, str) and a and a.casefold() in text.casefold()]
        if hits and ident: targets.append((ident, hits))
    # Reject an alias naming two objects, rather than picking the first.
    seen = {}
    for ident, hits in targets:
        for alias in hits:
            if alias in seen and seen[alias] != ident: return [], False
            seen[alias] = ident
    if not targets: return [], False
    if len(targets) > 1 and '分别' not in text and '各' not in text: return [], False
    return [{'operation': operations[0], 'project_id': ident, 'request_spans': hits}
            for ident, hits in targets], True


def check_goals(goals, complete_set, units):
    results = []
    for goal in goals:
        matches = [u for u in units if u['operation'] == goal['operation']
                   and u['target'].get('project_id') == goal['project_id']]
        matched = [u for u in matches if u['completion'] == 'fulfilled']
        results.append(dict(goal, completion='fulfilled' if matched else 'pending',
                            receipt_refs=[u['id'] for u in matched]))
    done = sum(r['completion'] == 'fulfilled' for r in results)
    state = ('fulfilled' if complete_set and results and done == len(results)
             else 'partial' if done or units else 'blocked')
    return results, state
