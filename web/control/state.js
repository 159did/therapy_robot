import { axisInputBindings, elements } from './dom.js';
import { radToDeg } from './math.js';

const persistedDraftKeys = [
  'cameraPointName', 'cameraX', 'cameraY', 'cameraZ', 'cameraRx', 'cameraRy',
  'calibTx', 'calibTy', 'calibTz', 'calibRx', 'calibRy', 'calibRz',
  'relativeX', 'relativeY', 'relativeZ', 'relativeRx', 'relativeRy',
  'baseX', 'baseY', 'baseZ', 'baseRx', 'baseRy',
];
const persistedDraftStorageKey = 'therapy_robot_control_drafts_v2';

export function fmt(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(3) : '--';
}

export function fmtInt(value) {
  const n = Number(value);
  return Number.isFinite(n) ? String(Math.trunc(n)) : '--';
}

export function fmtWithUnit(value, unit) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '--';
  return unit ? `${n.toFixed(3)} ${unit}` : n.toFixed(3);
}

export function displayValue(value) {
  if (value === undefined || value === null) return '--';
  if (value === '') return '(empty)';
  return value;
}

export function showError(error) {
  const payload = error?.payload || {};
  const code = payload.error_code || error?.errorCode;
  const lock = payload.execution_locked === true || error?.executionLocked === true;
  const details = [code, lock ? '自动执行已锁定' : ''].filter(Boolean).join('；');
  elements.connectionState.textContent = `错误: ${error?.message || '请求失败'}${details ? `（${details}）` : ''}`;
  elements.connectionState.className = 'pill bad';
}

function card(title, rows) {
  const body = rows.map(([key, value]) => `<div><span>${key}</span><b>${displayValue(value)}</b></div>`).join('');
  return `<article class="mem-card"><h3>${title}</h3>${body}</article>`;
}

export function buildAxisMapIndex(state) {
  const entries = state.axis_map || [];
  const index = new Map();
  for (const entry of entries) {
    index.set(`${entry.group}-${entry.axis}`, entry);
  }
  return index;
}

export function axisLimitsText(axisEntry, overridePhysicalRange = null) {
  const scale = Number(axisEntry?.motor_native_to_gui_display);
  const minNative = Number(axisEntry?.min_motor_native);
  const maxNative = Number(axisEntry?.max_motor_native);
  const unit = axisEntry?.gui_display_unit || '';
  if (!Number.isFinite(scale) || scale === 0 || !Number.isFinite(minNative) || !Number.isFinite(maxNative)) {
    return { native: 'native 范围: --', physical: '物理范围: --', minNative: NaN, maxNative: NaN, low: NaN, high: NaN };
  }
  const physicalMin = minNative * scale;
  const physicalMax = maxNative * scale;
  const low = overridePhysicalRange ? overridePhysicalRange.low : Math.min(physicalMin, physicalMax);
  const high = overridePhysicalRange ? overridePhysicalRange.high : Math.max(physicalMin, physicalMax);
  return {
    native: `native 范围: ${Math.trunc(minNative)} ~ ${Math.trunc(maxNative)}`,
    physical: `物理范围: ${low.toFixed(1)} ~ ${high.toFixed(1)} ${unit}`,
    minNative,
    maxNative,
    low,
    high,
  };
}

function k0DisplayRangeText(axisEntry) {
  return axisLimitsText(axisEntry, { low: -500, high: 0 }).physical;
}

function setInputOutOfRange(input, hint, isOutOfRange, text) {
  if (input) input.classList.toggle('input-out-of-range', isOutOfRange);
  if (hint) hint.classList.toggle('input-hint-warning', isOutOfRange);
  if (hint && text) hint.textContent = text;
}

