#!/usr/bin/env python3
"""Preview named Cartesian test points without starting automatic motion."""

import argparse
import json
import math
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


RUNTIME_DIR_TEXT = os.environ.get('THERAPY_ROBOT_RUNTIME_DIR', '/tmp/therapy_robot')
if (len(RUNTIME_DIR_TEXT) < 2 or len(RUNTIME_DIR_TEXT) > 4095 or
        not RUNTIME_DIR_TEXT.startswith('/') or RUNTIME_DIR_TEXT.endswith('/') or
        any(part in ('', '.', '..') for part in RUNTIME_DIR_TEXT[1:].split('/')) or
        any(not (char.isascii() and (char.isalnum() or char in '/_.-'))
            for char in RUNTIME_DIR_TEXT)):
    raise ValueError('invalid THERAPY_ROBOT_RUNTIME_DIR')
RUNTIME_DIR = Path(RUNTIME_DIR_TEXT)
PROGRESS_PATH = RUNTIME_DIR / 'motion_test_progress.json'
AUTOMATIC_EXECUTION_LOCK = {
    'ok': False,
    'execution_locked': True,
    'error_code': 'automatic_trajectory_locked',
    'error': '完整自动轨迹尚未完成安全复核，当前仅允许只读仿真预检',
    'motor_command_written': False,
    'motion_started': False,
}


def get_json(url, timeout=3.0):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        text = response.read().decode('utf-8')
        return json.loads(text) if text else {}


def post_json(url, payload, timeout=5.0):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'},
        method='POST',
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode('utf-8')
            return json.loads(text) if text else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode('utf-8', errors='replace')
        try:
            message = json.loads(body).get('error') or body
        except json.JSONDecodeError:
            message = body
        raise RuntimeError(message or f'HTTP {exc.code}') from exc


def write_progress(progress):
    PROGRESS_PATH.parent.mkdir(parents=True, exist_ok=True)
    progress['updated_at'] = time.time()
    PROGRESS_PATH.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding='utf-8')


def endpoint_error_mm(state, target):
    sim = state.get('simulation') or {}
    actual = [
        float(sim.get('end_effector_x_m') or 0.0) * 1000.0,
        float(sim.get('end_effector_y_m') or 0.0) * 1000.0,
        float(sim.get('end_effector_z_m') or 0.0) * 1000.0,
    ]
    desired = [float(target['x_mm']), float(target['y_mm']), float(target['z_mm'])]
    return math.sqrt(sum((actual[i] - desired[i]) ** 2 for i in range(3)))


def wait_until_reached(base_url, target, tolerance_mm, timeout_sec):
    deadline = time.monotonic() + timeout_sec
    last_error = None
    while time.monotonic() < deadline:
        state = get_json(base_url + '/api/state')
        endpoint = ((state.get('control') or {}).get('endpoint_target') or {})
        status = int(endpoint.get('status') or 0)
        last_error = endpoint_error_mm(state, target)
        if status == 2 and last_error <= tolerance_mm:
            return last_error
        if status == 3:
            raise RuntimeError(f"后端拒绝目标: {endpoint.get('last_error') or 'unknown'}")
        time.sleep(0.1)
    detail = f'{last_error:.2f} mm' if last_error is not None else 'unknown'
    raise TimeoutError(f'等待到位超时，末端误差 {detail}')


def parse_indices(raw, available):
    if not raw.strip():
        return sorted(available)
    indices = []
    for item in raw.split(','):
        item = item.strip()
        if not item:
            continue
        value = int(item)
        if value not in indices:
            indices.append(value)
    if not indices:
        raise ValueError('至少选择一个测试点')
    return indices


def demo_speed_multiplier(index, total):
    if index == 1:
        return 0.80, 'K0高位准备：约4 mm/s'
    if index == 2:
        return 0.45, '机箱附近高位转出：K1约0.9 deg/s，K2约2.25 deg/s'
    if 3 <= index <= 6:
        return 0.80, '机箱外垂直下降：K0约4 mm/s'
    if 7 <= index <= 10:
        return 0.65, '机箱外Y向演示：K1约1.3 deg/s，K2约3.25 deg/s'
    if 11 <= index < total:
        return 0.80, '机箱外垂直抬升：K0约4 mm/s'
    return 0.35, '高位收回：K1约0.7 deg/s，K2约1.75 deg/s'


