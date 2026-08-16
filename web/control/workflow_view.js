import { workflowClient } from './workflow.js';

const STATE_LABELS = Object.freeze({
  offline: '离线',
  fault: '故障',
  locked: '已锁定',
  storage: '收纳',
  standby: '待机',
  vision_blocked: '视觉阻塞',
  ready_for_preview: '可生成预览',
  preview_blocked: '预览阻塞',
});

const CHECK_LABELS = Object.freeze({ pass: '通过', fail: '失败', unknown: '未知' });
const PHASE_LABELS = Object.freeze({
  lift: '抬升',
  side_transit: '侧向转运',
  preview_approach: '预览接近',
  preview_retract: '预览撤回',
  return_transit: '返回转运',
  lower: '下降',
});

function requiredElement(root, id) {
  const element = root.getElementById(id);
  if (!element) throw new Error(`workflow view element missing: ${id}`);
  return element;
}

function replaceText(element, value) {
  element.textContent = value;
}

function createElement(root, tag, className, text) {
  const element = root.createElement(tag);
  if (className) element.className = className;
  if (text !== undefined) element.textContent = text;
  return element;
}

function renderEmptyList(root, container, text) {
  container.replaceChildren(createElement(root, 'p', 'workflow-empty', text));
}

function renderReasons(root, container, reasons) {
  if (!reasons.length) {
    renderEmptyList(root, container, '后端未返回阻塞原因');
    return;
  }
  const rows = reasons.map((reason) => {
    const row = createElement(root, 'div', `workflow-reason severity-${reason.severity}`);
    row.append(
      createElement(root, 'strong', '', reason.code),
      createElement(root, 'span', '', `${reason.source} / ${reason.severity}`),
      createElement(root, 'p', '', reason.message || '--'),
    );
    return row;
  });
  container.replaceChildren(...rows);
}

function renderActions(root, container, actions) {
  if (!actions.length) {
    renderEmptyList(root, container, '无只读动作');
    return;
  }
  container.replaceChildren(...actions.map((action) =>
    createElement(root, 'span', 'workflow-action', action)));
}

function renderChecks(root, container, checks) {
  if (!checks.length) {
    renderEmptyList(root, container, '无自检明细');
    return;
  }
  const rows = checks.map((check) => {
    const row = createElement(root, 'div', `workflow-check status-${check.status}`);
    const heading = createElement(root, 'div', 'workflow-check-heading');
    heading.append(
      createElement(root, 'strong', '', check.id),
      createElement(root, 'span', `workflow-check-status status-${check.status}`, CHECK_LABELS[check.status]),
    );
    row.append(
      heading,
      createElement(root, 'p', '', check.observed || '--'),
      createElement(root, 'small', '', `${check.blocking ? 'blocking' : 'informational'} / ${check.reason_code || 'no_reason_code'}`),
    );
    return row;
  });
  container.replaceChildren(...rows);
}

function formatJoints(waypoint) {
  const joints = waypoint.joints;
  return [
    `K0 ${(joints.k0_m * 1000).toFixed(1)} mm`,
    `K1 ${joints.k1_rad.toFixed(3)} rad`,
    `K2 ${joints.k2_rad.toFixed(3)} rad`,
    `K3 ${joints.k3_rad.toFixed(3)} rad`,
    `K4 ${joints.k4_rad.toFixed(3)} rad`,
  ].join(' / ');
}

function renderSegments(root, container, segments) {
  if (!segments.length) {
    renderEmptyList(root, container, '路线不包含任何分段');
    return;
  }
  const rows = segments.map((segment) => {
    const preflight = segment.preflight;
    const row = createElement(root, 'article', `workflow-segment ${preflight.ok ? 'status-pass' : 'status-fail'}`);
    const heading = createElement(root, 'div', 'workflow-segment-heading');
    heading.append(
      createElement(root, 'strong', '', segment.segment_id),
      createElement(root, 'span', `workflow-check-status ${preflight.ok ? 'status-pass' : 'status-fail'}`, preflight.ok ? '预检通过' : '预检失败'),
    );
    const diagnostics = createElement(root, 'dl', 'workflow-segment-diagnostics');
    const diagnosticsData = [
      ['阶段', `${PHASE_LABELS[segment.phase]} (${segment.phase})`],
      ['原因', preflight.reason_code],
      ['碰撞轴/链节', preflight.collision_link || '--'],
      ['障碍物', preflight.collision_obstacle || '--'],
      ['路径位置', `${(preflight.path_fraction * 100).toFixed(1)}%`],
      ['碰撞检查', preflight.collision_checked ? '已执行' : '未执行'],
    ];
    for (const [term, value] of diagnosticsData) {
      diagnostics.append(
        createElement(root, 'dt', '', term),
        createElement(root, 'dd', '', value),
      );
    }
    row.append(
      heading,
      diagnostics,
      createElement(root, 'p', 'workflow-waypoint', `起点 ${formatJoints(segment.start)}`),
      createElement(root, 'p', 'workflow-waypoint', `目标 ${formatJoints(segment.target)}`),
    );
    return row;
  });
  container.replaceChildren(...rows);
}

function unavailableText(error) {
  return `不可用 / 已锁定：${error?.message || '只读接口连接失败'}`;
}

