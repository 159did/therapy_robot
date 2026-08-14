import { updateThreeRobot } from '../three_robot_view.js?rev=20260726-1945';
import { api } from './api.js';
import { elements } from './dom_preview_20260810.js';
import { bindCommands } from './bindings_preview_20260810_v5.js';
import { hydrateEndpointInputsFromState, estimateEndpointFromState, renderEndpointBackendStatus, renderEndpointPrecheck } from './endpoint.js';
import { buildAxisMapIndex, hydrateAxisTargetInputsFromState, loadPersistedDrafts, renderInputRangeHints, renderStatusCards, showError, syncPhysicalInputsFromState } from './state.js';
import { renderJointJogState } from './joint_jog.js';

const physicalInputDirty = new Set();
let latestState = null;
let stateHydrated = false;
let lastUiRenderAt = 0;
let lastSlowRenderAt = 0;
let latestAcupointData = null;
const selectedAcupoints = new Set();
let previewActive = false;
let previewToken = 0;

function getLatestState() {
  return latestState;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"]/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[ch]);
}

function stepLabel(step) {
  return {
    planned: '已规划',
    start: '开始',
    approach: '法向预备点',
    massage: '穴位点',
    travel: '上方平移',
    press: 'Z向下',
    lift: 'Z抬升',
    dwell: '停留中',
    done: '完成',
  }[step] || step || '--';
}

function renderAcupointSequenceProgress(progress) {
  if (!elements.acupointSequenceProgress) return;
  if (!progress) {
    elements.acupointSequenceProgress.textContent = '等待进度...';
    return;
  }
  const points = Array.isArray(progress.points) ? progress.points : [];
  const summary = `已完成 ${progress.completed || 0}/${progress.reachable || 0} 个可达穴位；跳过 ${progress.skipped || 0} 个；当前：${escapeHtml(progress.current_name || '--')} ${escapeHtml(stepLabel(progress.current_step))}`;
  const list = points.map((point) => {
    const status = escapeHtml(point.status || 'pending');
    const message = point.message ? `<span>${escapeHtml(point.message)}</span>` : `<span>${escapeHtml(stepLabel(point.step))}</span>`;
    return `<div class="sequence-item ${status}"><b>${point.index}. ${escapeHtml(point.name || '--')}</b>${message}</div>`;
  }).join('');
  elements.acupointSequenceProgress.innerHTML = `<div class="sequence-summary">${summary}<br>${escapeHtml(progress.message || '')}</div><div class="sequence-list">${list}</div>`;
}

function renderAcupointSequenceStatus(status) {
  if (!elements.acupointSequenceStatus) return;
  const running = Boolean(status?.running);
  elements.acupointSequenceStatus.textContent = running ? '自动序列: 运行中' : '自动序列: 已停止';
  elements.acupointSequenceStatus.className = running ? 'pill good' : 'pill';
  renderAcupointSequenceProgress(status?.progress);
  if (elements.acupointSequenceLog) {
    elements.acupointSequenceLog.textContent = status?.log_tail || '暂无日志';
  }
}

function renderMotionTestStatus(status) {
  if (!elements.motionTestStatus) return;
  const running = Boolean(status?.running);
  if (!running && elements.motionTestStatus.dataset.simulationOnly === 'true') return;
  if (running) {
    delete elements.motionTestStatus.dataset.simulationOnly;
    delete elements.motionTestProgress?.dataset.simulationOnly;
  }
  const progress = status?.progress;
  if (running) {
    elements.motionTestStatus.textContent = `测试点: 运行中 ${progress?.completed || 0}/${progress?.total || 0}，当前 ${progress?.current_name || '--'}`;
    elements.motionTestStatus.className = 'pill warn';
  } else if (progress?.error) {
    elements.motionTestStatus.textContent = `测试点: ${progress.error}`;
    elements.motionTestStatus.className = 'pill bad';
  } else if (progress?.message) {
    elements.motionTestStatus.textContent = `测试点: ${progress.message}`;
    elements.motionTestStatus.className = 'pill good';
  }
  if (elements.motionTestProgress) {
    const points = Array.isArray(progress?.points) ? progress.points : [];
    elements.motionTestProgress.textContent = progress
      ? `已完成 ${progress.completed || 0}/${progress.total || 0}；${progress.message || ''}；${points.map((point) => `${point.index}.${point.name}:${point.status}`).join(' | ')}`
      : '等待测试序列...';
  }
  if (elements.motionTestLog) elements.motionTestLog.textContent = status?.log_tail || '暂无日志';
}

