import { api } from './api.js';

const axisNames = ['K0 升降', 'K1 大臂', 'K2 小臂', 'K3 腕关节', 'K4 末端关节'];

function axisMotor(state, axis) {
  const mapping = state?.axis_map?.[axis];
  if (!mapping) return null;
  return { mapping, motor: state.groups?.[mapping.group]?.motors?.[mapping.axis] };
}

export function renderJointJogState(state, elements) {
  if (!elements.jointJogStatus) return;
  const axes = Array.from({ length: 5 }, (_, axis) => axisMotor(state, axis));
  const available = axes.filter((pair) => pair?.motor);
  const offline = available.filter(({ motor }) => !motor.online).length;
  const faulted = available.filter(({ motor }) => motor.fault).length;
  const enabled = available.filter(({ motor }) => motor.enabled).length;
  const k0 = axes[0]?.motor;
  const brake = k0?.brake_supported
    ? (k0.brake_state_known ? (k0.brake_engaged ? 'K0抱闸已合' : 'K0抱闸已松') : 'K0抱闸未知')
    : 'K0无抱闸状态';
  if (elements.jointPowerStatus) {
    elements.jointPowerStatus.textContent = `电机电源：${enabled}/5 已上电，离线 ${offline}，故障 ${faulted}，${brake}`;
    elements.jointPowerStatus.className = offline || faulted
      ? 'pill bad'
      : (enabled === 5 ? 'pill good' : (enabled === 0 ? 'pill' : 'pill warn'));
  }
  const axis = Number(elements.jointJogAxis.value);
  const pair = axisMotor(state, axis);
  if (!pair?.motor) {
    elements.jointJogStatus.textContent = '单关节点动：状态不可用';
    elements.jointJogStatus.className = 'pill bad';
    return;
  }
  const { mapping, motor } = pair;
  const actual = Number(motor.actual_motor_native) * Number(mapping.motor_native_to_gui_display);
  const readiness = `online=${motor.online} enabled=${motor.enabled} fault=${motor.fault}`;
  const selectedBrake = motor.brake_supported
    ? `，抱闸=${motor.brake_state_known ? (motor.brake_engaged ? '已合' : '已松') : '未知'}`
    : '';
  elements.jointJogStatus.textContent = `${axisNames[axis]}：${actual.toFixed(3)} ${mapping.gui_display_unit}，${readiness}${selectedBrake}`;
  elements.jointJogStatus.className = motor.online && motor.enabled && !motor.fault ? 'pill good' : 'pill warn';
}

