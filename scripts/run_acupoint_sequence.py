#!/usr/bin/env python3
import argparse
import json
import math
import os
import time
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from collections import Counter
from types import SimpleNamespace

from send_acupoint_endpoint import build_target, load_acupoints, post_json


RUNTIME_DIR_TEXT = os.environ.get('THERAPY_ROBOT_RUNTIME_DIR', '/tmp/therapy_robot')
if (len(RUNTIME_DIR_TEXT) < 2 or len(RUNTIME_DIR_TEXT) > 4095 or
        not RUNTIME_DIR_TEXT.startswith('/') or RUNTIME_DIR_TEXT.endswith('/') or
        any(part in ('', '.', '..') for part in RUNTIME_DIR_TEXT[1:].split('/')) or
        any(not (char.isascii() and (char.isalnum() or char in '/_.-'))
            for char in RUNTIME_DIR_TEXT)):
    raise ValueError('invalid THERAPY_ROBOT_RUNTIME_DIR')
RUNTIME_DIR = Path(RUNTIME_DIR_TEXT)

AUTOMATIC_EXECUTION_LOCK = {
    'ok': False,
    'execution_locked': True,
    'error_code': 'automatic_trajectory_locked',
    'error': '完整自动轨迹尚未完成安全复核，当前仅允许只读仿真预检',
    'motor_command_written': False,
    'motion_started': False,
}


def resolve_result_path(result):
    if result and result != 'latest':
        return Path(result)
    root = Path('/home/zzq/PTR/therapy_robot/data')
    matches = sorted(root.rglob('analysis_result.json'), key=lambda x: x.stat().st_mtime, reverse=True)
    if not matches:
        raise FileNotFoundError(f'未在 {root} 下找到 analysis_result.json')
    return matches[0]


def get_json(url, timeout=3.0):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        text = response.read().decode('utf-8')
        return json.loads(text) if text else {}


def current_tip_mm(base_url):
    state = get_json(base_url.rstrip('/') + '/api/state')
    sim = state.get('simulation') or {}
    return [
        float(sim.get('end_effector_x_m') or 0.0) * 1000.0,
        float(sim.get('end_effector_y_m') or 0.0) * 1000.0,
        float(sim.get('end_effector_z_m') or 0.0) * 1000.0,
    ]


def rx_ry_from_axis(axis):
    n = math.sqrt(sum(float(v) * float(v) for v in axis))
    if n < 1e-12:
        raise ValueError('normal vector length is zero')
    x, y, z = [float(v) / n for v in axis]
    return math.degrees(math.asin(max(-1.0, min(1.0, -y)))), math.degrees(math.atan2(x, z))


def normalize3(v):
    n = math.sqrt(sum(float(x) * float(x) for x in v))
    if n < 1e-12:
        raise ValueError('normal vector length is zero')
    return [float(x) / n for x in v]


def build_target_relative(acupoint, args, current_tip, press_mm):
    p_camera_mm = [float(v) * 1000.0 for v in acupoint['point_camera_m']]
    n_base = normalize3(acupoint['normal_camera'])
    if args.invert_normal:
        n_base = [-v for v in n_base]
    camera_offset_mm = [args.camera_offset_x, args.camera_offset_y, args.camera_offset_z]
    surface_delta_mm = [
        camera_offset_mm[0] + p_camera_mm[0],
        camera_offset_mm[1] + p_camera_mm[1],
        camera_offset_mm[2] - p_camera_mm[2],
    ]
    surface_base = [current_tip[i] + surface_delta_mm[i] for i in range(3)]
    offset = args.standoff_mm - press_mm
    target_mm = [surface_base[i] + n_base[i] * offset for i in range(3)]
    rx_deg, ry_deg = rx_ry_from_axis(n_base)
    payload = {
        'x_m': target_mm[0] / 1000.0,
        'y_m': target_mm[1] / 1000.0,
        'z_m': target_mm[2] / 1000.0,
        'rx_rad': math.radians(rx_deg),
        'ry_rad': math.radians(ry_deg),
        'rz_rad': 0.0,
    }
    return surface_base, n_base, target_mm, (rx_deg, ry_deg), payload, {'type': 'relative_to_current_tip'}

