// FIX1 refuses new model probes while bootstrap/context isolation remains unproven.
// The reusable strict classifier is src/isolation-evidence.mjs, covered by negative tests.
console.error('BLOCKED_B03_B04: same-launch bootstrap isolation and complete model command receipts are not established. No model call was started. Do not lower the evidence predicate.');
process.exitCode=2;