export function renderInputRangeHints(state) {
  const axisMapIndex = buildAxisMapIndex(state);
  const hintBindings = [
    { group: 0, axis: 0, nativeHint: elements.hintTargetG0A0, physicalHint: elements.hintPhysicalG0A0, input: elements.targetG0A0, physicalInput: elements.physicalG0A0 },
    { group: 1, axis: 0, nativeHint: elements.hintTargetG1A0, physicalHint: elements.hintPhysicalG1A0, input: elements.targetG1A0, physicalInput: elements.physicalG1A0 },
    { group: 1, axis: 1, nativeHint: elements.hintTargetG1A1, physicalHint: elements.hintPhysicalG1A1, input: elements.targetG1A1, physicalInput: elements.physicalG1A1 },
    { group: 2, axis: 0, nativeHint: elements.hintTargetG2A0, physicalHint: elements.hintPhysicalG2A0, input: elements.targetG2A0, physicalInput: elements.physicalG2A0 },
    { group: 2, axis: 1, nativeHint: elements.hintTargetG2A1, physicalHint: elements.hintPhysicalG2A1, input: elements.targetG2A1, physicalInput: elements.physicalG2A1 },
  ];
  for (const binding of hintBindings) {
    const axisEntry = axisMapIndex.get(`${binding.group}-${binding.axis}`);
    const text = binding.group === 0 && binding.axis === 0
      ? axisLimitsText(axisEntry, { low: -500, high: 0 })
      : axisLimitsText(axisEntry);
    const nativeValue = Number.parseFloat(binding.input?.value ?? '0');
    const physicalValue = Number.parseFloat(binding.physicalInput?.value ?? '0');
    const nativeOut = Number.isFinite(nativeValue) && Number.isFinite(text.minNative) && (nativeValue < text.minNative || nativeValue > text.maxNative);
    const physicalOut = Number.isFinite(physicalValue) && Number.isFinite(text.low) && (physicalValue < text.low || physicalValue > text.high);
    if (binding.nativeHint) setInputOutOfRange(binding.input, binding.nativeHint, nativeOut, `${text.native}${nativeOut ? '（超限，发送时会钳制到边界）' : ''}`);
    const physicalHintText = binding.group === 0 && binding.axis === 0 ? k0DisplayRangeText(axisEntry) : text.physical;
    if (binding.physicalHint) setInputOutOfRange(binding.physicalInput, binding.physicalHint, physicalOut, `${physicalHintText}${physicalOut ? '（超限，发送时会钳制到边界）' : ''}`);
  }
}

function endpointStatusText(status) {
  switch (Number(status)) {
    case 1: return 'pending';
    case 2: return 'accepted';
    case 3: return 'ik_failed';
    case 4: return 'clamped';
    default: return 'idle';
  }
}

function motorDisplayRows(axisEntry, motor) {
  const guiUnit = axisEntry?.gui_display_unit || '';
  const scale = Number(axisEntry?.motor_native_to_gui_display);
  const hasScale = Number.isFinite(scale);
  const axisLabel = axisEntry?.kind === 0 ? 'joint_height' : 'joint_angle';
  const targetLabel = axisEntry?.kind === 0 ? 'target_height' : 'target_angle';
  const rows = [
    ['motor_id', motor.motor_id],
    ['online', motor.online],
    ['enabled', motor.enabled],
    ['fault', motor.fault],
    ['mode', motor.mode],
    ['brake_supported', motor.brake_supported],
    ['brake_engaged', motor.brake_engaged],
    ['brake_release_requested', motor.brake_release_requested],
    ['brake_state_known', motor.brake_state_known],
    ['brake_last_error', motor.brake_last_error || '--'],
    ['actual_native', motor.actual_motor_native],
    ['target_native', motor.target_motor_native],
    ['active_target_native', motor.active_target_motor_native],
  ];
  if (hasScale) {
    rows.push([axisLabel, fmtWithUnit(motor.actual_motor_native * scale, guiUnit)]);
    rows.push([targetLabel, fmtWithUnit(motor.target_motor_native * scale, guiUnit)]);
  }
  rows.push(['actual_axis_si', fmt(motor.actual_axis_si)]);
  rows.push(['target_axis_si', fmt(motor.target_axis_si)]);
  rows.push(['velocity', fmt(motor.actual_motor_native_velocity)]);
  rows.push(['current_a', fmt(motor.actual_current_a)]);
  return rows;
}

