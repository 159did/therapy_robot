import { updateThreeRobot } from './three_robot_view.js?rev=20260726-1945';

const api = {
  async getState() {
    const response = await fetch('/api/state');
    if (!response.ok) throw new Error(`state HTTP ${response.status}`);
    return response.json();
  },
};

const elements = {
  connectionState: document.getElementById('connectionState'),
  modeState: document.getElementById('modeState'),
  systemState: document.getElementById('systemState'),
  threeView: document.getElementById('threeView'),
  eeX: document.getElementById('eeX'),
  eeY: document.getElementById('eeY'),
  eeZ: document.getElementById('eeZ'),
  mujocoState: document.getElementById('mujocoState'),
  rawState: document.getElementById('rawState'),
};
let lastRawRenderAt = 0;

function fmt(value) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(3) : '--';
}

function showError(error) {
  elements.connectionState.textContent = `错误: ${error.message}`;
  elements.connectionState.className = 'pill bad';
}

function renderState(state) {
  const sim = state.simulation || {};
  elements.connectionState.textContent = '已连接';
  elements.connectionState.className = 'pill good';
  elements.systemState.textContent = `system_state: ${state.system_state}`;
  elements.modeState.textContent = `mode: ${state.run_mode || '--'}`;
  elements.modeState.className = state.run_mode === 'hardware' ? 'pill warn' : 'pill good';
  const pose = updateThreeRobot(elements.threeView, state);
  elements.eeX.textContent = `x: ${fmt(pose.x_m)} m`;
  elements.eeY.textContent = `y: ${fmt(pose.y_m)} m`;
  elements.eeZ.textContent = `z: ${fmt(pose.z_m)} m`;
  elements.mujocoState.textContent = 'absolute encoder feedback / Three.js viewer';
  const now = performance.now();
  if (now - lastRawRenderAt >= 1000) {
    lastRawRenderAt = now;
    elements.rawState.textContent = JSON.stringify(state, null, 2);
  }
}

async function pollState() {
  try {
    renderState(await api.getState());
  } catch (error) {
    showError(error);
  } finally {
    window.setTimeout(pollState, 150);
  }
}

pollState();
