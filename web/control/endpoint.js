import { api } from './api.js';
import { axisInputBindings, elements } from './dom.js';
import {
  axisFromRxRyDeg,
  degToRad,
  dot3,
  endpointModel,
  fillAbsoluteEndpoint,
  matVecMul,
  norm3,
  numberValue,
  planarDir,
  radToDeg,
  rotationMatrixFromEulerDeg,
  rxRyDegFromAxis,
  smallArmSide,
} from './math.js';

export function physicalToNative(axisEntry, physicalValue) {
  const scale = Number(axisEntry?.motor_native_to_gui_display);
  if (!Number.isFinite(scale) || scale === 0) {
    throw new Error(`轴 ${axisEntry?.name || '--'} 缺少有效换算比例`);
  }
  return Math.round(physicalValue / scale);
}

export function buildPhysicalTargetsFromInputs(state, buildAxisMapIndex) {
  const axisMapIndex = buildAxisMapIndex(state);
  const targets = {};
  for (const binding of axisInputBindings) {
    const axisEntry = axisMapIndex.get(`${binding.group}-${binding.axis}`);
    const input = elements[binding.physicalInput];
    const physicalValue = numberValue(input);
    const nativeValue = physicalToNative(axisEntry, physicalValue);
    targets[binding.key] = nativeValue;
    elements[binding.nativeInput].value = String(nativeValue);
  }
  return targets;
}

export async function sendTargets() {
  await api.post('/api/command/targets', {
    g0a0: numberValue(elements.targetG0A0),
    g1a0: numberValue(elements.targetG1A0),
    g1a1: numberValue(elements.targetG1A1),
    g2a0: numberValue(elements.targetG2A0),
    g2a1: numberValue(elements.targetG2A1),
  });
}

export async function sendPhysicalTargets(state, physicalInputDirty, buildAxisMapIndex) {
  if (!state) {
    throw new Error('状态尚未加载，无法按物理量换算');
  }
  const targets = buildPhysicalTargetsFromInputs(state, buildAxisMapIndex);
  await api.post('/api/command/targets', targets);
  physicalInputDirty.clear();
}

export function applyRelativeEndpoint(renderEndpointPrecheck) {
  const x = numberValue(elements.baseX) + numberValue(elements.relativeX);
  const y = numberValue(elements.baseY) + numberValue(elements.relativeY);
  const z = numberValue(elements.baseZ) + numberValue(elements.relativeZ);
  const rx = numberValue(elements.baseRx) + numberValue(elements.relativeRx);
  const ry = numberValue(elements.baseRy) + numberValue(elements.relativeRy);
  fillAbsoluteEndpoint({ x, y, z, rx, ry, rz: 0 }, renderEndpointPrecheck);
}

export function cameraToBaseEndpoint() {
  const rotation = rotationMatrixFromEulerDeg(
    numberValue(elements.calibRx),
    numberValue(elements.calibRy),
    numberValue(elements.calibRz),
  );
  const pCamera = {
    x: numberValue(elements.cameraX),
    y: numberValue(elements.cameraY),
    z: numberValue(elements.cameraZ),
  };
  const pRot = matVecMul(rotation, pCamera);
  const axisCamera = axisFromRxRyDeg(numberValue(elements.cameraRx), numberValue(elements.cameraRy));
  const axisBase = matVecMul(rotation, axisCamera);
  const anglesBase = rxRyDegFromAxis(axisBase);
  return {
    x: pRot.x + numberValue(elements.calibTx),
    y: pRot.y + numberValue(elements.calibTy),
    z: pRot.z + numberValue(elements.calibTz),
    rx: anglesBase.rx,
    ry: anglesBase.ry,
    rz: 0,
  };
}

export function applyCameraEndpoint(renderEndpointPrecheck) {
  fillAbsoluteEndpoint(cameraToBaseEndpoint(), renderEndpointPrecheck);
}

export function endpointNormalAngles() {
  const rawAxis = {
    x: numberValue(elements.endpointNx),
    y: numberValue(elements.endpointNy),
    z: numberValue(elements.endpointNz),
  };
  if (norm3(rawAxis) < 1e-9) {
    return null;
  }
  const angles = rxRyDegFromAxis(rawAxis);
  elements.endpointRx.value = String(Number(angles.rx.toFixed(3)));
  elements.endpointRy.value = String(Number(angles.ry.toFixed(3)));
  return angles;
}

export function renderEndpointFromNormal(renderEndpointPrecheck) {
  endpointNormalAngles();
  renderEndpointPrecheck();
}

