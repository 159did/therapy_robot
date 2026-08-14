#!/usr/bin/env python3
import argparse
import json
import math
from pathlib import Path

import numpy as np


def deg_to_rad(v):
    return float(v) * math.pi / 180.0


def axis_from_rx_ry_deg(rx_deg, ry_deg):
    rx = deg_to_rad(rx_deg)
    ry = deg_to_rad(ry_deg)
    sx, cx = math.sin(rx), math.cos(rx)
    sy, cy = math.sin(ry), math.cos(ry)
    return np.asarray([sy * cx, -sx, cy * cx], dtype=float)


def load_samples(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    samples = data.get('samples', data if isinstance(data, list) else [])
    clean = []
    for i, s in enumerate(samples):
        if 'k1_deg' not in s or 'k2_deg' not in s:
            raise ValueError(f'样本 {i} 缺少 k1_deg 或 k2_deg')
        item = {'name': s.get('name', f'p{i + 1}'), 'k0_mm': float(s.get('k0_mm', 0.0)), 'k1_deg': float(s['k1_deg']), 'k2_deg': float(s['k2_deg'])}
        if 'wrist_base_mm' in s:
            item['mode'] = 'wrist'
            item['point_mm'] = np.asarray(s['wrist_base_mm'], dtype=float).reshape(3)
        elif 'tip_base_mm' in s:
            item['mode'] = 'tip'
            item['point_mm'] = np.asarray(s['tip_base_mm'], dtype=float).reshape(3)
            axis = np.asarray(s['tool_axis_base'], dtype=float).reshape(3) if 'tool_axis_base' in s else axis_from_rx_ry_deg(s.get('rx_deg', 0.0), s.get('ry_deg', 0.0))
            n = np.linalg.norm(axis)
            if n < 1e-12:
                raise ValueError(f'样本 {i} tool axis 长度为 0')
            item['axis'] = axis / n
        else:
            raise ValueError(f'样本 {i} 需要 wrist_base_mm 或 tip_base_mm')
        clean.append(item)
    if len(clean) < 3:
        raise ValueError('至少需要 3 个样本，建议 8~20 个')
    return clean


def build_linear_system(samples, fit_tool=True, wrist_forward_offset_mm=0.0):
    rows, vals = [], []
    for s in samples:
        t1 = deg_to_rad(s['k1_deg'])
        t12 = deg_to_rad(s['k1_deg'] + s['k2_deg'])
        sin1, cos1 = math.sin(t1), math.cos(t1)
        sin12, cos12 = math.sin(t12), math.cos(t12)
        x, y, z = [float(v) for v in s['point_mm']]
        if s['mode'] == 'tip' and fit_tool:
            ax, ay, az = [float(v) for v in s['axis']]
            tool_terms = [-ax, -ay, -az]
        else:
            tool_terms = [0.0, 0.0, 0.0]
        rows += [[sin1, sin12, 0.0, tool_terms[0]], [cos1, cos12, 0.0, tool_terms[1]], [0.0, 0.0, 1.0, tool_terms[2]]]
        vals += [x - wrist_forward_offset_mm * sin12, y - wrist_forward_offset_mm * cos12, z - s['k0_mm']]
    a = np.asarray(rows, dtype=float)
    return (a if fit_tool else a[:, :3]), np.asarray(vals, dtype=float)


def solve_geometry(samples, fit_tool=True, wrist_forward_offset_mm=0.0):
    a, b = build_linear_system(samples, fit_tool=fit_tool, wrist_forward_offset_mm=wrist_forward_offset_mm)
    params, _, _, singular = np.linalg.lstsq(a, b, rcond=None)
    pred = a @ params
    err = pred - b
    if fit_tool:
        upper, forearm, base_eff, tool = [float(x) for x in params]
    else:
        upper, forearm, base_eff = [float(x) for x in params]
        tool = None
    return {
        'upperArmMm': upper,
        'forearmMm': forearm,
        'baseHeightMinusForearmDropMm': base_eff,
        'wristForwardOffsetMm': float(wrist_forward_offset_mm),
        'toolMm': tool,
        'rmse_mm': float(np.sqrt(np.mean(err ** 2))),
        'max_abs_error_mm': float(np.max(np.abs(err))),
        'rank': int(np.linalg.matrix_rank(a)),
        'singular_values': [float(x) for x in singular],
        'equation': 'wrist=[L1*sin(K1)+L2*sin(K1+K2), L1*cos(K1)+L2*cos(K1+K2), K0+baseEff]; tip=wrist-tool*axis',
    }


def main():
    parser = argparse.ArgumentParser(description='用实测末端/腕点坐标标定 IK 几何长度参数')
    parser.add_argument('--samples', default='/home/zzq/PTR/therapy_robot/calibration/robot_geometry_samples.json')
    parser.add_argument('--out', default='/home/zzq/PTR/therapy_robot/calibration/robot_geometry_calibration.json')
    parser.add_argument('--no-fit-tool', action='store_true')
    parser.add_argument('--wrist-forward-offset-mm', type=float, default=119.0, help='K4 到末端圆柱中心轴沿小臂 forward 的已知水平偏移')
    args = parser.parse_args()
    samples = load_samples(args.samples)
    fit_tool = not args.no_fit_tool and any(s['mode'] == 'tip' for s in samples)
    geom = solve_geometry(samples, fit_tool=fit_tool, wrist_forward_offset_mm=args.wrist_forward_offset_mm)
    out = {'type': 'robot_ik_geometry_calibration', 'source': str(args.samples), 'fit': geom, 'recommended_frontend_model_fields': {'upperArmMm': geom['upperArmMm'], 'forearmMm': geom['forearmMm'], 'wristForwardOffsetMm': geom['wristForwardOffsetMm'], 'toolMm': geom['toolMm'], 'baseHeightMm_minus_forearmDropMm': geom['baseHeightMinusForearmDropMm']}}
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ok': True, 'out': str(out_path), **geom}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