export function renderStatusCards(state) {
  const cards = [];
  const heartbeats = state.heartbeats || {};
  const command = state.command || {};
  const control = state.control || {};
  const endpoint = control.endpoint_target || {};
  const collision = control.collision || {};
  const simulation = state.simulation || {};
  const groups = state.groups || [];
  const axisMapIndex = buildAxisMapIndex(state);

  cards.push(card('系统状态', [
    ['run_mode', state.run_mode],
    ['system_state', state.system_state],
    ['emergency_stop', state.emergency_stop],
    ['system_command_seq', command.command_seq],
    ['last_system_command_id', command.command_id],
    ['target_command_seq', command.target_command_seq],
    ['last_target_command_id', command.target_command_id],
  ]));

  cards.push(card('进程心跳', [
    ['core', fmtInt(state.core_heartbeat_ms ?? heartbeats.core)],
    ['control', fmtInt(control.heartbeat_ms ?? heartbeats.control)],
    ['motor', fmtInt(state.motor_heartbeat_ms ?? heartbeats.motor)],
    ['web', fmtInt(state.web_heartbeat_ms ?? heartbeats.web)],
    ['sim', fmtInt(state.sim_heartbeat_ms ?? heartbeats.sim)],
  ]));

  cards.push(card('控制目标', [
    ['active_target_seq', control.active_target_seq],
    ['limit_alarm', control.limit_alarm],
    ['endpoint.valid', endpoint.valid],
    ['endpoint.target_seq', endpoint.target_seq],
    ['endpoint.status', endpointStatusText(endpoint.status)],
    ['endpoint.error', endpoint.last_error || '--'],
    ['endpoint.pos_err_mm', Number.isFinite(Number(endpoint.last_position_error_m)) ? fmt(Number(endpoint.last_position_error_m) * 1000) : '--'],
    ['endpoint.dir_err_deg', Number.isFinite(Number(endpoint.last_direction_error_rad)) ? fmt(radToDeg(Number(endpoint.last_direction_error_rad))) : '--'],
    ['endpoint.x_m', fmt(endpoint.x_m)],
    ['endpoint.y_m', fmt(endpoint.y_m)],
    ['endpoint.z_m', fmt(endpoint.z_m)],
  ]));

  cards.push(card('机箱碰撞边界', [
    ['configured', collision.configured ?? 0],
    ['enabled', collision.enabled ?? 0],
    ['status', collision.status || '--'],
    ['alarm', collision.alarm ?? 0],
    ['rejected_commands', collision.rejected_commands ?? 0],
    ['path_fraction', Number.isFinite(Number(collision.path_fraction)) ? fmt(Number(collision.path_fraction)) : '--'],
    ['link', collision.link_name || '--'],
    ['obstacle', collision.obstacle_name || '--'],
    ['last_error', collision.last_error || '--'],
    ['config_path', collision.config_path || '--'],
  ]));

  cards.push(card('仿真状态', [
    ['enabled', simulation.enabled],
    ['hardware_mode', simulation.hardware_mode],
    ['mujoco_available', simulation.mujoco_available],
    ['ee_x_m', fmt(simulation.end_effector_x_m)],
    ['ee_y_m', fmt(simulation.end_effector_y_m)],
    ['ee_z_m', fmt(simulation.end_effector_z_m)],
  ]));

  const targetValid = Number(endpoint.valid) === 1;
  const errorX = targetValid ? Number(simulation.end_effector_x_m) - Number(endpoint.x_m) : NaN;
  const errorY = targetValid ? Number(simulation.end_effector_y_m) - Number(endpoint.y_m) : NaN;
  const errorZ = targetValid ? Number(simulation.end_effector_z_m) - Number(endpoint.z_m) : NaN;
  const errorNorm = Math.hypot(errorX, errorY, errorZ);
  cards.push(card('末端目标误差', [
    ['target_x_mm', targetValid ? fmt(Number(endpoint.x_m) * 1000) : '--'],
    ['target_y_mm', targetValid ? fmt(Number(endpoint.y_m) * 1000) : '--'],
    ['target_z_mm', targetValid ? fmt(Number(endpoint.z_m) * 1000) : '--'],
    ['actual_x_mm', fmt(Number(simulation.end_effector_x_m) * 1000)],
    ['actual_y_mm', fmt(Number(simulation.end_effector_y_m) * 1000)],
    ['actual_z_mm', fmt(Number(simulation.end_effector_z_m) * 1000)],
    ['error_norm_mm', Number.isFinite(errorNorm) ? fmt(errorNorm * 1000) : '--'],
  ]));

  for (const group of groups) {
    const onlineCount = (group.motors || []).filter((motor) => motor.configured && motor.online).length;
    const enabledCount = (group.motors || []).filter((motor) => motor.configured && motor.enabled).length;
    const faultCount = (group.motors || []).filter((motor) => motor.configured && motor.fault).length;
    cards.push(card(`G${group.group} 总览`, [
      ['hardware_enabled', group.hardware_enabled],
      ['motor_count', group.motor_count],
      ['online', `${onlineCount}/${group.motor_count}`],
      ['enabled', `${enabledCount}/${group.motor_count}`],
      ['fault', `${faultCount}/${group.motor_count}`],
      ['port', group.port || '--'],
      ['last_error', group.last_error || '--'],
    ]));
  }

  for (const group of groups) {
    for (const motor of group.motors || []) {
      if (!motor.configured) continue;
      const axisEntry = axisMapIndex.get(`${group.group}-${motor.axis}`);
      cards.push(card(`G${group.group}-A${motor.axis}`, motorDisplayRows(axisEntry, motor)));
    }
  }

  elements.statusCards.innerHTML = cards.join('');
}

