#!/usr/bin/env python3
"""B2-D read-only workflow frontend contract checks."""

from __future__ import annotations

import argparse
import subprocess
import tempfile
from pathlib import Path


def require(source: str, fragment: str, label: str) -> None:
    if fragment not in source:
        raise AssertionError(f"missing {label}: {fragment!r}")


def forbid(source: str, fragment: str, label: str) -> None:
    if fragment in source:
        raise AssertionError(f"forbidden {label}: {fragment!r}")


def static_checks(root: Path) -> dict[str, str]:
    paths = {
        "html": root / "web/control.html",
        "style": root / "web/style.css",
        "api": root / "web/control/api.js",
        "workflow": root / "web/control/workflow.js",
        "view": root / "web/control/workflow_view.js",
        "main": root / "web/control/main_preview_20260810_v5.js",
        "entry": root / "web/control_preview_20260810_v5.js",
        "bindings": root / "web/control/bindings_preview_20260810_v5.js",
    }
    sources = {name: path.read_text(encoding="utf-8") for name, path in paths.items()}

    require(sources["html"], 'src="/control_preview_20260810_v5.js"', "active HTML entry")
    require(sources["entry"], "./control/main_preview_20260810_v5.js", "active main import")
    require(sources["main"], "import { createWorkflowView } from './workflow_view.js';", "workflow view import")
    require(sources["main"], "createWorkflowView();", "workflow view initialization")

    for element_id in (
        "workflowPanel", "workflowViewStatus", "workflowRefresh",
        "workflowStateValue", "workflowAllowedActions", "workflowBlockingReasons",
        "workflowSelfCheckSummary", "workflowChecks", "workflowPlanStatus",
        "workflowPlanId", "workflowPlanHash", "workflowPlanSegments",
    ):
        require(sources["html"], f'id="{element_id}"', f"workflow element {element_id}")
    require(sources["html"], 'data-workflow-side="left"', "left plan selector")
    require(sources["html"], 'data-workflow-side="right"', "right plan selector")

    # Preserve the G1/B1-D automatic-execution locks in the actual entry.
    require(sources["html"], 'id="startMotionTestSequence" class="secondary" disabled', "motion sequence lock")
    require(sources["html"], 'id="startSelectedAcupoints" disabled', "selected acupoint lock")
    require(sources["html"], 'id="startAcupointSequence" class="secondary" disabled', "all acupoints lock")
    require(sources["bindings"], "if (elements.startSelectedAcupoints.disabled) return;", "selected lock click guard")
    require(sources["bindings"], "if (elements.startAcupointSequence.disabled) return;", "all lock click guard")

    for path in (
        "/api/workflow/state",
        "/api/workflow/self_check",
        "/api/motion_plan/preview?side=${side}",
    ):
        require(sources["api"], path, f"fixed read-only API {path}")
    if sources["api"].count("method: 'GET'") < 3:
        raise AssertionError("all three B2 API methods must explicitly use GET")
    require(sources["workflow"], "payload.motor_command_written, false", "motor write fail-closed check")
    require(sources["workflow"], "payload.execution_locked, true", "workflow execution lock check")
    require(sources["workflow"], "payload.execution_allowed, false", "plan execution lock check")
    require(sources["workflow"], "b2.motion-plan.v1", "motion plan schema check")
    require(sources["view"], "clearStaleView('正在读取只读状态 / 执行已锁定');", "stale success clearing")
    require(sources["view"], "Promise.allSettled", "independent fail-closed refresh")
    require(sources["view"], "generation !== refreshGeneration", "rapid refresh stale-response guard")

    for name in ("workflow", "view"):
        for fragment in (
            "/api/command/", "/api/acupoint_sequence/start",
            "/api/motion_test/sequence/start", "method: 'POST'", ".post(",
            "localStorage", "sessionStorage", "fetch(",
        ):
            forbid(sources[name], fragment, f"control or cached state in {name}")

    require(sources["style"], ".workflow-overview-grid", "workflow desktop layout")
    require(sources["style"], "@media (max-width: 560px)", "workflow mobile layout")
    print("PASS: B2-D static entry, GET-only, fail-closed, and B1 lock checks")
    return sources


