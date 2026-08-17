#!/usr/bin/env python3
"""B3-D read-only readiness/audit frontend contract checks."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path


def require(source: str, fragment: str, label: str) -> None:
    if fragment not in source:
        raise AssertionError(f"missing {label}: {fragment!r}")


def forbid(source: str, fragment: str, label: str) -> None:
    if fragment in source:
        raise AssertionError(f"forbidden {label}: {fragment!r}")


def static_checks(root: Path) -> None:
    html = (root / "web/control.html").read_text(encoding="utf-8")
    style = (root / "web/style.css").read_text(encoding="utf-8")
    main = (root / "web/control/main_preview_20260810_v5.js").read_text(encoding="utf-8")
    readiness = (root / "web/control/readiness.js").read_text(encoding="utf-8")
    view = (root / "web/control/readiness_view.js").read_text(encoding="utf-8")
    bindings = (root / "web/control/bindings_preview_20260810_v5.js").read_text(encoding="utf-8")

    require(main, "import { createReadinessView } from './readiness_view.js';", "readiness view import")
    require(main, "createReadinessView();", "readiness view initialization")
    for element_id in (
        "b3AuditPanel", "readinessStatus", "readinessRefresh", "readinessAttestation",
        "readinessExpiry", "readinessCommit", "readinessChecks", "readinessBlocking",
        "auditReportFile", "auditReportStatus", "auditReportSummary", "auditReportIdentity",
        "auditReportEvents",
    ):
        require(html, f'id="{element_id}"', f"B3 audit element {element_id}")
    require(readiness, "const READINESS_PATH = '/api/readiness/attestation';", "readiness endpoint")
    require(readiness, "method: 'GET'", "readiness GET")
    require(readiness, "cache: 'no-store'", "no-store readiness request")
    require(readiness, "authorization_scope", "authorization scope validation")
    require(readiness, "value.expires_at_ms - value.issued_at_ms > 300000", "300 second lifetime")
    require(view, "delete core.report_id", "report core hash exclusion")
    require(view, "报告 hash 校验失败", "report hash fail-closed")
    require(view, "clearReport(root, '未载入报告 / 已锁定');", "network report clearing")
    require(view, "clearReadiness(root, `就绪证明不可用 / 已锁定：${error.message}`);", "network readiness clearing")
    require(view, "current !== generation", "stale readiness response guard")
    for name, source in (("readiness", readiness), ("readiness_view", view)):
        for fragment in ("method: 'POST'", ".post(", "/api/command/", "localStorage", "sessionStorage"):
            forbid(source, fragment, f"control or cached state in {name}")
    # B1 locks must remain present in the active page and bindings.
    require(html, 'id="startMotionTestSequence" class="secondary" disabled', "motion sequence lock")
    require(html, 'id="startSelectedAcupoints" disabled', "selected acupoint lock")
    require(html, 'id="startAcupointSequence" class="secondary" disabled', "all acupoints lock")
    require(bindings, "if (elements.startSelectedAcupoints.disabled) return;", "selected lock guard")
    require(bindings, "if (elements.startAcupointSequence.disabled) return;", "all lock guard")
    require(style, ".b3-audit-grid", "desktop B3 layout")
    require(style, "@media (max-width: 900px)", "mobile B3 layout")
    print("PASS: B3 readiness/audit frontend is GET-only, hash-checked, fail-closed, and preserves B1 locks")


NODE_HARNESS = r"""
import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { getReadinessAttestation, validateAttestation } from './readiness.mjs';
import { stableJson, verifyReport } from './readiness_view.mjs';

const fixed = {
  schema_version: 'b3.v1', ok: true,
  motor_command_written: false, execution_allowed: false,
  entity_action_authorized: false, nano_deployment_authorized: false,
  authorization_scope: 'software_precheck_only', attestation_id: 'fixture',
  issued_at_ms: 1000, expires_at_ms: 2000,
  source_state: { command_seq: 0, target_command_seq: 0, endpoint_target_seq: 0 },
  source_fingerprint: 'fixture-source', software_commit: 'fixture-commit',
  config_hashes: {}, checks: [], blocking_reasons: [],
};
const clone = (value) => JSON.parse(JSON.stringify(value));
assert.equal(validateAttestation(clone(fixed), 1500).attestation_id, 'fixture');
for (const mutate of [
  (x) => { x.schema_version = 'b3.v0'; },
  (x) => { x.execution_allowed = true; },
  (x) => { x.expires_at_ms = 400000; },
  (x) => { x.issued_at_ms = 1600; x.expires_at_ms = 1700; },
  (x) => { delete x.source_state.command_seq; },
]) {
  const payload = clone(fixed);
  mutate(payload);
  assert.throws(() => validateAttestation(payload, 1500));
}
assert.throws(() => validateAttestation(clone(fixed), 2500));

const requests = [];
const fetchMock = async (path, options) => {
  requests.push({ path, options });
  return { ok: true, status: 200, json: async () => clone(fixed) };
};
assert.equal((await getReadinessAttestation(fetchMock, () => 1500)).ok, true);
assert.deepEqual(requests, [{ path: '/api/readiness/attestation', options: { method: 'GET', cache: 'no-store', headers: { Accept: 'application/json' } } }]);
await assert.rejects(getReadinessAttestation(async () => { throw new Error('offline'); }, () => 1500));

const core = {
  schema_version: 'b3.audit-report.v1', valid: true,
  motor_command_written: false, execution_allowed: false,
  entity_action_authorized: false, nano_deployment_authorized: false,
  source_commit: 'fixture', events: [],
};
const reportHash = createHash('sha256').update(stableJson(core)).digest('hex');
const report = { ...core, report_id: `b3-audit-${reportHash.slice(0, 16)}`, report_hash: reportHash };
assert.equal((await verifyReport(report)).report_id, report.report_id);
const tampered = { ...report, source_commit: 'tampered' };
await assert.rejects(verifyReport(tampered));
console.log('PASS: B3 readiness expiry/schema/fixed-field/network and report hash checks');
"""


def node_checks(root: Path, node: Path) -> None:
    with tempfile.TemporaryDirectory(prefix="b3d-node-") as temp_name:
        temp = Path(temp_name)
        readiness = (root / "web/control/readiness.js").read_text(encoding="utf-8")
        view = (root / "web/control/readiness_view.js").read_text(encoding="utf-8")
        (temp / "readiness.mjs").write_text(readiness, encoding="utf-8")
        (temp / "readiness_view.mjs").write_text(view.replace("'./readiness.js'", "'./readiness.mjs'"), encoding="utf-8")
        harness = temp / "harness.mjs"
        harness.write_text(NODE_HARNESS, encoding="utf-8")
        subprocess.run([str(node), "--check", str(temp / "readiness.mjs")], check=True, cwd=root)
        subprocess.run([str(node), "--check", str(temp / "readiness_view.mjs")], check=True, cwd=root)
        subprocess.run([str(node), str(harness)], check=True, cwd=root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--node", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    static_checks(root)
    node = args.node or shutil.which("node")
    if node:
        node_checks(root, Path(node).resolve())
    else:
        print("SKIP: Node.js runtime checks (not installed on zzq)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
