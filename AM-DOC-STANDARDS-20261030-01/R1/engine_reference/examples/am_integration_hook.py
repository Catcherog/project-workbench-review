"""Illustrative insertion into existing LogicService.generate(document branch).

Not a replacement gateway. Host-specific row mapping/target permissions remain to bind.
"""
from am_doc_engine.host_bridge import prepare_am_document


def generate_with_existing_am(*, task, started, deadline, request, access, profiles,
                              snapshot, doc_store, gateway, assert_original_job_current):
    result = prepare_am_document(
        task=task, request=request, access=access, profiles=profiles,
        snapshot=snapshot, store=doc_store, provider=gateway.provider,
        deadline_monotonic=deadline, on_start=started,
        ensure_current=assert_original_job_current,
    )
    # Inside LogicService, persist the original draft's analysis/content hash/revision
    # using its existing transaction and completion guard. Then return:
    # (result.content, Result(result.reply_text, result.model, result.elapsed), expires)
    # `Result` and `expires` belong to the existing host; do not replace their semantics.
    return result
