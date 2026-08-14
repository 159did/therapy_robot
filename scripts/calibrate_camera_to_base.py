#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

import numpy as np


def load_samples(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    samples = data.get('samples', data if isinstance(data, list) else [])
    clean = []
    for i, s in enumerate(samples):
        c = s.get('camera_point_m') or s.get('camera_m') or s.get('camera')
        b = s.get('robot_point_m') or s.get('base_point_m') or s.get('robot_m') or s.get('base')
        if c is None or b is None:
            raise ValueError(f'样本 {i} 缺少 camera_point_m 或 robot_point_m')
        c = np.asarray(c, dtype=float).reshape(3)
        b = np.asarray(b, dtype=float).reshape(3)
        if not np.all(np.isfinite(c)) or not np.all(np.isfinite(b)):
            raise ValueError(f'样本 {i} 包含非数字坐标')
        clean.append({'name': s.get('name', f'p{i + 1}'), 'camera': c, 'base': b})
    if len(clean) < 3:
        raise ValueError('至少需要 3 个不共线标定点，建议 9~20 个')
    return clean


def solve_rigid_transform(camera_points, base_points):
    c = np.asarray(camera_points, dtype=float)
    b = np.asarray(base_points, dtype=float)
    c_mean = c.mean(axis=0)
    b_mean = b.mean(axis=0)
    c0 = c - c_mean
    b0 = b - b_mean
    h = c0.T @ b0
    u, _, vt = np.linalg.svd(h)
    r = vt.T @ u.T
    if np.linalg.det(r) < 0:
        vt[-1, :] *= -1
        r = vt.T @ u.T
    t = b_mean - r @ c_mean
    pred = (r @ c.T).T + t
    err = np.linalg.norm(pred - b, axis=1)
    return r, t, pred, err


def condition_report(points):
    p = np.asarray(points, dtype=float)
    _, s, _ = np.linalg.svd(p - p.mean(axis=0), full_matrices=False)
    rank = int(np.sum(s > max(1e-9, s[0] * 1e-4))) if s.size else 0
    return {'rank': rank, 'singular_values': [float(x) for x in s]}


def main():
    parser = argparse.ArgumentParser(description='用多组对应点求解 D405 相机坐标系到机器人基坐标系的刚体外参')
    parser.add_argument('--samples', default='/home/zzq/PTR/therapy_robot/calibration/camera_to_base_samples.json')
    parser.add_argument('--out', default='/home/zzq/PTR/therapy_robot/calibration/camera_to_base.json')
    parser.add_argument('--min-rmse-mm', type=float, default=10.0, help='超过该 RMSE 仅报警，不阻止输出')
    args = parser.parse_args()

    samples = load_samples(args.samples)
    camera = np.asarray([s['camera'] for s in samples], dtype=float)
    base = np.asarray([s['base'] for s in samples], dtype=float)
    cond = condition_report(camera)
    if cond['rank'] < 2:
        raise SystemExit('标定点分布退化：至少需要不共线点，建议覆盖工作区九宫格')

    r, t, pred, err = solve_rigid_transform(camera, base)
    rmse = float(np.sqrt(np.mean(err ** 2)) * 1000.0)
    max_err = float(np.max(err) * 1000.0)
    result_samples = []
    for sample, p, e in zip(samples, pred, err):
        result_samples.append({
            'name': sample['name'],
            'camera_point_m': [float(x) for x in sample['camera']],
            'robot_point_m': [float(x) for x in sample['base']],
            'pred_robot_point_m': [float(x) for x in p],
            'error_mm': float(e * 1000.0),
        })

    out = {
        'type': 'camera_to_robot_base_rigid_transform',
        'source': str(args.samples),
        'point_count': len(samples),
        'rotation': [[float(x) for x in row] for row in r],
        'translation_m': [float(x) for x in t],
        'rmse_mm': rmse,
        'max_error_mm': max_err,
        'camera_point_condition': cond,
        'usage': 'p_base = R @ p_camera + t; normal_base = R @ normal_camera',
        'samples': result_samples,
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'ok': True,
        'out': str(out_path),
        'point_count': len(samples),
        'rmse_mm': rmse,
        'max_error_mm': max_err,
        'rank': cond['rank'],
        'warning': f'RMSE {rmse:.2f}mm 超过建议阈值 {args.min_rmse_mm:.2f}mm' if rmse > args.min_rmse_mm else '',
    }, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
