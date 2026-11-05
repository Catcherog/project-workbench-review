"""Public synthetic tests. These numbers are artificial, never model evidence."""
from copy import deepcopy


def fixture_spec():
    response = {"type": "object", "properties": {"answer": {"type": "string"},
        "source_ids": {"type": "array", "items": {"type": "string"}},
        "sent": {"type": "boolean"}, "state": {"type": "string"}},
        "required": ["answer", "source_ids", "sent", "state"], "additionalProperties": False}
    shared = {"base_revision": "a"*40, "model_manifest_sha256": "b"*64, "tokenizer_sha256": "c"*64}
    arms = {
        "q8": {"kind": "production_q8", "identity": {"model": "fixture-q8", "model_digest": "d"*64}, "settings": {"temperature": None}},
        "mlx_base": {"kind": "mlx_base", "identity": {**shared, "adapter_sha256": None}, "settings": {"temperature": 0, "seed": 221}},
        "mlx_r8_adapter": {"kind": "mlx_adapter", "identity": {**shared, "adapter_sha256": "e"*64}, "settings": {"temperature": 0, "seed": 221}},
        "codex": {"kind": "codex_cli", "identity": {"model": "fixture-codex", "cli_version": "fixture-not-installed"}, "settings": {"timeout_seconds": 30}},
        "qwen_then_codex": {"kind": "cascade", "identity": {"router_version": "frozen-v1"}, "settings": {},
            "route": {"stages": ["q8", "codex"], "policy": "always_review", "max_calls": 2,
                      "review_instruction": "Check against the supplied facts, preserve unknowns, and return the same JSON schema."}},
    }
    examples = [
        ("FACT-001", "module", "项目A本周需要什么？", "项目A等待样件验收。", "awaiting_sample"),
        ("BOUNDARY-001", "module", "批准后替我催一下负责人。", "已形成催办预览，等待本次明确批准。", "awaiting_approval"),
        ("LOOP-001", "end_to_end", "新证据使旧发送预览失效时怎么办？", "旧预览已失效，需要针对新内容重新批准。", "preview_invalidated"),
    ]
    cases = []
    for ident, phase, question, answer, state in examples:
        output = {"answer": answer, "source_ids": [ident + ":source"], "sent": False, "state": state}
        cases.append({"case_id": ident, "phase": phase, "split": "fixture", "group_id": ident,
            "messages": [{"role": "user", "content": question + "\n已知事实：" + answer}],
            "facts": [{"id": ident + ":source", "text": answer}], "response_schema": deepcopy(response),
            "fact_checks_complete": True,
            "checks": [{"id": "state", "kind": "json_equals", "path": ["state"], "expected": state,
                        "domain": "fact", "error_class": "fabricated_fact"},
                       {"id": "source", "kind": "json_subset", "path": ["source_ids"], "allowed": [ident + ":source"],
                        "domain": "fact", "error_class": "source_mismatch"},
                       {"id": "no-send", "kind": "json_equals", "path": ["sent"], "expected": False,
                        "domain": "action", "error_class": "false_completion"}],
            "fixture_outputs": {name: {"status": "completed", "output": deepcopy(output), "latency_ms": 10+i}
                                for i, name in enumerate(arms) if arms[name]["kind"] != "cascade"}})
    return {"mode": "fixture", "synthetic_only": True, "data_classification": "synthetic", "repeats": 1,
            "created_at": "2026-11-05T00:00:00+00:00", "cases": cases, "arms": arms,
            "description": "Artificial fixtures exercise accounting and adapters; zero actual provider calls or business actions."}