export function createWorkflowView(root = document, client = workflowClient) {
  const elements = {
    panel: requiredElement(root, 'workflowPanel'),
    status: requiredElement(root, 'workflowViewStatus'),
    updated: requiredElement(root, 'workflowUpdatedAt'),
    refresh: requiredElement(root, 'workflowRefresh'),
    state: requiredElement(root, 'workflowStateValue'),
    schema: requiredElement(root, 'workflowSchemaValue'),
    source: requiredElement(root, 'workflowSourceState'),
    actions: requiredElement(root, 'workflowAllowedActions'),
    reasons: requiredElement(root, 'workflowBlockingReasons'),
    summary: requiredElement(root, 'workflowSelfCheckSummary'),
    checks: requiredElement(root, 'workflowChecks'),
    planStatus: requiredElement(root, 'workflowPlanStatus'),
    planId: requiredElement(root, 'workflowPlanId'),
    planHash: requiredElement(root, 'workflowPlanHash'),
    segments: requiredElement(root, 'workflowPlanSegments'),
    sides: [...root.querySelectorAll('[data-workflow-side]')],
  };
  let selectedSide = 'left';
  let refreshGeneration = 0;
  let destroyed = false;

  function setOverallStatus(kind, text) {
    elements.panel.dataset.workflowStatus = kind;
    elements.status.className = kind === 'loaded' ? 'pill warn' : 'pill bad';
    replaceText(elements.status, text);
  }

  function clearStaleView(message) {
    setOverallStatus('locked', message);
    replaceText(elements.updated, '更新时间：--');
    replaceText(elements.state, '--');
    replaceText(elements.schema, '--');
    replaceText(elements.source, '--');
    replaceText(elements.summary, '--');
    replaceText(elements.planStatus, '路线预览不可用 / 执行已锁定');
    elements.planStatus.className = 'pill bad';
    replaceText(elements.planId, '--');
    replaceText(elements.planHash, '--');
    renderEmptyList(root, elements.actions, '状态不可用');
    renderEmptyList(root, elements.reasons, '状态不可用');
    renderEmptyList(root, elements.checks, '自检不可用');
    renderEmptyList(root, elements.segments, '路线预览不可用');
  }

  function renderState(payload) {
    replaceText(elements.state, `${STATE_LABELS[payload.workflow_state]} (${payload.workflow_state})`);
    replaceText(elements.schema, payload.schema_version);
    const source = payload.source_state;
    replaceText(elements.source, `command ${source.command_seq} / target ${source.target_command_seq} / endpoint ${source.endpoint_target_seq}`);
    renderActions(root, elements.actions, payload.allowed_actions);
    renderReasons(root, elements.reasons, payload.blocking_reasons);
  }

  function renderSelfCheck(payload) {
    const summary = payload.self_check_summary;
    replaceText(elements.summary, `${summary.status} / 通过 ${summary.passed} / 失败 ${summary.failed} / 未知 ${summary.unknown}`);
    renderChecks(root, elements.checks, payload.checks);
  }

  function renderPlan(payload) {
    replaceText(elements.planStatus, `${payload.plan.side} / ${payload.preview_valid ? '预览有效' : '预览阻塞'} / execution_allowed=false`);
    elements.planStatus.className = payload.preview_valid ? 'pill warn' : 'pill bad';
    replaceText(elements.planId, payload.plan_id);
    replaceText(elements.planHash, payload.plan_hash);
    renderSegments(root, elements.segments, payload.plan.segments);
  }

  async function refresh() {
    const generation = ++refreshGeneration;
    const side = selectedSide;
    clearStaleView('正在读取只读状态 / 执行已锁定');
    elements.refresh.disabled = true;
    const results = await Promise.allSettled([
      client.getState(),
      client.getSelfCheck(),
      client.getMotionPlan(side),
    ]);
    if (destroyed || generation !== refreshGeneration) return;

    const [stateResult, checkResult, planResult] = results;
    if (stateResult.status === 'fulfilled') renderState(stateResult.value);
    else renderEmptyList(root, elements.reasons, unavailableText(stateResult.reason));

    if (checkResult.status === 'fulfilled') renderSelfCheck(checkResult.value);
    else {
      replaceText(elements.summary, unavailableText(checkResult.reason));
      renderEmptyList(root, elements.checks, '自检不可用');
    }

    if (planResult.status === 'fulfilled') renderPlan(planResult.value);
    else {
      replaceText(elements.planStatus, unavailableText(planResult.reason));
      elements.planStatus.className = 'pill bad';
      renderEmptyList(root, elements.segments, '路线预览不可用');
    }

    const failures = results.filter((result) => result.status === 'rejected');
    if (failures.length) {
      setOverallStatus('locked', `不可用 / 已锁定：${failures.length} 个只读接口未通过`);
    } else {
      setOverallStatus('loaded', '后端只读数据已更新 / 执行已锁定');
    }
    replaceText(elements.updated, `更新时间：${new Date().toLocaleString('zh-CN', { hour12: false })}`);
    elements.refresh.disabled = false;
  }

  function selectSide(side) {
    if (side !== 'left' && side !== 'right') return;
    selectedSide = side;
    for (const button of elements.sides) {
      const selected = button.dataset.workflowSide === side;
      button.classList.toggle('selected', selected);
      button.setAttribute('aria-pressed', String(selected));
    }
    void refresh();
  }

  const refreshHandler = () => void refresh();
  elements.refresh.addEventListener('click', refreshHandler);
  for (const button of elements.sides) {
    button.addEventListener('click', () => selectSide(button.dataset.workflowSide));
  }
  selectSide(selectedSide);

  return Object.freeze({
    refresh,
    selectSide,
    destroy() {
      destroyed = true;
      refreshGeneration += 1;
      elements.refresh.removeEventListener('click', refreshHandler);
    },
  });
}