function renderAcupointImage() {
  const image = elements.acupointSourceImage;
  const canvas = elements.acupointOverlay;
  if (!image || !canvas || !latestAcupointData || !image.complete || !image.naturalWidth) return;
  const points = latestAcupointData.template_acupoints || latestAcupointData.acupoints || [];
  const rect = image.getBoundingClientRect();
  const ratio = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * ratio));
  canvas.height = Math.max(1, Math.round(rect.height * ratio));
  canvas.style.width = `${rect.width}px`;
  canvas.style.height = `${rect.height}px`;
  const ctx = canvas.getContext('2d');
  ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
  ctx.clearRect(0, 0, rect.width, rect.height);
  const scaleX = rect.width / image.naturalWidth;
  const scaleY = rect.height / image.naturalHeight;
  ctx.font = '600 12px system-ui, sans-serif';
  ctx.lineWidth = 2;
  for (const point of points) {
    if (!point.ok || !Array.isArray(point.pixel)) continue;
    const x = Number(point.pixel[0]) * scaleX;
    const y = Number(point.pixel[1]) * scaleY;
    ctx.beginPath();
    ctx.arc(x, y, 5, 0, Math.PI * 2);
    ctx.fillStyle = '#22c55e';
    ctx.fill();
    ctx.strokeStyle = '#052e16';
    ctx.stroke();
    const label = String(point.name || '--');
    const width = ctx.measureText(label).width + 10;
    ctx.fillStyle = 'rgba(2, 6, 23, 0.82)';
    ctx.fillRect(x + 7, y - 16, width, 19);
    ctx.fillStyle = '#dcfce7';
    ctx.fillText(label, x + 12, y - 2);
  }
}

function renderAcupointCoordinates(data) {
  const points = data?.template_acupoints || data?.acupoints || [];
  if (elements.acupointImageStatus) {
    elements.acupointImageStatus.textContent = `穴位数据: ${points.filter((point) => point.ok).length} 个有效点`;
    elements.acupointImageStatus.className = 'pill good';
  }
  if (elements.acupointCoordinateList) {
    elements.acupointCoordinateList.innerHTML = points.map((point) => {
      const p = Array.isArray(point.point_camera_m) ? point.point_camera_m.map((v) => Number(v) * 1000) : null;
      const n = Array.isArray(point.normal_camera) ? point.normal_camera : null;
      const coordinate = p ? `X ${p[0].toFixed(1)} · Y ${p[1].toFixed(1)} · Z ${p[2].toFixed(1)} mm` : '坐标无效';
      const normal = n ? `N ${n.map((v) => Number(v).toFixed(3)).join(', ')}` : 'N --';
      return `<button type="button" class="acupoint-coordinate-item ${point.ok ? 'selectable' : 'invalid'}" data-acupoint-name="${escapeHtml(point.name || '--')}" ${point.ok ? '' : 'disabled'}><b>${escapeHtml(point.name || '--')}</b><span>${escapeHtml(coordinate)}</span><small>${escapeHtml(normal)}</small><em>${point.ok ? '点击选择' : '不可用'}</em></button>`;
    }).join('');
    for (const item of elements.acupointCoordinateList.querySelectorAll('[data-acupoint-name]')) {
      item.addEventListener('click', () => {
        const name = item.dataset.acupointName;
        if (selectedAcupoints.has(name)) selectedAcupoints.delete(name);
        else selectedAcupoints.add(name);
        item.classList.toggle('selected', selectedAcupoints.has(name));
        item.querySelector('em').textContent = selectedAcupoints.has(name) ? `已选择 ${selectedAcupoints.size} 个` : '点击选择';
      });
    }
  }
  renderAcupointImage();
}