export function bindJointJog({ getLatestState, elements, showError }) {
  const render = () => renderJointJogState(getLatestState(), elements);
  const populateSteps = () => {
    const liftAxis = Number(elements.jointJogAxis.value) === 0;
    const steps = liftAxis ? [5, 10, 20, 50, 100] : [0.5, 1, 2, 5, 10];
    const selected = liftAxis ? 20 : 5;
    elements.jointJogStep.replaceChildren(...steps.map((step) => {
      const option = document.createElement('option');
      option.value = String(step);
      option.textContent = String(step);
      option.selected = step === selected;
      return option;
    }));
  };
  elements.jointJogAxis.addEventListener('change', () => {
    populateSteps();
    render();
  });
  populateSteps();
  for (const button of elements.jointJogButtons) {
    button.addEventListener('click', async () => {
      const axis = Number(elements.jointJogAxis.value);
      const delta = Number(elements.jointJogStep.value) * Number(button.dataset.jointJogSign);
      if (axis === 0 && !window.confirm(`K0 是重力升降轴，本次将移动 ${delta > 0 ? '+' : ''}${delta} mm。确认机械臂已可靠支撑、人员远离，并准备好立即停止？`)) return;
      try {
        elements.jointJogStatus.textContent = `${axisNames[axis]}：发送 ${delta > 0 ? '+' : ''}${delta} ${axis === 0 ? 'mm' : 'deg'}...`;
        elements.jointJogStatus.className = 'pill warn';
        const result = await api.post('/api/command/jog_axis', { axis, delta_display: delta });
        elements.jointJogStatus.textContent = `${axisNames[axis]}：已接受目标 ${Number(result.target_display).toFixed(3)} ${result.unit}（请观察实际反馈）`;
        elements.jointJogStatus.className = 'pill good';
      } catch (error) {
        elements.jointJogStatus.textContent = `${axisNames[axis]}：${error.message}`;
        elements.jointJogStatus.className = 'pill bad';
        showError(error);
      }
    });
  }
  const populateRecoverySteps = () => {
    if (!elements.recoveryJogStep || !elements.recoveryJogAxis) return;
    const axis = Number(elements.recoveryJogAxis.value);
    const steps = axis === 0 ? [0.5, 1, 2, 5] : [0.5, 1, 2];
    const current = Number(elements.recoveryJogStep.value);
    elements.recoveryJogStep.replaceChildren(...steps.map((step) => {
      const option = document.createElement('option');
      option.value = String(step);
      option.textContent = String(step);
      option.selected = step === (steps.includes(current) ? current : 1);
      return option;
    }));
  };
  elements.recoveryJogAxis?.addEventListener('change', populateRecoverySteps);
  populateRecoverySteps();
  for (const button of elements.recoveryJogButtons || []) {
    button.addEventListener('click', async () => {
      const axis = Number(elements.recoveryJogAxis.value);
      const sign = Number(button.dataset.recoveryJogSign);
      const delta = Number(elements.recoveryJogStep.value) * sign;
      if (axis === 0 && delta < 0) {
        elements.recoveryJogStatus.textContent = '恢复点动：K0在恢复模式只允许向上';
        elements.recoveryJogStatus.className = 'pill bad';
        return;
      }
      const unit = axis === 0 ? 'mm' : 'deg';
      if (!window.confirm(`${axisNames[axis]} 将在恢复模式移动 ${delta > 0 ? '+' : ''}${delta} ${unit}。确认人员远离、物理急停可用，并且只需脱离当前碰撞？`)) return;
      try {
        elements.recoveryJogStatus.textContent = `恢复点动：发送 ${axisNames[axis]} ${delta > 0 ? '+' : ''}${delta} ${unit}...`;
        elements.recoveryJogStatus.className = 'pill warn';
        const result = await api.post('/api/command/recovery_jog_axis', {
          axis, delta_display: delta,
        });
        elements.recoveryJogStatus.textContent = `恢复点动：已发送 ${axisNames[axis]} ${delta > 0 ? '+' : ''}${delta} ${unit}；请观察实体，必要时立即停止`;
        elements.recoveryJogStatus.className = 'pill good';
      } catch (error) {
        elements.recoveryJogStatus.textContent = `恢复点动：${error.message}`;
        elements.recoveryJogStatus.className = 'pill bad';
        showError(error);
      }
    });
  }
  for (const button of elements.jointContinuousButtons || []) {
    button.addEventListener('click', async () => {
      const axis = Number(elements.jointJogAxis.value);
      const direction = Number(button.dataset.jointContinuousDirection);
      const speedText = axis === 0 ? '配置速度' : '1 deg/s';
      const directionText = direction > 0 ? '+' : '−';
      const warning = axis === 0
        ? `K0 将以 ${speedText} 朝 ${directionText} 方向持续运动，直到手动停止或到达软限位。确认升降轴已可靠支撑、人员远离、抱闸已松并准备好立即停止？`
        : `${axisNames[axis]} 将以 ${speedText} 朝 ${directionText} 方向持续运动，直到手动停止或到达软限位。确认人员远离并准备好立即停止？`;
      if (!window.confirm(warning)) return;
      try {
        elements.jointContinuousStatus.textContent =
          `${axisNames[axis]}：正在请求 ${directionText} 方向匀速运动...`;
        elements.jointContinuousStatus.className = 'pill warn';
        const result = await api.post('/api/command/jog_axis_continuous', {
          axis, direction,
        });
        elements.jointContinuousStatus.textContent =
          `${axisNames[axis]}：正在以 ${speedText} 朝 ${directionText} 方向运动；请观察实体，按“立即停止”结束`;
        elements.jointContinuousStatus.className = 'pill good';
        elements.jointJogStatus.textContent =
          `${axisNames[axis]}：匀速目标为软限位 ${Number(result.soft_limit_display).toFixed(3)} ${result.unit}`;
      } catch (error) {
        elements.jointContinuousStatus.textContent = `${axisNames[axis]}：${error.message}`;
        elements.jointContinuousStatus.className = 'pill bad';
        showError(error);
      }
    });
  }
  elements.jointJogEnable.addEventListener('click', async () => {
    if (!window.confirm('全部上电会使能 K0-K4，并松开 K0 抱闸。确认 K0 已可靠支撑、物理急停可用且机械臂周围无人？')) return;
    try {
      elements.jointPowerStatus.textContent = '电机电源：正在请求全部上电并松开 K0 抱闸...';
      elements.jointPowerStatus.className = 'pill warn';
      await api.post('/api/command/enable_all');
    } catch (error) {
      elements.jointPowerStatus.textContent = `电机电源：上电失败，${error.message}`;
      elements.jointPowerStatus.className = 'pill bad';
      showError(error);
    }
  });
  elements.jointJogStop.addEventListener('click', async () => {
    try {
      await api.post('/api/command/stop_all');
      if (elements.jointContinuousStatus) {
        elements.jointContinuousStatus.textContent = '单轴匀速：已发送停止；K0 已请求合闸';
        elements.jointContinuousStatus.className = 'pill warn';
      }
    } catch (error) {
      showError(error);
    }
  });
  elements.jointJogDisable.addEventListener('click', () => api.post('/api/command/disable_all').catch(showError));
}
