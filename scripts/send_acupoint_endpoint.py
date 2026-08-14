#!/usr/bin/env python3
import argparse
import json
import math
import urllib.error
import urllib.request
from pathlib import Path

ENDPOINT_MODEL = {
    'base_height_mm': 710.0,
    'upper_arm_mm': 580.0,
    'forearm_mm': 229.0,
    'wrist_forward_offset_mm': 119.0,
    'forearm_drop_mm': 80.0,
    'tool_mm': 153.1,
    'lift_min_mm': -500.0,
    'lift_max_mm': 0.0,
    'theta1_min': -90.0,
    'theta1_max': 90.0,
    'theta2_min': -90.0,
    'theta2_max': 90.0,
    'theta3_min': -45.0,
    'theta3_max': 45.0,
    'theta4_min': -60.0,
    'theta4_max': 60.0,
}


def deg_to_rad(v):
    return v * math.pi / 180.0


def rad_to_deg(v):
    return v * 180.0 / math.pi


def norm3(v):
    return math.sqrt(sum(float(x) * float(x) for x in v))


def normalize3(v):
    n = norm3(v)
    if n < 1e-12:
        raise ValueError('normal vector length is zero')
    return [float(x) / n for x in v]


def dot3(a, b):
    return sum(float(x) * float(y) for x, y in zip(a, b))


def sub3(a, b):
    return [float(x) - float(y) for x, y in zip(a, b)]


def mul3(a, s):
    return [float(x) * float(s) for x in a]


def rotation_matrix_from_euler_deg(rx_deg, ry_deg, rz_deg):
    rx, ry, rz = map(deg_to_rad, (rx_deg, ry_deg, rz_deg))
    sx, cx = math.sin(rx), math.cos(rx)
    sy, cy = math.sin(ry), math.cos(ry)
    sz, cz = math.sin(rz), math.cos(rz)
    return [
        [cz * cy, cz * sy * sx - sz * cx, cz * sy * cx + sz * sx],
        [sz * cy, sz * sy * sx + cz * cx, sz * sy * cx - cz * sx],
        [-sy, cy * sx, cy * cx],
    ]


def mat_vec_mul(m, v):
    return [
        m[0][0] * v[0] + m[0][1] * v[1] + m[0][2] * v[2],
        m[1][0] * v[0] + m[1][1] * v[1] + m[1][2] * v[2],
        m[2][0] * v[0] + m[2][1] * v[1] + m[2][2] * v[2],
    ]


def rx_ry_from_axis(axis):
    x, y, z = normalize3(axis)
    rx = rad_to_deg(math.asin(max(-1.0, min(1.0, -y))))
    ry = rad_to_deg(math.atan2(x, z))
    return rx, ry


def axis_from_rx_ry_deg(rx_deg, ry_deg):
    rx, ry = deg_to_rad(rx_deg), deg_to_rad(ry_deg)
    sx, cx = math.sin(rx), math.cos(rx)
    sy, cy = math.sin(ry), math.cos(ry)
    return [sy * cx, -sx, cy * cx]


def planar_dir(angle):
    return [math.sin(angle), math.cos(angle), 0.0]


def small_arm_side(angle):
    return [math.cos(angle), -math.sin(angle), 0.0]


def wrap_pi(rad):
    while rad > math.pi:
        rad -= 2.0 * math.pi
    while rad < -math.pi:
        rad += 2.0 * math.pi
    return rad


def rotate_around_axis(v, axis, angle):
    axis = normalize3(axis)
    c = math.cos(angle)
    s = math.sin(angle)
    kv = dot3(axis, v)
    cross = [
        axis[1] * v[2] - axis[2] * v[1],
        axis[2] * v[0] - axis[0] * v[2],
        axis[0] * v[1] - axis[1] * v[0],
    ]
    return [v[i] * c + cross[i] * s + axis[i] * kv * (1.0 - c) for i in range(3)]