export function syncPhysicalInputsFromState(state, physicalInputDirty) {
  const axisMapIndex = buildAxisMapIndex(state);
  for (const binding of axisInputBindings) {
    const axisEntry = axisMapIndex.get(`${binding.group}-${binding.axis}`);
    const group = state.groups?.[binding.group];
    const motor = group?.motors?.[binding.axis];
    const input = elements[binding.physicalInput];
    const scale = Number(axisEntry?.motor_native_to_gui_display);
    const hint = elements[`hint_${binding.physicalInput}`];
    if (!input || !motor || !Number.isFinite(scale)) continue;
    if (document.activeElement === input || physicalInputDirty.has(binding.physicalInput)) continue;
    const physicalValue = motor.target_motor_native * scale;
    input.value = Number.isFinite(physicalValue) ? physicalValue.toFixed(binding.physicalUnit === 'mm' ? 2 : 3) : '0';
    setInputOutOfRange(input, hint, false, hint?.textContent || '');
  }
}

export function hydrateAxisTargetInputsFromState(state, physicalInputDirty) {
  const axisMapIndex = buildAxisMapIndex(state);
  for (const binding of axisInputBindings) {
    const axisEntry = axisMapIndex.get(`${binding.group}-${binding.axis}`);
    const group = state.groups?.[binding.group];
    const motor = group?.motors?.[binding.axis];
    const nativeInput = elements[binding.nativeInput];
    const physicalInput = elements[binding.physicalInput];
    const scale = Number(axisEntry?.motor_native_to_gui_display);
    if (nativeInput && motor && document.activeElement !== nativeInput) {
      nativeInput.value = String(motor.target_motor_native ?? 0);
    }
    if (physicalInput && motor && Number.isFinite(scale) && !physicalInputDirty.has(binding.physicalInput) && document.activeElement !== physicalInput) {
      const physicalValue = motor.target_motor_native * scale;
      physicalInput.value = Number.isFinite(physicalValue) ? physicalValue.toFixed(binding.physicalUnit === 'mm' ? 2 : 3) : '0';
    }
  }
}

export function persistDraftInputs() {
  const payload = {};
  for (const key of persistedDraftKeys) {
    const input = elements[key];
    if (input) payload[key] = input.value;
  }
  window.localStorage.setItem(persistedDraftStorageKey, JSON.stringify(payload));
}

export function loadPersistedDrafts() {
  let payload = null;
  try {
    payload = JSON.parse(window.localStorage.getItem(persistedDraftStorageKey) || 'null');
  } catch {
    payload = null;
  }
  if (!payload || typeof payload !== 'object') return;
  for (const key of persistedDraftKeys) {
    const input = elements[key];
    const value = payload[key];
    if (input && typeof value === 'string') input.value = value;
  }
}
