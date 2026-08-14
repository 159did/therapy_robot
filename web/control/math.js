import { elements } from './dom.js';

export const endpointModel = {
  baseHeightMm: 710,
  upperArmMm: 580,
  forearmMm: 229,
  wristForwardOffsetMm: 119,
  forearmDropMm: 80,
  toolMm: 153.1,
  cameraMountOffsetYMm: -217,
  cameraMountOffsetZMm: 145.2,
  liftMinMm: -500,
  liftMaxMm: 0,
  theta1Min: -90,
  theta1Max: 90,
  theta2Min: -90,
  theta2Max: 90,
  theta3Min: -45,
  theta3Max: 45,
  theta4Min: -60,
  theta4Max: 60,
};

export const degToRad = (deg) => deg * Math.PI / 180;
export const radToDeg = (rad) => rad * 180 / Math.PI;

export function numberValue(input) {
  const value = Number.parseFloat(input.value);
  return Number.isFinite(value) ? value : 0;
}

export function dot3(a, b) {
  return a.x * b.x + a.y * b.y + a.z * b.z;
}

export function sub3(a, b) {
  return { x: a.x - b.x, y: a.y - b.y, z: a.z - b.z };
}

export function mul3(a, s) {
  return { x: a.x * s, y: a.y * s, z: a.z * s };
}

export function norm3(v) {
  return Math.hypot(v.x, v.y, v.z);
}

export function normalize3(v) {
  const n = norm3(v) || 1;
  return { x: v.x / n, y: v.y / n, z: v.z / n };
}

export function planarDir(angle) {
  return { x: Math.sin(angle), y: Math.cos(angle), z: 0 };
}

export function smallArmSide(angle) {
  return { x: Math.cos(angle), y: -Math.sin(angle), z: 0 };
}

export function wrapPi(rad) {
  let v = rad;
  while (v > Math.PI) v -= 2 * Math.PI;
  while (v < -Math.PI) v += 2 * Math.PI;
  return v;
}

export function rotationMatrixFromEulerDeg(rxDeg, ryDeg, rzDeg) {
  const rx = degToRad(rxDeg);
  const ry = degToRad(ryDeg);
  const rz = degToRad(rzDeg);
  const sx = Math.sin(rx); const cx = Math.cos(rx);
  const sy = Math.sin(ry); const cy = Math.cos(ry);
  const sz = Math.sin(rz); const cz = Math.cos(rz);
  return [
    [cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
    [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
    [-sy, cy * sx, cy * cx],
  ];
}

export function matVecMul(m, v) {
  return {
    x: m[0][0] * v.x + m[0][1] * v.y + m[0][2] * v.z,
    y: m[1][0] * v.x + m[1][1] * v.y + m[1][2] * v.z,
    z: m[2][0] * v.x + m[2][1] * v.y + m[2][2] * v.z,
  };
}

export function axisFromRxRyDeg(rxDeg, ryDeg) {
  const rx = degToRad(rxDeg);
  const ry = degToRad(ryDeg);
  const sx = Math.sin(rx);
  const cx = Math.cos(rx);
  const sy = Math.sin(ry);
  const cy = Math.cos(ry);
  return { x: sy * cx, y: -sx, z: cy * cx };
}

export function rxRyDegFromAxis(axis) {
  const norm = Math.hypot(axis.x, axis.y, axis.z) || 1;
  const x = axis.x / norm;
  const y = axis.y / norm;
  const z = axis.z / norm;
  return {
    rx: radToDeg(Math.asin(Math.max(-1, Math.min(1, -y)))),
    ry: radToDeg(Math.atan2(x, z)),
  };
}

export function fillAbsoluteEndpoint({ x, y, z, rx, ry, rz = 0 }, renderEndpointPrecheck) {
  elements.endpointX.value = String(Number.isFinite(x) ? Number(x.toFixed(3)) : 0);
  elements.endpointY.value = String(Number.isFinite(y) ? Number(y.toFixed(3)) : 0);
  elements.endpointZ.value = String(Number.isFinite(z) ? Number(z.toFixed(3)) : 0);
  const axis = axisFromRxRyDeg(rx, ry);
  elements.endpointNx.value = String(Number(axis.x.toFixed(6)));
  elements.endpointNy.value = String(Number(axis.y.toFixed(6)));
  elements.endpointNz.value = String(Number(axis.z.toFixed(6)));
  elements.endpointRx.value = String(Number.isFinite(rx) ? Number(rx.toFixed(3)) : 0);
  elements.endpointRy.value = String(Number.isFinite(ry) ? Number(ry.toFixed(3)) : 0);
  elements.endpointRz.value = String(Number.isFinite(rz) ? Number(rz.toFixed(3)) : 0);
  renderEndpointPrecheck();
}