function rotateAroundAxis(v, axis, angle) {
  const n = norm3(axis) || 1;
  const k = { x: axis.x / n, y: axis.y / n, z: axis.z / n };
  const c = Math.cos(angle);
  const s = Math.sin(angle);
  const kv = dot3(k, v);
  return {
    x: v.x * c + (k.y * v.z - k.z * v.y) * s + k.x * kv * (1 - c),
    y: v.y * c + (k.z * v.x - k.x * v.z) * s + k.y * kv * (1 - c),
    z: v.z * c + (k.x * v.y - k.y * v.x) * s + k.z * kv * (1 - c),
  };
}

export function estimateEndpointFromState(state) {
  const axisMap = state.axis_map || [];
  const readDisplay = (globalAxis) => {
    const map = axisMap.find((axis) => axis.global_axis === globalAxis);
    const motorNative = state.groups?.[map?.group]?.motors?.[map?.axis]?.actual_motor_native || 0;
    return motorNative * (map?.motor_native_to_gui_display || 0.01);
  };
  const liftMm = Number(state.groups?.[0]?.motors?.[0]?.actual_axis_si || 0) * 1000;
  const q1 = degToRad(readDisplay(1));
  const q2 = degToRad(readDisplay(2));
  const q3 = degToRad(readDisplay(3));
  const q4 = degToRad(readDisplay(4));
  const p1 = { x: 0, y: 0, z: endpointModel.baseHeightMm + liftMm };
  const p2 = {
    x: p1.x + Math.sin(q1) * endpointModel.upperArmMm,
    y: p1.y + Math.cos(q1) * endpointModel.upperArmMm,
    z: p1.z,
  };
  const p3 = { x: p2.x, y: p2.y, z: p2.z - endpointModel.forearmDropMm };
  // K2=0 is the folded storage pose, so the forearm points back underneath
  // the upper arm instead of extending in the same direction.
  const yaw = q1 + q2 + Math.PI;
  const forward = planarDir(yaw);
  const p4 = {
    x: p3.x + forward.x * endpointModel.forearmMm,
    y: p3.y + forward.y * endpointModel.forearmMm,
    z: p3.z,
  };
  const side = rotateAroundAxis(smallArmSide(yaw), forward, q3);
  const wristForward = rotateAroundAxis(forward, side, q4);
  const axis = rotateAroundAxis(rotateAroundAxis({ x: 0, y: 0, z: 1 }, forward, q3), side, q4);
  const tip = {
    x: p4.x + wristForward.x * endpointModel.wristForwardOffsetMm - axis.x * endpointModel.toolMm,
    y: p4.y + wristForward.y * endpointModel.wristForwardOffsetMm - axis.y * endpointModel.toolMm,
    z: p4.z + wristForward.z * endpointModel.wristForwardOffsetMm - axis.z * endpointModel.toolMm,
  };
  const angles = rxRyDegFromAxis(axis);
  return { ...tip, rx: angles.rx, ry: angles.ry, rz: 0 };
}

export function syncActualEndpointFromState(state, renderEndpointPrecheck) {
  if (!state) {
    throw new Error('状态尚未加载，无法同步当前末端');
  }
  const estimated = estimateEndpointFromState(state);
  fillAbsoluteEndpoint(estimated, renderEndpointPrecheck);
}

export function hydrateEndpointInputsFromState(state, renderEndpointPrecheck) {
  const endpoint = state.control?.endpoint_target || {};
  if (Number(endpoint.valid) !== 1) return;
  fillAbsoluteEndpoint({
    x: Number(endpoint.x_m || 0) * 1000,
    y: Number(endpoint.y_m || 0) * 1000,
    z: Number(endpoint.z_m || 0) * 1000,
    rx: Number.isFinite(Number(endpoint.rx_rad)) ? radToDeg(Number(endpoint.rx_rad)) : 0,
    ry: Number.isFinite(Number(endpoint.ry_rad)) ? radToDeg(Number(endpoint.ry_rad)) : 0,
    rz: 0,
  }, renderEndpointPrecheck);
}

export async function sendEndpoint() {
  await api.post('/api/command/endpoint_target', buildEndpointPayload());
}

function buildEndpointPayload() {
  const angles = endpointNormalAngles();
  if (!angles) {
    throw new Error('法向量长度不能为 0');
  }
  return {
    x_m: numberValue(elements.endpointX) / 1000,
    y_m: numberValue(elements.endpointY) / 1000,
    z_m: numberValue(elements.endpointZ) / 1000,
    rx_rad: degToRad(angles.rx),
    ry_rad: degToRad(angles.ry),
    rz_rad: 0,
  };
}

