import { api } from './api.js';
import { axisInputBindings, elements, endpointInputKeys, endpointSourceInputs } from './dom.js';
import {
  applyAndSendCameraEndpoint,
  applyCameraEndpoint,
  applyRelativeEndpoint,
  estimateEndpointFromState,
  renderEndpointFromNormal,
  renderEndpointPrecheck,
  sendCheckedEndpoint,
  sendPhysicalTargets,
  sendTargets,
  syncActualEndpointFromState,
} from './endpoint.js';
import { persistDraftInputs, showError } from './state.js';
import { fillAbsoluteEndpoint } from './math.js';
import { bindJointJog } from './joint_jog.js';

export function bindCommands({ getLatestState, getSelectedAcupoints, physicalInputDirty, renderInputRangeHints, buildAxisMapIndex, playMotionPreview }) {
  let motionTestPoints = [];
  const renderAcupointLockError = (error) => {
    const payload = error?.payload || {};
    const locked = payload.execution_locked === true
      || error?.executionLocked === true
      || payload.error_code === 'automatic_trajectory_locked';
    if (!locked) {
      showError(error);
      return;
    }
    const reason = payload.lock_reason || payload.error || '自动穴位序列已锁定，当前仅允许只读预览';
    for (const button of [elements.startSelectedAcupoints, elements.startAcupointSequence].filter(Boolean)) {
      button.disabled = true;
      button.title = reason;
    }
    if (elements.acupointSequenceStatus) {
      elements.acupointSequenceStatus.textContent = `自动序列: ${reason}`;
      elements.acupointSequenceStatus.className = 'pill warn';
    }
    showError(error);
  };
  for (const binding of axisInputBindings) {
    const input = elements[binding.physicalInput];
    const nativeInput = elements[binding.nativeInput];
    if (!input) continue;
    input.addEventListener('input', () => {
      physicalInputDirty.add(binding.physicalInput);
      const state = getLatestState();
      if (state) renderInputRangeHints(state);
    });
    input.addEventListener('change', () => {
      physicalInputDirty.add(binding.physicalInput);
      const state = getLatestState();
      if (state) renderInputRangeHints(state);
    });
    if (nativeInput) {
      nativeInput.addEventListener('input', () => {
        const state = getLatestState();
        if (state) renderInputRangeHints(state);
      });
      nativeInput.addEventListener('change', () => {
        const state = getLatestState();
        if (state) renderInputRangeHints(state);
      });
    }
  }

  const advancedPanels = [...document.querySelectorAll('.advanced-panel')];
  for (const panel of advancedPanels) panel.classList.add('advanced-hidden');
  document.querySelector('.operation-grid')?.append(
    document.querySelector('.acupoint-vision-panel'),
    document.querySelector('.embedded-sim-panel'),
    document.querySelector('.endpoint-live-panel'),
    document.querySelector('.joint-jog-panel'),
    document.querySelector('.endpoint-jog-panel'),
    document.querySelector('.acupoint-panel'),
  );

  elements.emergencyStopTop.addEventListener('click', () => {
    api.post('/api/command/emergency_stop').catch(showError);
  });
  elements.applyRuntimeMode?.addEventListener('click', async () => {
    const mode = elements.runtimeModeSelect.value;
    const label = mode === 'hardware' ? '实机模式' : '仿真模式';
    if (!window.confirm(`将切换到${label}。切换前必须确认全部电机已经下电，服务会短暂断开并重启。继续吗？`)) return;
    elements.applyRuntimeMode.disabled = true;
    elements.runtimeModeStatus.textContent = `全局模式：正在切换到${label}，请等待页面重新连接`;
    elements.runtimeModeStatus.className = 'pill warn';
    try {
      const result = await api.post('/api/mode/switch', { mode });
      if (result.changed === false) {
        elements.runtimeModeStatus.textContent = `全局模式：当前已经是${label}`;
        elements.runtimeModeStatus.className = mode === 'sim' ? 'pill good' : 'pill warn';
        elements.applyRuntimeMode.disabled = false;
      } else {
        elements.runtimeModeStatus.textContent = `全局模式：已请求切换到${label}，服务正在重启`;
        elements.runtimeModeStatus.className = 'pill warn';
      }
    } catch (error) {
      elements.runtimeModeStatus.textContent = `全局模式：${error.message}`;
      elements.runtimeModeStatus.className = 'pill bad';
      elements.applyRuntimeMode.disabled = false;
    }
  });
  elements.resetEmergencyStopTop.addEventListener('click', () => {
    if (!window.confirm('确认机械臂已经停止、周围无人，并且所有电机已经下电？')) return;
    api.post('/api/command/reset_emergency_stop').catch(showError);
  });
  elements.clearFaultsTop?.addEventListener('click', async () => {
    if (!window.confirm('确认机械臂已经停止、周围无人，且所有电机均已下电？故障清零只解除软件锁定，不会自动上电或移动。')) return;
    elements.clearFaultsTop.disabled = true;
    try {
      const result = await api.post('/api/command/clear_faults');
      elements.faultDetailTop.textContent = `故障详情：${result.message}`;
      elements.faultDetailTop.className = 'pill good';
    } catch (error) {
      elements.faultDetailTop.textContent = `故障详情：清零失败，${error.message}`;
      elements.faultDetailTop.className = 'pill bad';
    } finally {
      elements.clearFaultsTop.disabled = false;
    }
  });
  const reconcileInputs = [elements.reconcileK0, elements.reconcileK1, elements.reconcileK2,
    elements.reconcileK3, elements.reconcileK4];
  const readPoseFromState = (state) => {
    const values = Array(5).fill(0);
    for (const group of state?.groups || []) {
      for (const motor of group.motors || []) {
        if (!motor.configured) continue;
        const mapping = (state.axis_map || []).find((entry) => entry.group === group.group && entry.axis === motor.axis);
        if (!mapping || mapping.global_axis < 0 || mapping.global_axis > 4) continue;
        values[mapping.global_axis] = Number(motor.actual_axis_si || 0);
      }
    }
    return [values[0] * 1000, values[1] * 180 / Math.PI, values[2] * 180 / Math.PI,
      values[3] * 180 / Math.PI, values[4] * 180 / Math.PI];
  };
  elements.reconcileFill?.addEventListener('click', () => {
    const pose = readPoseFromState(getLatestState());
    reconcileInputs.forEach((input, index) => { if (input) input.value = pose[index].toFixed(index === 0 ? 3 : 3); });
    if (elements.reconcileStatus) elements.reconcileStatus.textContent = '已填入程序当前解释，请与实体比较后再确认';
  });
  elements.reconcileApply?.addEventListener('click', async () => {
    const state = getLatestState();
    if (!state) return;
    if (!window.confirm('确认所有电机已经下电，且实体姿态与填写值一致？此操作只更新软件偏置、仿真和目标，不会让电机运动。')) return;
    const body = { k0_mm: Number(elements.reconcileK0.value), k1_deg: Number(elements.reconcileK1.value),
      k2_deg: Number(elements.reconcileK2.value), k3_deg: Number(elements.reconcileK3.value), k4_deg: Number(elements.reconcileK4.value) };
    if (Object.values(body).some((value) => !Number.isFinite(value))) {
      elements.reconcileStatus.textContent = '请输入完整的数值';
      elements.reconcileStatus.className = 'pill bad';
      return;
    }
    elements.reconcileApply.disabled = true;
    try {
      const result = await api.post('/api/reconcile/apply', body);
      elements.reconcileStatus.textContent = result.message || '同步已排队，等待状态刷新';
      elements.reconcileStatus.className = 'pill good';
    } catch (error) {
      elements.reconcileStatus.textContent = `同步失败：${error.message}`;
      elements.reconcileStatus.className = 'pill bad';
    } finally {
      elements.reconcileApply.disabled = false;
    }
  });
  elements.advancedDebugToggle.addEventListener('click', () => {
    const show = advancedPanels.some((panel) => panel.classList.contains('advanced-hidden'));
    for (const panel of advancedPanels) panel.classList.toggle('advanced-hidden', !show);
    elements.advancedDebugToggle.textContent = show ? '隐藏高级调试' : '显示高级调试';
  });

  elements.convertCameraEndpoint.addEventListener('click', () => applyCameraEndpoint(renderEndpointPrecheck));
  elements.sendCameraEndpoint.addEventListener('click', () => applyAndSendCameraEndpoint(renderEndpointPrecheck).catch(showError));
  elements.convertEndpoint.addEventListener('click', () => applyRelativeEndpoint(renderEndpointPrecheck));

  for (const key of endpointSourceInputs) {
    const input = elements[key];
    if (!input) continue;
    input.addEventListener('input', () => {
      persistDraftInputs();
      const state = getLatestState();
      if (state) renderInputRangeHints(state);
    });
    input.addEventListener('change', () => persistDraftInputs());
  }

  for (const key of endpointInputKeys) {
    const input = elements[key];
    if (!input) continue;
    input.addEventListener('input', () => renderEndpointFromNormal(renderEndpointPrecheck));
    input.addEventListener('change', () => renderEndpointFromNormal(renderEndpointPrecheck));
  }

  elements.sendTargets.addEventListener('click', () => sendTargets().catch(showError));
  elements.sendPhysicalTargets.addEventListener('click', () => sendPhysicalTargets(getLatestState(), physicalInputDirty, buildAxisMapIndex).catch(showError));
  elements.syncActualEndpoint.addEventListener('click', () => {
    try {
      syncActualEndpointFromState(getLatestState(), renderEndpointPrecheck);
    } catch (error) {
      showError(error);
    }
  });
  for (const button of elements.endpointJogButtons) {
    button.addEventListener('click', async () => {
      try {
        const state = getLatestState();
        if (!state) throw new Error('状态尚未加载');
        const axis = button.dataset.jogAxis;
        const delta = Number(elements.endpointJogStep.value) * Number(button.dataset.jogSign);
        elements.endpointJogStatus.textContent = `增量控制: ${axis.toUpperCase()} ${delta > 0 ? '+' : ''}${delta} mm 检查中`;
        elements.endpointJogStatus.className = 'pill warn';
        const result = await api.post('/api/command/endpoint_jog', { axis, delta_mm: delta });
        if (result.target_pose) fillAbsoluteEndpoint(result.target_pose, renderEndpointPrecheck);
        elements.endpointJogStatus.textContent = `增量控制: 已发送 ${axis.toUpperCase()} ${delta > 0 ? '+' : ''}${delta} mm（后端FK/IK已通过）`;
        elements.endpointJogStatus.className = 'pill good';
      } catch (error) {
        elements.endpointJogStatus.textContent = `增量控制: ${error.message}`;
        elements.endpointJogStatus.className = 'pill bad';
      }
    });
  }
  elements.sendEndpoint.addEventListener('click', () => sendCheckedEndpoint().catch(showError));
  elements.enableAll.addEventListener('click', () => api.post('/api/command/enable_all').catch(showError));
  elements.disableAll.addEventListener('click', () => api.post('/api/command/disable_all').catch(showError));
  elements.stopAll.addEventListener('click', () => api.post('/api/command/stop_all').catch(showError));
  elements.returnArmZero.addEventListener('click', async () => {
    if (!window.confirm('确认周围安全？将保持K0当前高度不变，同时让K1～K4回到已保存的0°姿态。')) return;
    try {
      elements.returnZeroStatus.textContent = '分轴回零：K1～K4正在回零，K0保持当前高度';
      elements.returnZeroStatus.className = 'pill warn';
      await api.post('/api/command/return_arm_zero');
      elements.returnZeroStatus.textContent = '分轴回零：K1～K4目标已发送（K0保持）';
      elements.returnZeroStatus.className = 'pill good';
    } catch (error) {
      elements.returnZeroStatus.textContent = `分轴回零：${error.message}`;
      elements.returnZeroStatus.className = 'pill bad';
    }
  });
  elements.returnZZero.addEventListener('click', async () => {
    if (!window.confirm('确认K0路径安全？将保持K1～K4不变，让升降柱回到零位上方3 mm的安全位置。')) return;
    try {
      elements.returnZeroStatus.textContent = '分轴回零：Z / K0正在回到安全位置 +3 mm';
      elements.returnZeroStatus.className = 'pill warn';
      await api.post('/api/command/return_z_zero');
      elements.returnZeroStatus.textContent = '分轴回零：Z / K0安全位置 +3 mm目标已发送';
      elements.returnZeroStatus.className = 'pill good';
    } catch (error) {
      elements.returnZeroStatus.textContent = `分轴回零：${error.message}`;
      elements.returnZeroStatus.className = 'pill bad';
    }
  });
  elements.setZero.addEventListener('click', () => {
    if (!window.confirm('将把当前五轴实体位置永久保存为“收纳零位”，用于仿真、FK和IK；只写软件配置，不修改电机内部零点。确认所有电机已下电，K0位于收纳高度，K1-K4与实体收纳结构完全对齐？')) return;
    api.post('/api/command/set_zero').catch(showError);
  });
  bindJointJog({ getLatestState, elements, showError });
  elements.motionSpeed.addEventListener('change', async () => {
    try {
      const multiplier = Number(elements.motionSpeed.value);
      await api.post('/api/speed', { multiplier });
      elements.motionSpeedStatus.textContent = `实机/仿真速度: ${Math.round(multiplier * 100)}%`;
      elements.motionSpeedStatus.className = 'pill good';
      localStorage.setItem('therapyRobotMotionSpeed', String(multiplier));
    } catch (error) {
      elements.motionSpeedStatus.textContent = `速度设置: ${error.message}`;
      elements.motionSpeedStatus.className = 'pill bad';
    }
  });
  const savedSpeed = localStorage.getItem('therapyRobotMotionSpeed');
  if (savedSpeed && [...elements.motionSpeed.options].some((option) => option.value === savedSpeed)) {
    elements.motionSpeed.value = savedSpeed;
    elements.motionSpeed.dispatchEvent(new Event('change'));
  }
  elements.startSelectedAcupoints.addEventListener('click', async () => {
    if (elements.startSelectedAcupoints.disabled) return;
    const names = getSelectedAcupoints();
    if (!names.length) {
      elements.acupointSequenceStatus.textContent = '自动序列: 请先点击选择穴位';
      elements.acupointSequenceStatus.className = 'pill warn';
      return;
    }
    try {
      await api.post('/api/acupoint_sequence/start', { names: names.join(',') });
      elements.acupointSequenceStatus.textContent = `自动序列: 已启动所选 ${names.length} 个穴位`;
      elements.acupointSequenceStatus.className = 'pill good';
    } catch (error) {
      renderAcupointLockError(error);
    }
  });
  elements.startAcupointSequence.addEventListener('click', () => {
    if (elements.startAcupointSequence.disabled) return;
    api.post('/api/acupoint_sequence/start', { names: '' })
      .catch(renderAcupointLockError);
  });
  elements.stopAcupointSequence.addEventListener('click', () => api.post('/api/acupoint_sequence/stop').catch(showError));

  const renderMotionTestPointInfo = () => {
    const point = motionTestPoints.find((item) => String(item.index) === String(elements.motionTestPointSelect?.value));
    if (!elements.motionTestPointInfo) return;
    if (!point) {
      elements.motionTestPointInfo.textContent = '测试点尚未加载';
      return;
    }
    elements.motionTestPointInfo.textContent = `${point.name}：${point.description}；目标 X ${Number(point.x_mm).toFixed(1)} · Y ${Number(point.y_mm).toFixed(1)} · Z ${Number(point.z_mm).toFixed(1)} mm，法向 +Z`;
  };
  const selectedMotionTestSide = () => elements.motionTestSide?.value === 'left' ? 'left' : 'right';
  const loadMotionTestPoints = async () => {
    try {
      const payload = await api.get(`/api/motion_test/points?side=${selectedMotionTestSide()}`);
      motionTestPoints = Array.isArray(payload?.points) ? payload.points : [];
      if (!elements.motionTestPointSelect) return;
      elements.motionTestPointSelect.innerHTML = motionTestPoints.map((point) =>
        `<option value="${point.index}">${point.index}. ${point.name}</option>`).join('');
      renderMotionTestPointInfo();
    } catch (error) {
      if (elements.motionTestStatus) {
        elements.motionTestStatus.textContent = `测试点: ${error.message}`;
        elements.motionTestStatus.className = 'pill bad';
      }
    }
  };
  loadMotionTestPoints();
  elements.motionTestSide?.addEventListener('change', loadMotionTestPoints);
  elements.motionTestPointSelect?.addEventListener('change', renderMotionTestPointInfo);
  elements.simulateMotionTest?.addEventListener('click', async () => {
    const button = elements.simulateMotionTest;
    button.disabled = true;
    elements.motionTestStatus.dataset.simulationOnly = 'true';
    elements.motionTestProgress.dataset.simulationOnly = 'true';
    elements.motionTestStatus.textContent = '测试点: 正在进行独立仿真，不会发送电机命令';
    elements.motionTestStatus.className = 'pill warn';
    try {
      const result = await api.post('/api/motion_test/simulate', { side: selectedMotionTestSide() });
      const points = Array.isArray(result?.points) ? result.points : [];
      const passed = result?.result === 'all_points_passed' && result?.motor_command_written === false;
      if (passed) playMotionPreview?.(points);
      elements.motionTestProgress.textContent = points.map((point) => {
        const joints = point.joints || {};
        const jointText = point.ok
          ? `K0 ${Number(joints.k0_mm).toFixed(1)} mm，K1 ${Number(joints.k1_deg).toFixed(1)}°，K2 ${Number(joints.k2_deg).toFixed(1)}°`
          : point.reason;
        return `${point.index}.${point.name}: ${point.ok ? '通过' : '失败'}；${jointText}`;
      }).join(' | ');
      elements.motionTestStatus.textContent = passed
        ? `测试点: 实时起点整轨预检 ${points.length}/${points.length} 通过，未发送任何电机命令`
        : `测试点: 独立仿真未通过（${points.find((point) => !point.ok)?.reason || 'unknown'}）`;
      elements.motionTestStatus.className = passed ? 'pill good' : 'pill bad';
    } catch (error) {
      elements.motionTestStatus.textContent = `测试点: 独立仿真失败：${error.message}`;
      elements.motionTestStatus.className = 'pill bad';
    } finally {
      button.disabled = false;
    }
  });
  elements.sendMotionTestPoint?.addEventListener('click', async () => {
    try {
      delete elements.motionTestStatus.dataset.simulationOnly;
      delete elements.motionTestProgress.dataset.simulationOnly;
      const index = Number(elements.motionTestPointSelect.value);
      const result = await api.post('/api/motion_test/point', {
        index,
        side: selectedMotionTestSide(),
      });
      elements.motionTestStatus.textContent = `测试点: 已发送 ${result.name || index}，后端IK/碰撞检查通过`;
      elements.motionTestStatus.className = 'pill good';
    } catch (error) {
      elements.motionTestStatus.textContent = `测试点: ${error.message}`;
      elements.motionTestStatus.className = 'pill bad';
    }
  });
  elements.startMotionTestSequence?.addEventListener('click', async () => {
    try {
      delete elements.motionTestStatus.dataset.simulationOnly;
      delete elements.motionTestProgress.dataset.simulationOnly;
      const result = await api.post('/api/motion_test/sequence/start', { side: selectedMotionTestSide() });
      elements.motionTestStatus.textContent = result.running
        ? '测试点: 完整安全轨迹已在运行'
        : `测试点: 已通过整轨预检并启动 ${result.point_count || motionTestPoints.length} 个路径点`;
      elements.motionTestStatus.className = 'pill good';
    } catch (error) {
      elements.motionTestStatus.textContent = `测试点: ${error.message}`;
      elements.motionTestStatus.className = 'pill bad';
    }
  });
  elements.stopMotionTestSequence?.addEventListener('click', async () => {
    try {
      delete elements.motionTestStatus.dataset.simulationOnly;
      delete elements.motionTestProgress.dataset.simulationOnly;
      await api.post('/api/motion_test/sequence/stop');
      elements.motionTestStatus.textContent = '测试点: 序列已停止，电机停止命令已发送';
      elements.motionTestStatus.className = 'pill warn';
    } catch (error) {
      elements.motionTestStatus.textContent = `测试点: ${error.message}`;
      elements.motionTestStatus.className = 'pill bad';
    }
  });
}
