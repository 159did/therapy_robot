import { getReadinessAttestation } from './readiness.js';

const FIXED_FALSE_FIELDS = ['motor_command_written', 'execution_allowed', 'entity_action_authorized', 'nano_deployment_authorized'];

function object(value) {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function stableJson(value) {
  if (Array.isArray(value)) return `[${value.map(stableJson).join(',')}]`;
  if (object(value)) return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stableJson(value[key])}`).join(',')}}`;
  return JSON.stringify(value);
}

async function sha256Hex(value) {
  if (!globalThis.crypto?.subtle) throw new Error('browser crypto unavailable');
  const bytes = new TextEncoder().encode(stableJson(value));
  const digest = await globalThis.crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

function text(root, id, value) {
  const node = root.getElementById(id);
  if (node) node.textContent = value;
}

function list(root, id, values, empty = '--') {
  const node = root.getElementById(id);
  if (!node) return;
  node.replaceChildren();
  const items = Array.isArray(values) ? values : [];
  if (!items.length) {
    const emptyNode = root.createElement('p');
    emptyNode.className = 'b3-audit-empty';
    emptyNode.textContent = empty;
    node.append(emptyNode);
    return;
  }
  for (const value of items) {
    const item = root.createElement('li');
    item.textContent = typeof value === 'string' ? value : JSON.stringify(value);
    node.append(item);
  }
}

function clearReport(root, message = '未载入报告 / 已锁定') {
  text(root, 'auditReportStatus', message);
  text(root, 'auditReportSummary', '--');
  text(root, 'auditReportIdentity', '--');
  text(root, 'auditReportEvents', '--');
  const panel = root.getElementById('b3AuditPanel');
  if (panel) panel.dataset.auditStatus = 'locked';
}

function clearReadiness(root, message = '就绪证明不可用 / 已锁定') {
  text(root, 'readinessStatus', message);
  text(root, 'readinessAttestation', '--');
  text(root, 'readinessExpiry', '--');
  text(root, 'readinessCommit', '--');
  list(root, 'readinessChecks', [], '自检不可用');
  list(root, 'readinessBlocking', [], '阻塞原因不可用');
  const panel = root.getElementById('b3AuditPanel');
  if (panel) panel.dataset.readinessStatus = 'unknown';
}

function renderReadiness(root, attestation) {
  text(root, 'readinessStatus', attestation.ok ? '软件前置条件已读取 / 执行仍锁定' : '前置条件阻塞 / 执行已锁定');
  text(root, 'readinessAttestation', attestation.attestation_id);
  text(root, 'readinessExpiry', `${new Date(attestation.issued_at_ms).toLocaleString('zh-CN', { hour12: false })} - ${new Date(attestation.expires_at_ms).toLocaleString('zh-CN', { hour12: false })}`);
  text(root, 'readinessCommit', attestation.software_commit);
  list(root, 'readinessChecks', attestation.checks, '无自检明细');
  list(root, 'readinessBlocking', attestation.blocking_reasons, '无阻塞原因');
  const panel = root.getElementById('b3AuditPanel');
  if (panel) panel.dataset.readinessStatus = attestation.ok ? 'observed' : 'blocked';
}

function validateReportShape(report) {
  if (!object(report) || report.schema_version !== 'b3.audit-report.v1') throw new Error('报告 schema 未知');
  if (typeof report.valid !== 'boolean') throw new Error('报告 valid 缺失');
  for (const key of FIXED_FALSE_FIELDS) {
    if (report[key] !== false) throw new Error(`${key} 必须为 false`);
  }
  if (typeof report.report_id !== 'string' || !report.report_id.startsWith('b3-audit-')) throw new Error('报告 ID 无效');
  if (typeof report.report_hash !== 'string' || !/^[0-9a-f]{64}$/.test(report.report_hash)) throw new Error('报告 hash 无效');
  return report;
}

async function verifyReport(report) {
  const checked = validateReportShape(report);
  const core = { ...checked };
  delete core.report_id;
  delete core.report_hash;
  const expected = await sha256Hex(core);
  if (expected !== checked.report_hash || checked.report_id !== `b3-audit-${expected.slice(0, 16)}`) {
    throw new Error('报告 hash 校验失败');
  }
  return checked;
}

function renderReport(root, report) {
  text(root, 'auditReportStatus', report.valid ? '报告完整 / 仍为只读事实' : '报告标记为无效 / 已锁定');
  text(root, 'auditReportSummary', `源码 ${report.source_commit || '--'}；事件 ${Array.isArray(report.events) ? report.events.length : 0}；execution_allowed=false`);
  text(root, 'auditReportIdentity', `${report.report_id} / ${report.report_hash}`);
  text(root, 'auditReportEvents', Array.isArray(report.events) ? report.events.map((event) => `${event.sequence} ${event.event_type} ${event.event_hash}`).join(' | ') : '--');
  const panel = root.getElementById('b3AuditPanel');
  if (panel) panel.dataset.auditStatus = report.valid ? 'loaded' : 'locked';
}

export function createReadinessView(root = document, options = {}) {
  const fetchImpl = options.fetchImpl || fetch;
  const now = options.now || (() => Date.now());
  const refresh = root.getElementById('readinessRefresh');
  const fileInput = root.getElementById('auditReportFile');
  let generation = 0;

  async function refreshReadiness() {
    const current = ++generation;
    clearReport(root, '正在读取报告 / 执行已锁定');
    clearReadiness(root, '正在读取软件前置条件 / 执行已锁定');
    try {
      const attestation = await getReadinessAttestation(fetchImpl, now);
      if (current !== generation) return;
      renderReadiness(root, attestation);
    } catch (error) {
      if (current !== generation) return;
      clearReport(root, '未载入报告 / 已锁定');
      clearReadiness(root, `就绪证明不可用 / 已锁定：${error.message}`);
    }
  }

  async function loadReport(file) {
    generation += 1;
    clearReport(root, '正在校验报告 / 执行已锁定');
    if (!file) return;
    try {
      const report = await verifyReport(JSON.parse(await file.text()));
      renderReport(root, report);
    } catch (error) {
      clearReport(root, `报告不可用 / 已锁定：${error.message}`);
    }
  }

  refresh?.addEventListener('click', () => void refreshReadiness());
  fileInput?.addEventListener('change', () => void loadReport(fileInput.files?.[0]));
  void refreshReadiness();
  return Object.freeze({ refresh: refreshReadiness, loadReport });
}

export { stableJson, verifyReport };