def endpoint_precheck(target_mm, normal):
    axis = normalize3(normal)
    tip = [float(v) for v in target_mm]
    best_cost = float('inf')

    def orientation_for_yaw(yaw):
        forward = planar_dir(yaw)
        a_forward = max(-1.0, min(1.0, dot3(axis, forward)))
        perp = sub3(axis, mul3(forward, a_forward))
        perp_norm = norm3(perp)
        if perp_norm < 1e-9:
            theta3 = 0.0
            theta4 = -math.pi / 2.0 if a_forward >= 0 else math.pi / 2.0
        else:
            up_after_roll = normalize3(perp)
            side0 = small_arm_side(yaw)
            theta3 = math.atan2(dot3(up_after_roll, side0), up_after_roll[2])
            theta4 = -math.atan2(a_forward, perp_norm)
        theta3_deg = rad_to_deg(theta3)
        theta4_deg = rad_to_deg(theta4)
        if not (ENDPOINT_MODEL['theta3_min'] <= theta3_deg <= ENDPOINT_MODEL['theta3_max'] and ENDPOINT_MODEL['theta4_min'] <= theta4_deg <= ENDPOINT_MODEL['theta4_max']):
            return None
        return theta3, theta4

    for i in range(-720, 721):
        yaw = i * math.pi / 720.0
        orientation = orientation_for_yaw(yaw)
        if orientation is None:
            continue
        theta3, theta4 = orientation
        forward = planar_dir(yaw)
        side = rotate_around_axis(small_arm_side(yaw), forward, theta3)
        wrist_forward = rotate_around_axis(forward, side, theta4)
        p4 = sub3([tip[j] + axis[j] * ENDPOINT_MODEL['tool_mm'] for j in range(3)], mul3(wrist_forward, ENDPOINT_MODEL['wrist_forward_offset_mm']))
        lift = p4[2] - ENDPOINT_MODEL['base_height_mm'] + ENDPOINT_MODEL['forearm_drop_mm']
        if lift < ENDPOINT_MODEL['lift_min_mm'] or lift > ENDPOINT_MODEL['lift_max_mm']:
            continue
        p1 = sub3([p4[0], p4[1], 0.0], mul3(forward, ENDPOINT_MODEL['forearm_mm']))
        theta1 = math.atan2(p1[0], p1[1])
        theta2 = wrap_pi(yaw - theta1)
        theta1_deg = rad_to_deg(theta1)
        theta2_deg = rad_to_deg(theta2)
        if not (ENDPOINT_MODEL['theta1_min'] <= theta1_deg <= ENDPOINT_MODEL['theta1_max'] and ENDPOINT_MODEL['theta2_min'] <= theta2_deg <= ENDPOINT_MODEL['theta2_max']):
            continue
        cost = abs(math.hypot(p1[0], p1[1]) - ENDPOINT_MODEL['upper_arm_mm'])
        best_cost = min(best_cost, cost)
        if cost <= 0.5:
            return True, f"可达: K0={lift:.1f} mm, K1={theta1_deg:.1f}°, K2={theta2_deg:.1f}°, K3={rad_to_deg(theta3):.1f}°, K4={rad_to_deg(theta4):.1f}°"
    if math.isfinite(best_cost):
        return False, f"前端/脚本粗检未找到近似解: 残差 {best_cost:.1f} mm，建议以后端 accepted 为准"
    return False, '姿态不可达: K1-K4 超限'