def choose_points(points, names):
    if not names:
        return points
    order = [name.strip() for name in names.split(',') if name.strip()]
    selected = []
    available = {p.get('name'): p for p in points}
    missing = []
    for name in order:
        point = available.get(name)
        if point is None:
            missing.append(name)
        else:
            selected.append(point)
    if missing:
        raise ValueError(f"未找到穴位: {', '.join(missing)}；可用: {', '.join(str(p.get('name')) for p in points)}")
    return selected


def args_for_target(args, press_mm):
    return SimpleNamespace(
        extrinsics=args.extrinsics,
        calib_tx=args.calib_tx,
        calib_ty=args.calib_ty,
        calib_tz=args.calib_tz,
        calib_rx=args.calib_rx,
        calib_ry=args.calib_ry,
        calib_rz=args.calib_rz,
        standoff_mm=args.standoff_mm,
        press_mm=press_mm,
        invert_normal=args.invert_normal,
    )


def ik_check(base_url, payload):
    return post_json(base_url.rstrip('/') + '/api/ik/check', payload)


def send_endpoint(base_url, payload):
    return post_json(base_url.rstrip('/') + '/api/command/endpoint_target', payload)


def position_error_mm(state, payload):
    sim = state.get('simulation') or {}
    actual = [
        float(sim.get('end_effector_x_m') or 0.0),
        float(sim.get('end_effector_y_m') or 0.0),
        float(sim.get('end_effector_z_m') or 0.0),
    ]
    target = [float(payload['x_m']), float(payload['y_m']), float(payload['z_m'])]
    return math.sqrt(sum((actual[i] - target[i]) ** 2 for i in range(3))) * 1000.0


def wait_until_reached(base_url, payload, tolerance_mm, timeout_sec):
    deadline = time.monotonic() + timeout_sec
    last_state = None
    last_error = None
    while time.monotonic() < deadline:
        state = get_json(base_url.rstrip('/') + '/api/state')
        last_state = state
        endpoint = ((state.get('control') or {}).get('endpoint_target') or {})
        status = int(endpoint.get('status') or 0)
        last_error = position_error_mm(state, payload)
        if status == 2 and last_error <= tolerance_mm:
            return state, last_error
        if status == 3:
            raise RuntimeError(f"后端拒绝目标: {endpoint.get('last_error') or 'unknown'}")
        time.sleep(0.1)
    raise TimeoutError(f"等待到位超时: last_error={last_error:.3f} mm" if last_error is not None else '等待到位超时')


def build_steps(acupoint, args, current_tip=None):
    if args.target_frame == 'relative':
        if current_tip is None:
            raise ValueError('relative 模式需要 current_tip')
        approach_info = build_target_relative(acupoint, args, current_tip, press_mm=0.0)
        massage_info = build_target_relative(acupoint, args, current_tip, press_mm=args.press_mm)
    else:
        approach_info = build_target(acupoint, args_for_target(args, press_mm=0.0))
        massage_info = build_target(acupoint, args_for_target(args, press_mm=args.press_mm))
    steps = [
        ('approach', approach_info),
        ('massage', massage_info),
    ]
    if not args.no_retract:
        steps.append(('retract', approach_info))
    return steps


def local_z_info(acupoint, args, current_tip, z_offset_mm):
    surface_base, n_base, _, _, _, extrinsics_info = build_target_relative(acupoint, args, current_tip, press_mm=args.press_mm)
    target_mm = [surface_base[0], surface_base[1], surface_base[2] + z_offset_mm]
    rx_deg, ry_deg = rx_ry_from_axis(n_base)
    payload = {
        'x_m': target_mm[0] / 1000.0,
        'y_m': target_mm[1] / 1000.0,
        'z_m': target_mm[2] / 1000.0,
        'rx_rad': math.radians(rx_deg),
        'ry_rad': math.radians(ry_deg),
        'rz_rad': 0.0,
    }
    return surface_base, n_base, target_mm, (rx_deg, ry_deg), payload, extrinsics_info