def run(args):
    if args.execute:
        print(json.dumps(AUTOMATIC_EXECUTION_LOCK, ensure_ascii=False))
        raise SystemExit(2)
    base_url = args.base_url.rstrip('/')
    side = 'left' if args.side == 'left' else 'right'
    catalog_url = base_url + '/api/motion_test/points?' + urllib.parse.urlencode({'side': side})
    catalog = get_json(catalog_url).get('points') or []
    available = {int(point['index']): point for point in catalog}
    indices = parse_indices(args.indices, available)
    missing = [index for index in indices if index not in available]
    if missing:
        raise ValueError(f"不存在的测试点编号: {','.join(str(v) for v in missing)}")
    selected = [available[index] for index in indices]
    expected = list(range(1, len(catalog) + 1))
    if indices != expected:
        raise ValueError('自动三维测试必须执行完整安全轨迹；指定单点请使用控制页的“移动到指定点”')
    preflight = post_json(base_url + '/api/motion_test/simulate', {'side': side})
    if not preflight.get('ok') or preflight.get('motor_command_written') is not False:
        failed = next((p for p in preflight.get('points', []) if not p.get('ok')), {})
        raise RuntimeError(f"启动前整轨预检失败: {failed.get('name', '--')} {failed.get('reason', 'unknown')}")
    print(json.dumps(preflight, ensure_ascii=False, indent=2))
    if not args.execute:
        print('dry-run: 自动执行已锁定，本次仅输出整轨仿真预检。')
        return
    progress = {
        'running': True,
        'total': len(selected),
        'completed': 0,
        'current_index': 0,
        'current_name': '',
        'message': '测试序列准备完成',
        'points': [
            {'index': p['index'], 'name': p['name'], 'status': 'pending'}
            for p in selected
        ],
    }
    write_progress(progress)

    for order, point in enumerate(selected, start=1):
        speed_multiplier, speed_description = demo_speed_multiplier(order, len(selected))
        post_json(base_url + '/api/speed', {'multiplier': speed_multiplier})
        progress['current_index'] = order
        progress['current_name'] = point['name']
        progress['message'] = f"正在移动到 {point['name']}；{speed_description}"
        progress['speed_multiplier'] = speed_multiplier
        progress['speed_description'] = speed_description
        progress['points'][order - 1]['status'] = 'running'
        write_progress(progress)
        response = post_json(base_url + '/api/motion_test/point', {
            'index': point['index'],
            'side': side,
        })
        print(json.dumps({'point': point, 'sent': response}, ensure_ascii=False), flush=True)
        error_mm = wait_until_reached(base_url, point, args.tolerance_mm, args.timeout_sec)
        progress['completed'] = order
        progress['points'][order - 1]['status'] = 'completed'
        progress['points'][order - 1]['error_mm'] = round(error_mm, 3)
        progress['message'] = f"{point['name']} 已到位"
        write_progress(progress)
        time.sleep(args.dwell_sec)

    progress['running'] = False
    progress['current_name'] = ''
    progress['message'] = '全部测试点执行完成'
    write_progress(progress)
    post_json(base_url + '/api/speed', {'multiplier': 0.65})
    print('全部测试点执行完成', flush=True)


def main():
    parser = argparse.ArgumentParser(description='按编号顺序执行保守的机械臂末端测试点')
    parser.add_argument('--indices', default='', help='内部调试参数；自动序列必须包含全部轨迹点')
    parser.add_argument('--side', choices=('left', 'right'), default='right')
    parser.add_argument('--base-url', default='http://127.0.0.1:8080')
    parser.add_argument('--tolerance-mm', type=float, default=3.0)
    parser.add_argument('--timeout-sec', type=float, default=45.0)
    parser.add_argument('--dwell-sec', type=float, default=1.0)
    parser.add_argument('--execute', action='store_true', help='自动执行当前被安全硬锁；默认只运行整轨仿真预检')
    args = parser.parse_args()
    try:
        run(args)
    except (ValueError, RuntimeError, TimeoutError, urllib.error.URLError) as exc:
        if args.execute:
            try:
                progress = json.loads(PROGRESS_PATH.read_text(encoding='utf-8'))
            except (OSError, json.JSONDecodeError):
                progress = {'completed': 0, 'points': []}
            progress.update({
                'running': False,
                'message': f'测试序列停止: {exc}',
                'error': str(exc),
            })
            write_progress(progress)
        raise SystemExit(str(exc)) from exc


if __name__ == '__main__':
    main()