def load_acupoints(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    points = data.get('template_acupoints') or data.get('acupoints') or []
    return [p for p in points if p.get('ok') and p.get('point_camera_m') and p.get('normal_camera')]


def choose_acupoint(points, name):
    matches = [p for p in points if p.get('name') == name]
    if not matches:
        available = ', '.join(p.get('name', '--') for p in points)
        raise ValueError(f'未找到穴位 {name}，可用: {available}')
    return matches[0]


def post_json(url, payload, timeout=3.0):
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json'}, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as response:
        text = response.read().decode('utf-8')
        return json.loads(text) if text else {}


def load_extrinsics(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    r = data.get('rotation')
    t = data.get('translation_m')
    if r is None or t is None:
        raise ValueError(f'外参文件 {path} 缺少 rotation 或 translation_m')
    r = [[float(x) for x in row] for row in r]
    t = [float(x) * 1000.0 for x in t]
    if len(r) != 3 or any(len(row) != 3 for row in r) or len(t) != 3:
        raise ValueError('外参 rotation 必须是 3x3，translation_m 必须是 3 维')
    return r, t, data


def build_target(acupoint, args):
    extrinsics_info = None
    if args.extrinsics and Path(args.extrinsics).exists():
        rot, trans_mm, extrinsics_info = load_extrinsics(args.extrinsics)
    else:
        rot = rotation_matrix_from_euler_deg(args.calib_rx, args.calib_ry, args.calib_rz)
        trans_mm = [args.calib_tx, args.calib_ty, args.calib_tz]
    p_camera_mm = [float(v) * 1000.0 for v in acupoint['point_camera_m']]
    n_camera = normalize3(acupoint['normal_camera'])
    if args.invert_normal:
        n_camera = [-v for v in n_camera]
    p_base_rot = mat_vec_mul(rot, p_camera_mm)
    n_base = normalize3(mat_vec_mul(rot, n_camera))
    surface_base = [
        p_base_rot[0] + trans_mm[0],
        p_base_rot[1] + trans_mm[1],
        p_base_rot[2] + trans_mm[2],
    ]
    offset = args.standoff_mm - args.press_mm
    target_mm = [surface_base[i] + n_base[i] * offset for i in range(3)]
    rx_deg, ry_deg = rx_ry_from_axis(n_base)
    payload = {
        'x_m': target_mm[0] / 1000.0,
        'y_m': target_mm[1] / 1000.0,
        'z_m': target_mm[2] / 1000.0,
        'rx_rad': deg_to_rad(rx_deg),
        'ry_rad': deg_to_rad(ry_deg),
        'rz_rad': 0.0,
    }
    return surface_base, n_base, target_mm, (rx_deg, ry_deg), payload, extrinsics_info


def main():
    parser = argparse.ArgumentParser(description='把 D405 绿色模板穴位转换并发送为机器人 endpoint_target')
    parser.add_argument('--result', default='/home/zzq/PTR/therapy_robot/data/d405_samples/back_20260617_212933_470/analysis_result.json')
    parser.add_argument('--name', default='大椎', help='穴位名，例如 大椎、肺俞-L、肩井-R')
    parser.add_argument('--base-url', default='http://127.0.0.1:8080')
    parser.add_argument('--extrinsics', default='/home/zzq/PTR/therapy_robot/calibration/camera_to_base.json', help='camera_to_base.json；文件存在时优先使用，设为空字符串则使用 calib-* 参数')
    parser.add_argument('--calib-tx', type=float, default=0.0)
    parser.add_argument('--calib-ty', type=float, default=711.0)
    parser.add_argument('--calib-tz', type=float, default=622.1)
    parser.add_argument('--calib-rx', type=float, default=0.0)
    parser.add_argument('--calib-ry', type=float, default=0.0)
    parser.add_argument('--calib-rz', type=float, default=0.0)
    parser.add_argument('--standoff-mm', type=float, default=30.0, help='沿皮肤法线离体预备距离，默认 30mm')
    parser.add_argument('--press-mm', type=float, default=0.0, help='从预备点沿法线向皮肤下压距离，预览默认 0mm')
    parser.add_argument('--invert-normal', action='store_true', help='如果法线方向反了，启用该项翻转法线')
    parser.add_argument('--execute', action='store_true', help='真正发送给控制后端；不加则只预览')
    parser.add_argument('--force', action='store_true', help='即使前端同款粗检失败也允许发送')
    args = parser.parse_args()

    points = load_acupoints(args.result)
    acupoint = choose_acupoint(points, args.name)
    surface_base, n_base, target_mm, angles, payload, extrinsics_info = build_target(acupoint, args)
    ok, reason = endpoint_precheck(target_mm, n_base)

    preview = {
        'name': acupoint['name'],
        'pixel': acupoint.get('pixel'),
        'surface_base_mm': [round(v, 3) for v in surface_base],
        'normal_base': [round(v, 6) for v in n_base],
        'target_tip_mm': [round(v, 3) for v in target_mm],
        'rx_ry_deg': [round(angles[0], 3), round(angles[1], 3)],
        'standoff_mm': args.standoff_mm,
        'press_mm': args.press_mm,
        'extrinsics': args.extrinsics if extrinsics_info else 'calib_args',
        'extrinsics_rmse_mm': extrinsics_info.get('rmse_mm') if extrinsics_info else None,
        'precheck_ok': ok,
        'precheck': reason,
        'payload': payload,
    }
    print(json.dumps(preview, ensure_ascii=False, indent=2))

    if not args.execute:
        print('dry-run: 未发送。确认安全后追加 --execute。')
        return
    if not ok and not args.force:
        raise SystemExit('粗检失败，未发送。若确认安全可追加 --force。')
    url = args.base_url.rstrip('/') + '/api/command/endpoint_target'
    try:
        response = post_json(url, payload)
    except urllib.error.URLError as exc:
        raise SystemExit(f'发送失败: {exc}') from exc
    print(json.dumps({'sent': True, 'url': url, 'response': response}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