async function loadAcupointData() {
  try {
    latestAcupointData = await api.get('/api/acupoints/latest');
    renderAcupointCoordinates(latestAcupointData);
  } catch (error) {
    if (elements.acupointImageStatus) {
      elements.acupointImageStatus.textContent = `穴位数据: ${error.message}`;
      elements.acupointImageStatus.className = 'pill bad';
    }
  }
}

function renderLivePose(state) {
  if (!elements.livePoseX) return;
  const pose = estimateEndpointFromState(state);
  elements.livePoseX.textContent = `${pose.x.toFixed(1)} mm`;
  elements.livePoseY.textContent = `${pose.y.toFixed(1)} mm`;
  elements.livePoseZ.textContent = `${pose.z.toFixed(1)} mm`;
  elements.livePoseRx.textContent = `${pose.rx.toFixed(1)} deg`;
  elements.livePoseRy.textContent = `${pose.ry.toFixed(1)} deg`;
}

function renderEmbeddedSimulation(state) {
  if (!elements.embeddedThreeView) return;
  if (previewActive) return;
  const fmt = (value) => Number.isFinite(Number(value)) ? Number(value).toFixed(3) : '--';
  const pose = updateThreeRobot(elements.embeddedThreeView, state);
  elements.embeddedEeX.textContent = `x: ${fmt(pose.x_m)} m`;
  elements.embeddedEeY.textContent = `y: ${fmt(pose.y_m)} m`;
  elements.embeddedEeZ.textContent = `z: ${fmt(pose.z_m)} m`;
  elements.embeddedSimMode.textContent = '模式: 五轴绝对编码器反馈';
}

function previewStateFromJoints(state, joints) {
  const preview = JSON.parse(JSON.stringify(state));
  const display = [joints.k0_mm, joints.k1_deg, joints.k2_deg, joints.k3_deg, joints.k4_deg];
  for (let globalAxis = 0; globalAxis < 5; globalAxis += 1) {
    const map = (preview.axis_map || []).find((entry) => entry.global_axis === globalAxis);
    const motor = preview.groups?.[map?.group]?.motors?.[map?.axis];
    if (!map || !motor) continue;
    motor.actual_motor_native = display[globalAxis] / map.motor_native_to_gui_display;
    motor.actual_axis_si = globalAxis === 0 ? display[globalAxis] / 1000 : display[globalAxis] * Math.PI / 180;
  }
  return preview;
}

async function playMotionPreview(points) {
  if (!latestState || !elements.embeddedThreeView || !Array.isArray(points) || !points.length) return;
  const token = ++previewToken;
  previewActive = true;
  const current = [
    Number(latestState.groups?.[0]?.motors?.[0]?.actual_axis_si || 0) * 1000,
    Number(latestState.groups?.[1]?.motors?.[0]?.actual_axis_si || 0) * 180 / Math.PI,
    Number(latestState.groups?.[1]?.motors?.[1]?.actual_axis_si || 0) * 180 / Math.PI,
    Number(latestState.groups?.[2]?.motors?.[0]?.actual_axis_si || 0) * 180 / Math.PI,
    Number(latestState.groups?.[2]?.motors?.[1]?.actual_axis_si || 0) * 180 / Math.PI,
  ];
  let from = current;
  for (const point of points) {
    if (token !== previewToken || !point.ok || !point.joints) break;
    const to = [point.joints.k0_mm, point.joints.k1_deg, point.joints.k2_deg, point.joints.k3_deg, point.joints.k4_deg].map(Number);
    for (let step = 1; step <= 20; step += 1) {
      if (token !== previewToken) return;
      const t = step / 20;
      const values = from.map((value, index) => value + (to[index] - value) * (t * t * (3 - 2 * t)));
      const frame = previewStateFromJoints(latestState, {
        k0_mm: values[0], k1_deg: values[1], k2_deg: values[2], k3_deg: values[3], k4_deg: values[4],
      });
      const pose = updateThreeRobot(elements.embeddedThreeView, frame);
      elements.embeddedEeX.textContent = `x: ${Number(pose.x_m).toFixed(3)} m`;
      elements.embeddedEeY.textContent = `y: ${Number(pose.y_m).toFixed(3)} m`;
      elements.embeddedEeZ.textContent = `z: ${Number(pose.z_m).toFixed(3)} m`;
      elements.embeddedSimMode.textContent = `模式: 新轨迹纯仿真 ${point.index}/${points.length}`;
      await new Promise((resolve) => window.setTimeout(resolve, 30));
    }
    from = to;
  }
  await new Promise((resolve) => window.setTimeout(resolve, 800));
  if (token === previewToken) previewActive = false;
}

