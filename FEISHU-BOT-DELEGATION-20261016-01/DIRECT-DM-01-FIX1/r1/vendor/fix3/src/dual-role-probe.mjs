// Deliberate hard gate: no real launch capability is enabled in this blocked delivery.
console.error(JSON.stringify({status:'BLOCKED',reason:'parent_and_command_sandbox_composition_unavailable',realModelStarts:0,offlineReproduction:'node --test tests/dual-role.test.mjs'}));
process.exitCode=2;