NODE_HARNESS = r"""
import assert from 'node:assert/strict';
import { api, ApiError } from './api.mjs';
import {
  WorkflowContractError,
  createWorkflowClient,
  validateMotionPlanPreview,
  validateWorkflowSelfCheck,
  validateWorkflowState,
} from './workflow.mjs';

const clone = (value) => JSON.parse(JSON.stringify(value));
const common = {
  schema_version: 'b2.v1',
  ok: true,
  motor_command_written: false,
  source_state: { command_seq: 4, target_command_seq: 5, endpoint_target_seq: 6 },
  blocking_reasons: [{
    code: 'missing_formal_camera_extrinsics', source: 'formal_camera_extrinsics',
    severity: 'blocking', message: 'formal_extrinsics_missing',
  }],
};
const state = {
  ...clone(common), workflow_state: 'vision_blocked',
  allowed_actions: ['view_state', 'view_self_check', 'refresh_state', 'preview_motion_plan'],
  self_check_summary: { status: 'blocked', passed: 2, failed: 1, unknown: 0 },
  plan_id: null, plan_hash: null, execution_locked: true,
};
const selfCheck = {
  ...clone(common), self_check_summary: { status: 'blocked', passed: 1, failed: 1, unknown: 1 },
  checks: [
    { id: 'automatic_execution_lock', status: 'pass', blocking: false, reason_code: null, observed: 'execution_allowed_false' },
    { id: 'formal_camera_extrinsics', status: 'fail', blocking: true, reason_code: 'missing_formal_camera_extrinsics', observed: 'formal_extrinsics_missing' },
    { id: 'axis_online', status: 'unknown', blocking: true, reason_code: 'axis_offline', observed: 'unknown' },
  ],
};
const segment = {
  segment_id: 'segment-01-lift', phase: 'lift',
  start: { joints: { k0_m: 0, k1_rad: 0, k2_rad: 0, k3_rad: 0, k4_rad: 0 } },
  target: { joints: { k0_m: 0.2, k1_rad: 0, k2_rad: 0, k3_rad: 0, k4_rad: 0 } },
  preflight: {
    ok: false, collision_checked: true, reason_code: 'collision_detected',
    collision_link: 'K0_lift', collision_obstacle: 'cabinet', path_fraction: 0.25,
  },
};
const plan = {
  ...clone(common),
  plan_id: 'b2-0123456789abcdef',
  plan_hash: `sha256:${'0'.repeat(64)}`,
  preview_valid: false,
  execution_allowed: false,
  plan: {
    schema_version: 'b2.motion-plan.v1', side: 'left', coordinate_frame: 'robot_base',
    units: { linear: 'm', angular: 'rad' }, formal_use_allowed: false,
    segments: [segment],
  },
};

assert.equal(validateWorkflowState(clone(state)).workflow_state, 'vision_blocked');
assert.equal(validateWorkflowSelfCheck(clone(selfCheck)).checks.length, 3);
assert.equal(validateMotionPlanPreview(clone(plan), 'left').plan.segments.length, 1);

const rejected = [
  (p) => { delete p.schema_version; },
  (p) => { p.schema_version = 'b2.v0'; },
  (p) => { p.motor_command_written = true; },
  (p) => { delete p.source_state.command_seq; },
  (p) => { p.source_state.target_command_seq = '5'; },
  (p) => { p.workflow_state = 'execute_ready'; },
  (p) => { p.allowed_actions.push('execute_plan'); },
  (p) => { p.execution_locked = false; },
];
for (const mutate of rejected) {
  const payload = clone(state);
  mutate(payload);
  assert.throws(() => validateWorkflowState(payload), WorkflowContractError);
}
const badCheck = clone(selfCheck);
badCheck.checks[0].status = 'maybe';
assert.throws(() => validateWorkflowSelfCheck(badCheck), WorkflowContractError);
const unknownSummary = clone(selfCheck);
unknownSummary.self_check_summary.status = 'execute_ready';
assert.throws(() => validateWorkflowSelfCheck(unknownSummary), WorkflowContractError);
const staleSummary = clone(selfCheck);
staleSummary.self_check_summary.passed = 99;
assert.throws(() => validateWorkflowSelfCheck(staleSummary), WorkflowContractError);
const wrongSide = clone(plan);
wrongSide.plan.side = 'right';
assert.throws(() => validateMotionPlanPreview(wrongSide, 'left'), WorkflowContractError);
const allowedPlan = clone(plan);
allowedPlan.execution_allowed = true;
assert.throws(() => validateMotionPlanPreview(allowedPlan, 'left'), WorkflowContractError);
const missingCollision = clone(plan);
delete missingCollision.plan.segments[0].preflight.collision_obstacle;
assert.throws(() => validateMotionPlanPreview(missingCollision, 'left'), WorkflowContractError);

const requests = [];
globalThis.fetch = async (path, options = {}) => {
  requests.push({ path, options });
  const payload = path === '/api/workflow/state'
    ? state
    : path === '/api/workflow/self_check'
      ? selfCheck
      : plan;
  return { ok: true, status: 200, json: async () => clone(payload) };
};
await api.getWorkflowState();
await api.getWorkflowSelfCheck();
await api.getMotionPlanPreview('left');
assert.deepEqual(requests.map(({ path }) => path), [
  '/api/workflow/state',
  '/api/workflow/self_check',
  '/api/motion_plan/preview?side=left',
]);
for (const request of requests) {
  assert.equal(request.options.method, 'GET');
  assert.equal(request.options.body, undefined);
  assert.equal(request.options.cache, 'no-store');
}
await assert.rejects(api.getMotionPlanPreview('center'), ApiError);
assert.equal(requests.length, 3);

const client = createWorkflowClient({
  getWorkflowState: async () => clone(state),
  getWorkflowSelfCheck: async () => clone(selfCheck),
  getMotionPlanPreview: async () => clone(plan),
});
assert.equal((await client.getState()).execution_locked, true);
assert.equal((await client.getSelfCheck()).checks.length, 3);
assert.equal((await client.getMotionPlan('left')).execution_allowed, false);

console.log('PASS: B2-D JS validators and fixed GET request audit');
"""


def node_checks(root: Path, sources: dict[str, str], node: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="b2d-node-") as temp_name:
        temp = Path(temp_name)
        (temp / "api.mjs").write_text(sources["api"], encoding="utf-8")
        workflow = sources["workflow"].replace("'./api.js'", "'./api.mjs'")
        (temp / "workflow.mjs").write_text(workflow, encoding="utf-8")
        (temp / "harness.mjs").write_text(NODE_HARNESS, encoding="utf-8")
        subprocess.run([str(node), "--check", str(temp / "api.mjs")], check=True, cwd=root)
        subprocess.run([str(node), "--check", str(temp / "workflow.mjs")], check=True, cwd=root)
        subprocess.run([str(node), str(temp / "harness.mjs")], check=True, cwd=root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--node", type=Path, help="optional Node.js executable for runtime contract checks")
    args = parser.parse_args()
    root = args.root.resolve()
    sources = static_checks(root)
    if args.node:
        node_checks(root, sources, args.node.resolve())
    else:
        print("SKIP: Node.js runtime checks (pass --node to enable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