def build_local_z_steps(acupoint, args, current_tip=None):
    if args.target_frame != 'relative':
        return build_steps(acupoint, args, current_tip)
    if current_tip is None:
        raise ValueError('relative 模式需要 current_tip')
    overhead_info = local_z_info(acupoint, args, current_tip, z_offset_mm=args.standoff_mm)
    massage_info = local_z_info(acupoint, args, current_tip, z_offset_mm=0.0)
    steps = [
        ('travel', overhead_info),
        ('press', massage_info),
    ]
    if not args.no_retract:
        steps.append(('lift', overhead_info))
    return steps


def preview_step(name, step_name, info, ik):
    surface_base, n_base, target_mm, angles, payload, extrinsics_info = info
    return {
        'name': name,
        'step': step_name,
        'surface_base_mm': [round(v, 3) for v in surface_base],
        'normal_base': [round(v, 6) for v in n_base],
        'target_tip_mm': [round(v, 3) for v in target_mm],
        'rx_ry_deg': [round(angles[0], 3), round(angles[1], 3)],
        'ik_ok': bool(ik.get('ok')),
        'ik_reason': ik.get('reason'),
        'payload': payload,
        'extrinsics': extrinsics_info.get('type') if extrinsics_info else 'calib_args',
    }


def write_progress(progress):
    path = RUNTIME_DIR / 'acupoint_sequence_progress.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.json.tmp')
    tmp.write_text(json.dumps(progress, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def progress_points_from_plans(point_plans):
    items = []
    for index, plan in enumerate(point_plans, start=1):
        acupoint = plan['acupoint']
        failed = plan['failed']
        items.append({
            'index': index,
            'name': acupoint.get('name'),
            'status': 'skipped' if failed else 'pending',
            'step': '',
            'message': failed[0]['ik_reason'] if failed else '',
        })
    return items



def scan_payload_from_tip(current_tip, args):
    x = current_tip[0] if args.scan_x_mm is None else args.scan_x_mm
    y = current_tip[1] if args.scan_y_mm is None else args.scan_y_mm
    z = args.scan_z_mm
    return {
        'x_m': x / 1000.0,
        'y_m': y / 1000.0,
        'z_m': z / 1000.0,
        'rx_rad': 0.0,
        'ry_rad': 0.0,
        'rz_rad': 0.0,
    }


def move_to_scan_pose(base_url, args):
    tip = current_tip_mm(base_url)
    payload = scan_payload_from_tip(tip, args)
    ik = ik_check(base_url, payload) if args.check_backend else {'ok': True, 'reason': 'skipped'}
    if not ik.get('ok') and not args.force:
        raise RuntimeError(f"高处识别位 IK失败: {ik.get('reason')}")
    if args.execute:
        response = send_endpoint(base_url, payload)
        print(json.dumps({'step': 'scan_pose', 'sent': response}, ensure_ascii=False))
        if args.wait_reached:
            _, err = wait_until_reached(base_url, payload, args.tolerance_mm, args.timeout_sec)
            print(f"高处识别位到位，误差 {err:.3f} mm")
    return payload, ik


def run_scan_command(args):
    if not args.scan_command:
        return
    print(f"运行识别命令: {args.scan_command}")
    completed = subprocess.run(args.scan_command, shell=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"识别命令失败，exit={completed.returncode}")


def select_cycle_acupoint(points, args, index):
    if args.names:
        order = [name.strip() for name in args.names.split(',') if name.strip()]
        if index >= len(order):
            return None
        matches = [p for p in points if p.get('name') == order[index]]
        if not matches:
            raise ValueError(f"本轮识别结果中未找到穴位 {order[index]}")
        return matches[0]
    if index >= len(points):
        return None
    return points[index]


def run_cycle_sequence(args):
    base_url = args.base_url.rstrip('/')
    total = args.limit if args.limit > 0 else None
    index = 0
    print(json.dumps({
        'mode': 'cycle_scan',
        'target_frame': args.target_frame,
        'scan_z_mm': args.scan_z_mm,
        'dwell_sec': args.dwell_sec,
        'execute': args.execute,
    }, ensure_ascii=False, indent=2))
    while total is None or index < total:
        print(f"循环 {index + 1}: 移动到高处识别位")
        move_to_scan_pose(base_url, args)
        run_scan_command(args)
        result_path = resolve_result_path(args.result)
        points = load_acupoints(result_path)
        acupoint = select_cycle_acupoint(points, args, index)
        if acupoint is None:
            print('没有更多穴位，序列结束')
            return
        current_tip = current_tip_mm(base_url) if args.target_frame == 'relative' else None
        steps = build_steps(acupoint, args, current_tip)
        previews = []
        for step_name, info in steps:
            ik = ik_check(base_url, info[4]) if args.check_backend else {'ok': True, 'reason': 'skipped'}
            previews.append(preview_step(acupoint.get('name'), step_name, info, ik))
            if not ik.get('ok') and not args.force:
                print(json.dumps({'cycle': index + 1, 'result': str(result_path), 'selected': acupoint.get('name'), 'plan': previews}, ensure_ascii=False, indent=2))
                raise RuntimeError(f"{acupoint.get('name')} {step_name} IK失败: {ik.get('reason')}")
        print(json.dumps({'cycle': index + 1, 'result': str(result_path), 'selected': acupoint.get('name'), 'plan': previews}, ensure_ascii=False, indent=2))
        if args.execute:
            for step_name, info in steps:
                payload = info[4]
                response = send_endpoint(base_url, payload)
                print(json.dumps({'name': acupoint.get('name'), 'step': step_name, 'sent': response}, ensure_ascii=False))
                if args.wait_reached:
                    _, err = wait_until_reached(base_url, payload, args.tolerance_mm, args.timeout_sec)
                    print(f"{acupoint.get('name')} {step_name} 到位，误差 {err:.3f} mm")
                if step_name in ('massage', 'press'):
                    print(f"{acupoint.get('name')} 按摩停留 {args.dwell_sec:.1f} 秒")
                    time.sleep(args.dwell_sec)
        else:
            print('dry-run: 本轮未执行动作')
        index += 1
    if args.execute:
        print('全部穴位完成，回到高处识别位')
        move_to_scan_pose(base_url, args)



def run_scan_once_sequence(args):
    base_url = args.base_url.rstrip('/')
    print(json.dumps({
        'mode': 'scan_once',
        'target_frame': args.target_frame,
        'scan_z_mm': args.scan_z_mm,
        'dwell_sec': args.dwell_sec,
        'execute': args.execute,
        'skip_unreachable': args.skip_unreachable,
    }, ensure_ascii=False, indent=2))
    print('移动到一次识别位')
    scan_payload, _ = move_to_scan_pose(base_url, args)
    run_scan_command(args)
    result_path = resolve_result_path(args.result)
    points = choose_points(load_acupoints(result_path), args.names)
    if args.limit > 0:
        points = points[:args.limit]
    if not points:
        raise ValueError('没有可用穴位点')
    if args.target_frame == 'relative':
        current_tip = current_tip_mm(base_url) if args.execute else [scan_payload['x_m'] * 1000.0, scan_payload['y_m'] * 1000.0, scan_payload['z_m'] * 1000.0]
    else:
        current_tip = None

    point_plans = []
    previews = []
    failed = []
    for acupoint in points:
        steps = []
        point_failed = []
        for step_name, info in build_local_z_steps(acupoint, args, current_tip):
            ik = ik_check(base_url, info[4]) if args.check_backend else {'ok': True, 'reason': 'skipped'}
            preview = preview_step(acupoint.get('name'), step_name, info, ik)
            previews.append(preview)
            steps.append((step_name, info, ik))
            if not ik.get('ok'):
                point_failed.append(preview)
                failed.append(preview)
        point_plans.append({'index': len(point_plans) + 1, 'acupoint': acupoint, 'steps': steps, 'failed': point_failed})

    executable = [plan for plan in point_plans if not plan['failed']]
    print(json.dumps({
        'result': str(result_path),
        'current_tip_mm': [round(v, 3) for v in current_tip] if current_tip else None,
        'count': len(points),
        'reachable_points': len(executable),
        'skipped_points': len(points) - len(executable),
        'steps': len(previews),
        'plan': previews,
    }, ensure_ascii=False, indent=2))
    progress = {
        'mode': 'scan_once',
        'result': str(result_path),
        'running': bool(args.execute),
        'current_index': 0,
        'current_name': '',
        'current_step': 'planned',
        'total': len(points),
        'reachable': len(executable),
        'skipped': len(points) - len(executable),
        'completed': 0,
        'points': progress_points_from_plans(point_plans),
        'message': '计划生成完成',
        'updated_at': time.time(),
    }
    write_progress(progress)
    if failed:
        print(json.dumps({'ik_failed_steps': len(failed), 'failure_summary': dict(Counter(item['ik_reason'] for item in failed))}, ensure_ascii=False, indent=2))
    if failed and not args.force and not args.skip_unreachable:
        raise SystemExit(f'后端IK检查失败 {len(failed)} 步，未执行。若确认安全可追加 --force 或 --skip-unreachable。')
    if not executable:
        raise SystemExit('没有可执行的可达穴位，未执行。')
    if not args.execute:
        print('dry-run: 自动执行已锁定，本次仅输出计划。')
        return

    for idx, plan in enumerate(executable, start=1):
        acupoint = plan['acupoint']
        original_index = plan['index']
        progress['current_index'] = idx
        progress['current_name'] = acupoint.get('name') or ''
        progress['current_step'] = 'start'
        progress['message'] = f"{acupoint.get('name')} 开始"
        progress['points'][original_index - 1]['status'] = 'running'
        progress['points'][original_index - 1]['step'] = 'start'
        progress['updated_at'] = time.time()
        write_progress(progress)
        print(f"[{idx}/{len(executable)}] {acupoint.get('name')} 开始")
        for step_name, info, _ in plan['steps']:
            progress['current_step'] = step_name
            progress['message'] = f"{acupoint.get('name')} {step_name}"
            progress['points'][original_index - 1]['step'] = step_name
            progress['updated_at'] = time.time()
            write_progress(progress)
            payload = info[4]
            response = send_endpoint(base_url, payload)
            print(json.dumps({'name': acupoint.get('name'), 'step': step_name, 'sent': response}, ensure_ascii=False))
            if args.wait_reached:
                _, err = wait_until_reached(base_url, payload, args.tolerance_mm, args.timeout_sec)
                print(f"{acupoint.get('name')} {step_name} 到位，误差 {err:.3f} mm")
            if step_name in ('massage', 'press'):
                progress['current_step'] = 'dwell'
                progress['message'] = f"{acupoint.get('name')} 按摩停留 {args.dwell_sec:.1f} 秒"
                progress['points'][original_index - 1]['step'] = 'dwell'
                progress['updated_at'] = time.time()
                write_progress(progress)
                print(f"{acupoint.get('name')} 按摩停留 {args.dwell_sec:.1f} 秒")
                time.sleep(args.dwell_sec)
        progress['completed'] += 1
        progress['points'][original_index - 1]['status'] = 'completed'
        progress['points'][original_index - 1]['step'] = 'done'
        progress['message'] = f"{acupoint.get('name')} 完成"
        progress['updated_at'] = time.time()
        write_progress(progress)
        print(f"[{idx}/{len(executable)}] {acupoint.get('name')} 完成")
    progress['running'] = False
    progress['current_step'] = 'done'
    progress['message'] = '全部可达穴位完成'
    progress['updated_at'] = time.time()
    write_progress(progress)
    print('全部可达穴位完成')


def run_sequence(args):
    if args.execute:
        print(json.dumps(AUTOMATIC_EXECUTION_LOCK, ensure_ascii=False))
        raise SystemExit(2)
    if args.cycle_scan:
        run_cycle_sequence(args)
        return
    if args.scan_once:
        run_scan_once_sequence(args)
        return
    base_url = args.base_url.rstrip('/')
    result_path = resolve_result_path(args.result)
    points = choose_points(load_acupoints(result_path), args.names)
    if args.limit > 0:
        points = points[:args.limit]
    if not points:
        raise ValueError('没有可用穴位点')

    current_tip = current_tip_mm(base_url) if args.target_frame == 'relative' else None

    plan = []
    for acupoint in points:
        for step_name, info in build_steps(acupoint, args, current_tip):
            ik = ik_check(base_url, info[4]) if args.check_backend else {'ok': True, 'reason': 'skipped'}
            plan.append((acupoint, step_name, info, ik))

    print(json.dumps({
        'result': str(result_path),
        'target_frame': args.target_frame,
        'current_tip_mm': [round(v, 3) for v in current_tip] if current_tip else None,
        'count': len(points),
        'steps': len(plan),
        'dwell_sec': args.dwell_sec,
        'standoff_mm': args.standoff_mm,
        'press_mm': args.press_mm,
        'execute': args.execute,
        'plan': [preview_step(p.get('name'), step, info, ik) for p, step, info, ik in plan],
    }, ensure_ascii=False, indent=2))

    failed = [preview_step(p.get('name'), step, info, ik) for p, step, info, ik in plan if not ik.get('ok')]
    summary = Counter(item['ik_reason'] for item in failed)
    if failed:
        print(json.dumps({'ik_failed_steps': len(failed), 'failure_summary': dict(summary)}, ensure_ascii=False, indent=2))
    if failed and not args.force:
        raise SystemExit(f'后端IK检查失败 {len(failed)} 步，未执行。若确认安全可追加 --force。')
    if not args.execute:
        print('dry-run: 自动执行已锁定，本次仅输出计划。')
        return

    for idx, acupoint in enumerate(points, start=1):
        print(f"[{idx}/{len(points)}] {acupoint.get('name')} 开始")
        for step_name, info in build_steps(acupoint, args, current_tip):
            payload = info[4]
            if args.check_backend:
                ik = ik_check(base_url, payload)
                if not ik.get('ok') and not args.force:
                    raise RuntimeError(f"{acupoint.get('name')} {step_name} IK失败: {ik.get('reason')}")
            response = send_endpoint(base_url, payload)
            print(json.dumps({'name': acupoint.get('name'), 'step': step_name, 'sent': response}, ensure_ascii=False))
            if args.wait_reached:
                _, err = wait_until_reached(base_url, payload, args.tolerance_mm, args.timeout_sec)
                print(f"{acupoint.get('name')} {step_name} 到位，误差 {err:.3f} mm")
            if step_name in ('massage', 'press'):
                print(f"{acupoint.get('name')} 按摩停留 {args.dwell_sec:.1f} 秒")
                time.sleep(args.dwell_sec)
        print(f"[{idx}/{len(points)}] {acupoint.get('name')} 完成")


def main():
    parser = argparse.ArgumentParser(description='按相机识别到的穴位顺序依次按摩，每个穴位默认停留 10 秒')
    parser.add_argument('--result', default='latest', help='analysis_result.json 路径；默认 latest 表示自动选择 data 下最新结果')
    parser.add_argument('--names', default='', help='逗号分隔的穴位顺序；为空则按识别结果中的顺序执行全部 ok 穴位')
    parser.add_argument('--limit', type=int, default=0, help='只执行前 N 个穴位，0 表示不限')
    parser.add_argument('--base-url', default='http://127.0.0.1:8080')
    parser.add_argument('--target-frame', choices=['relative', 'absolute'], default='relative', help='relative: 使用穴位相对当前末端位移；absolute: 使用相机到基座外参')
    parser.add_argument('--cycle-scan', action='store_true', help='每个穴位前都回高处重新识别的循环流程')
    parser.add_argument('--scan-once', action='store_true', help='先到高处识别一次并记录全部穴位，然后按顺序依次按摩')
    parser.add_argument('--scan-z-mm', type=float, default=450.0, help='高处识别位末端 Z 坐标 mm')
    parser.add_argument('--scan-x-mm', type=float, default=None, help='高处识别位末端 X 坐标 mm；默认保持当前位置')
    parser.add_argument('--scan-y-mm', type=float, default=None, help='高处识别位末端 Y 坐标 mm；默认保持当前位置')
    parser.add_argument('--scan-command', default='', help='每轮到达高处识别位后执行的识别命令；为空则只读取最新 analysis_result.json')
    parser.add_argument('--camera-offset-x', type=float, default=0.0, help='相机中心相对当前末端的 X 偏移 mm')
    parser.add_argument('--camera-offset-y', type=float, default=-217.0, help='相机中心相对当前末端的 Y 偏移 mm')
    parser.add_argument('--camera-offset-z', type=float, default=145.2, help='相机中心相对当前末端的 Z 偏移 mm')
    parser.add_argument('--extrinsics', default='/home/zzq/PTR/therapy_robot/calibration/camera_to_base.json')
    parser.add_argument('--calib-tx', type=float, default=0.0)
    parser.add_argument('--calib-ty', type=float, default=711.0)
    parser.add_argument('--calib-tz', type=float, default=622.1)
    parser.add_argument('--calib-rx', type=float, default=0.0)
    parser.add_argument('--calib-ry', type=float, default=0.0)
    parser.add_argument('--calib-rz', type=float, default=0.0)
    parser.add_argument('--standoff-mm', type=float, default=30.0, help='沿皮肤法线离体预备距离')
    parser.add_argument('--press-mm', type=float, default=30.0, help='从预备点沿法线向皮肤方向下压量；默认等于 standoff，即到达皮肤表面')
    parser.add_argument('--dwell-sec', type=float, default=10.0, help='每个穴位按摩点停留时间')
    parser.add_argument('--tolerance-mm', type=float, default=2.0, help='到位判定的末端位置误差阈值')
    parser.add_argument('--timeout-sec', type=float, default=15.0, help='每一步等待到位超时')
    parser.add_argument('--invert-normal', action='store_true')
    parser.add_argument('--no-retract', action='store_true', help='每个穴位按摩后不回到预备点')
    parser.add_argument('--no-backend-check', dest='check_backend', action='store_false', help='跳过 /api/ik/check')
    parser.add_argument('--no-wait-reached', dest='wait_reached', action='store_false', help='发送后不等待到位')
    parser.add_argument('--execute', action='store_true', help='自动执行当前被安全硬锁；默认只打印计划')
    parser.add_argument('--force', action='store_true', help='即使 IK 检查失败也继续发送')
    parser.add_argument('--skip-unreachable', action='store_true', help='scan-once 中跳过 IK 不可达穴位，继续执行可达穴位')
    parser.set_defaults(check_backend=True, wait_reached=True)
    args = parser.parse_args()
    try:
        run_sequence(args)
    except (FileNotFoundError, ValueError, RuntimeError, TimeoutError, urllib.error.URLError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == '__main__':
    main()