function renderReconcileState(state) {
  if (!elements.reconcileCurrent) return;
  const actual = Array(5).fill(0);
  const target = Array(5).fill(0);
  for (const group of state.groups || []) {
    for (const motor of group.motors || []) {
      if (!motor.configured) continue;
      const mapping = (state.axis_map || []).find((entry) => entry.group === group.group && entry.axis === motor.axis);
      if (!mapping || mapping.global_axis < 0 || mapping.global_axis > 4) continue;
      actual[mapping.global_axis] = Number(motor.actual_axis_si || 0);
      target[mapping.global_axis] = Number(motor.target_axis_si || 0);
    }
  }
  const deg = (v) => (v * 180 / Math.PI).toFixed(3);
  const sim = state.simulation || {};
  elements.reconcileCurrent.textContent = [
    `actual: K0 ${(actual[0] * 1000).toFixed(3)} mm | K1 ${deg(actual[1])}° | K2 ${deg(actual[2])}° | K3 ${deg(actual[3])}° | K4 ${deg(actual[4])}°`,
    `target: K0 ${(target[0] * 1000).toFixed(3)} mm | K1 ${deg(target[1])}° | K2 ${deg(target[2])}° | K3 ${deg(target[3])}° | K4 ${deg(target[4])}°`,
    `FK end: X ${(Number(sim.end_effector_x_m || 0) * 1000).toFixed(1)} mm, Y ${(Number(sim.end_effector_y_m || 0) * 1000).toFixed(1)} mm, Z ${(Number(sim.end_effector_z_m || 0) * 1000).toFixed(1)} mm`,
    `system: ${state.system_state || '--'} | emergency_stop: ${state.emergency_stop ? 'ON' : 'off'} | limit: ${state.control?.limit_alarm ? 'ON' : 'off'} | collision: ${state.control?.collision?.alarm ? 'ON' : 'off'}`,
  ].join('\n');
}

