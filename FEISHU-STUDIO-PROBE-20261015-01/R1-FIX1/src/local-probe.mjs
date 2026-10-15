// The current operator identity remains a live-input blocker. Offline tests use the adapter directly.
console.error('BLOCKED_B03: current operator bootstrap boundary is not isolated. Use the offline tests and preflight; no real model call was started.');
process.exitCode=2;