export async function endpointPrecheck() {
  return api.post('/api/ik/check', buildEndpointPayload());
}

let endpointPrecheckRequestId = 0;
let endpointPrecheckLastKey = '';
let endpointPrecheckLastResult = null;
let endpointPrecheckPendingKey = '';
let endpointPrecheckMotionKey = '';

function applyEndpointPrecheckResult(check) {
  const ok = Boolean(check?.ok);
  const reason = check?.reason || (ok ? 'ok' : 'unknown');
  const collisionEnabled = Boolean(check?.collision_enabled);
  if (ok && collisionEnabled) {
    elements.endpointPrecheck.textContent = '后端预检查: IK可达，轨迹无机箱碰撞';
    elements.endpointPrecheck.className = 'pill good';
  } else if (ok) {
    elements.endpointPrecheck.textContent = '后端预检查: IK可达；机箱碰撞边界尚未启用';
    elements.endpointPrecheck.className = 'pill warn';
  } else {
    elements.endpointPrecheck.textContent = `后端预检查: ${reason}`;
    elements.endpointPrecheck.className = 'pill bad';
  }
}

export function renderEndpointPrecheck(state = null) {
  if (!elements.endpointPrecheck) return;
  if (state) {
    const actual = [];
    for (const group of state.groups || []) {
      for (const motor of group.motors || []) {
        if (motor.configured) actual.push(Number(motor.actual_motor_native || 0));
      }
    }
    endpointPrecheckMotionKey = JSON.stringify(actual);
  }
  let payload;
  try {
    payload = buildEndpointPayload();
  } catch (error) {
    endpointPrecheckLastKey = '';
    endpointPrecheckLastResult = null;
    endpointPrecheckPendingKey = '';
    elements.endpointPrecheck.textContent = `后端IK预检查: ${error.message}`;
    elements.endpointPrecheck.className = 'pill bad';
    return;
  }
  const key = `${JSON.stringify(payload)}:${endpointPrecheckMotionKey}`;
  if (key === endpointPrecheckLastKey && endpointPrecheckLastResult) {
    applyEndpointPrecheckResult(endpointPrecheckLastResult);
    return;
  }
  if (key === endpointPrecheckPendingKey) {
    return;
  }

  const requestId = ++endpointPrecheckRequestId;
  endpointPrecheckPendingKey = key;
  if (!endpointPrecheckLastResult) {
    elements.endpointPrecheck.textContent = '后端IK预检查: checking...';
    elements.endpointPrecheck.className = 'pill warn';
  }
  api.post('/api/ik/check', payload)
    .then((check) => {
      if (requestId !== endpointPrecheckRequestId) return;
      endpointPrecheckPendingKey = '';
      endpointPrecheckLastKey = key;
      endpointPrecheckLastResult = check;
      applyEndpointPrecheckResult(check);
    })
    .catch((error) => {
      if (requestId !== endpointPrecheckRequestId) return;
      endpointPrecheckPendingKey = '';
      endpointPrecheckLastKey = '';
      endpointPrecheckLastResult = null;
      elements.endpointPrecheck.textContent = `后端IK预检查: ${error.message}`;
      elements.endpointPrecheck.className = 'pill bad';
    });
}

export function renderEndpointBackendStatus(state) {
  if (!elements.endpointBackendStatus) return;
  const endpoint = state.control?.endpoint_target || {};
  const status = Number(endpoint.status);
  if (Number(endpoint.valid) !== 1) {
    elements.endpointBackendStatus.textContent = '后端结果: --';
    elements.endpointBackendStatus.className = 'pill';
    return;
  }
  if (status === 2) {
    elements.endpointBackendStatus.textContent = '后端结果: accepted';
    elements.endpointBackendStatus.className = 'pill good';
    return;
  }
  if (status === 1) {
    elements.endpointBackendStatus.textContent = '后端结果: pending';
    elements.endpointBackendStatus.className = 'pill warn';
    return;
  }
  const errorText = endpoint.last_error || 'unknown';
  elements.endpointBackendStatus.textContent = `后端结果: ${errorText}`;
  elements.endpointBackendStatus.className = 'pill bad';
}

export async function sendCheckedEndpoint() {
  const check = await endpointPrecheck();
  if (!check.ok) {
    throw new Error(`发送前后端IK检查失败: ${check.reason}`);
  }
  await sendEndpoint();
}

export async function applyAndSendCameraEndpoint(renderEndpointPrecheck) {
  applyCameraEndpoint(renderEndpointPrecheck);
  await sendCheckedEndpoint();
}