function renderState(state) {
  latestState = state;
  renderReconcileState(state);
  const now = performance.now();
  if (!stateHydrated) {
    hydrateEndpointInputsFromState(state, renderEndpointPrecheck);
    hydrateAxisTargetInputsFromState(state, physicalInputDirty);
    loadPersistedDrafts();
    stateHydrated = true;
  }
  renderEmbeddedSimulation(state);
  renderLivePose(state);
  if (now - lastUiRenderAt < 250) return;
  lastUiRenderAt = now;
  elements.connectionState.textContent = '已连接';
  elements.connectionState.className = 'pill good';
  elements.systemState.textContent = `system_state: ${state.system_state}`;
  if (elements.faultDetailTop) {
    const problems = [];
    if (state.emergency_stop) problems.push('急停已锁定');
    if (state.control?.limit_alarm) problems.push('软限位报警');
    if (state.control?.collision?.alarm) problems.push(`碰撞：${state.control.collision.link_name || '--'} / ${state.control.collision.obstacle_name || '--'}`);
    for (const group of state.groups || []) {
      if (group.last_error) problems.push(`G${group.group}: ${group.last_error}`);
      for (const motor of group.motors || []) {
        if (motor.configured && motor.fault) problems.push(`K${motor.axis}故障=${motor.fault}`);
      }
    }
    elements.faultDetailTop.textContent = problems.length ? `故障详情：${problems.join('；')}` : '故障详情：无';
    elements.faultDetailTop.className = problems.length ? 'pill bad' : 'pill good';
  }
  elements.modeState.textContent = `mode: ${state.run_mode || '--'}`;
  elements.modeState.className = state.run_mode === 'hardware' ? 'pill warn' : 'pill good';
  const effectiveMode = state.run_mode === 'sim' ? 'sim' : 'hardware';
  if (elements.runtimeModeSelect && !elements.applyRuntimeMode?.disabled) {
    elements.runtimeModeSelect.value = effectiveMode;
  }
  if (elements.runtimeModeStatus && !elements.applyRuntimeMode?.disabled) {
    elements.runtimeModeStatus.textContent = effectiveMode === 'sim'
      ? '全局模式：仿真（不连接电机）'
      : '全局模式：实机（由Nano电机进程提供反馈）';
    elements.runtimeModeStatus.className = effectiveMode === 'sim' ? 'pill good' : 'pill warn';
  }
  renderInputRangeHints(state);
  syncPhysicalInputsFromState(state, physicalInputDirty);
  renderEndpointBackendStatus(state);
  renderJointJogState(state, elements);
  if (now - lastSlowRenderAt >= 1000) {
    lastSlowRenderAt = now;
    renderEndpointPrecheck(state);
    api.get('/api/acupoint_sequence/status').then(renderAcupointSequenceStatus).catch(() => {});
    api.get('/api/motion_test/sequence/status').then(renderMotionTestStatus).catch(() => {});
    renderStatusCards(state);
  }
}

async function pollState() {
  try {
    const state = await api.getState();
    renderState(state);
  } catch (error) {
    showError(error);
  } finally {
    window.setTimeout(pollState, 100);
  }
}

bindCommands({
  getLatestState,
  getSelectedAcupoints: () => [...selectedAcupoints],
  physicalInputDirty,
  renderInputRangeHints,
  buildAxisMapIndex,
  playMotionPreview,
});
window.therapyRobotPlayPreview = async () => {
  const button = elements.playTrajectoryPreview;
  button.disabled = true;
  elements.motionTestStatus.textContent = '新轨迹仿真：正在进行IK、软限位、小臂投影和碰撞预检';
  elements.motionTestStatus.className = 'pill warn';
  try {
    const side = elements.motionTestSide?.value === 'left' ? 'left' : 'right';
    const result = await api.post('/api/motion_test/simulate', { side });
    const points = Array.isArray(result?.points) ? result.points : [];
    const passed = result?.result === 'all_points_passed' && result?.motor_command_written === false;
    if (!passed) throw new Error(points.find((point) => !point.ok)?.reason || 'trajectory preflight failed');
    elements.motionTestStatus.textContent = `新轨迹仿真：${points.length}/${points.length}通过，正在播放；未发送电机命令`;
    elements.motionTestStatus.className = 'pill good';
    elements.motionTestProgress.textContent = `X=${side === 'left' ? '-' : '+'}575 mm；Z 790→650→790 mm；Y 250→300→250 mm；小臂始终在机箱Z向投影之外`;
    await playMotionPreview(points);
  } catch (error) {
    elements.motionTestStatus.textContent = `新轨迹仿真失败：${error.message}`;
    elements.motionTestStatus.className = 'pill bad';
  } finally {
    button.disabled = false;
  }
};
elements.playTrajectoryPreview?.addEventListener('click', window.therapyRobotPlayPreview);
if (elements.playTrajectoryPreview) elements.playTrajectoryPreview.dataset.previewBound = 'true';
if (new URLSearchParams(window.location.search).get('trajectory_preview') === '1') {
  window.setTimeout(() => window.therapyRobotPlayPreview(), 800);
}
renderEndpointPrecheck();
if (elements.acupointSourceImage) {
  elements.acupointSourceImage.addEventListener('load', renderAcupointImage);
}
window.addEventListener('resize', renderAcupointImage);
loadAcupointData();
pollState();
