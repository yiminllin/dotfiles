---
name: "trace-hil-failure-chains-before-timeouts"
description: "Diagnose Phoenix HIL MISSION_TIMED_OUT, pre-takeoff capability failures, NODATA and nested CAUSED_BY reports from retained CI logs before assuming timing or simulator root causes."
version: 1
created: "2026-10-14"
updated: "2026-10-14"
---
## When to Use
Use for retained HIL CI log diagnosis when mission completion times out or a failure report contains nested causes. Route detailed native/process evidence inspection to phoenix-inspector.

## Procedure
1. Read full retained CI stdout and strip ANSI escapes. Separate executed runtime messages from echoed shell and container-build warnings.
2. Preserve the full block following Failure Reason 1, including every CAUSED_BY continuation. Error-line-only filters omit actionable leaf causes.
3. Build each run's timeline independently: simulation start, acceptance, FAILED/ENDED_IN_FAILURE or COMPLETED, and runner shutdown. Separate startup, in-mission, and teardown failures. Check whether a reported timeout followed an earlier terminal mission failure. Distinguish measured publication gaps and timing-validator failures from the mission or fault-injection failure. Similar symptoms across repetitions do not establish a shared cause.
4. Locate leaf error-code producers in source. Read inputs, thresholds and propagation. Droid actuator TIMED_OUT producers live in motor_alarm_integration.rs and control_loop health_aggregator.rs; distinguish missing feedback from execution timeout.
5. Compare actual hardware config paths and revision fixtures across runs. A Zip-EV3 selector does not imply EV3 Droid on all benches. Inspect generated scenario revision and matching feedback interfaces.
6. Use exact process/native traces to find the first broken producer, bridge, IPC or consumer edge. If access is expired, stop retrieval without refreshing credentials and report missing evidence.

## Pitfalls
- NODATA does not prove a measured deadline/memory fault. Simulator return1 does not prove a timing validator failure.
- Fault-injection DockASAP may intentionally produce failed mission status. Preserve expected-failure semantics before suggesting fail-fast changes.
- Missing interception entries or revision differences are candidates, not proof of dropped messages. Do not force older hardware configs or relax feedback/recovery guards.

## Verification
1. Support immediate causes with intact causal chains and source producers.
2. Separate confirmed failures, secondary symptoms and unproved transport/physical causes.
3. Record evidence locally; do not launch HILs or change hardware/authentication without approval.