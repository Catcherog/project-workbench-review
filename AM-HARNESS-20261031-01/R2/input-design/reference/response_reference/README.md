# Response reference contracts (design only)

This package is an importable reference for the AM Harness Outcome/Response design. It does not change or run the production bot. All real model, semantic-assessment, source, rendering, persistence and delivery implementations are deliberately left as Protocol ports.

Set `PYTHONPATH` to the directory containing `response_reference/`, then run the narrow reference checks:

```sh
python3 -m unittest response_reference.test_reference -v
```

The test Assessor always accepts fixtures solely to exercise routing; it is **not** an implementation to ship. Mechanical claim coverage does not prove semantic fidelity. One test intentionally demonstrates a wrong paraphrase with a correct citation passing mechanical checks. The orchestrator requires an explicit semantic assessment profile for free text; without one it regenerates from the current trusted Outcome through HostRenderer.

Generation defaults off. Existing fast/control paths remain zero model. Main-model final plans are reused without another call. An independently admitted durable-expression route can make at most one call through the original coordinator. Run and Event bindings remain different. STOP_UNKNOWN and unclassified timeouts propagate to the original host, never imply a safe fallback or lane release.

`TaskFamily.SCHEDULE` covers plans and reminders. Their original approval, exact preview/version binding, execution receipts and readback remain authoritative; this family does not authorize scheduling or sending. A durable-expression route requires a real `RunBinding`, not only the route enum.

`ResponsePolicy.mode=off` means this **new** pipeline uses HostRenderer. It is not an alias for the existing R2 switch. Production must provide a separate integration switch and a compatibility renderer before replacing existing replies. Adapters preserve both real origin_event_id and engine_event_id; they do not reconstruct these identities from a Run id or message body.

HostRenderer must be implemented per task family, preserve actual partial/unknown results, and retain required protected text. EnvelopeGuard must check live authorization, dependencies, TTL and current event/run state on every call. Preparing text is outside SQL commit; the original host must still recheck and bind it at finalization, publication and dispatch. A metadata-only outcome may not carry old source content.

The envelope boundary requires required host blocks for every effect/non-complete/unresolved work unit, every receipt, and every important coverage gap. Their ids are explicitly bound to the blocks; generated plans cannot omit these blocks. This still assumes the trusted adapter wrote the correct host status text. Both candidate and canonical rendering retain block order.

The main design document delivered with this package specifies integration points, boundaries, all task families, failure risks, rollout and Codex's required production-path tests. Passing this package's tests proves neither production correctness nor human acceptance.
