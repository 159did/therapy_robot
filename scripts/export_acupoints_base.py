#!/usr/bin/env python3
import argparse
import json
from pathlib import Path

import numpy as np


def load_extrinsics(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    r = np.asarray(data['rotation'], dtype=float).reshape(3, 3)
    t = np.asarray(data['translation_m'], dtype=float).reshape(3)
    rmse = data.get('rmse_mm')
    return r, t, rmse


def transform_points(result_path, extrinsics_path):
    result = json.loads(Path(result_path).read_text(encoding='utf-8'))
    r, t, rmse = load_extrinsics(extrinsics_path)
    pts = result.get('template_acupoints') or result.get('acupoints') or []
    out_pts = []
    for p in pts:
        if not p.get('ok') or 'point_camera_m' not in p or 'normal_camera' not in p:
            continue
        pc = np.asarray(p['point_camera_m'], dtype=float).reshape(3)
        nc = np.asarray(p['normal_camera'], dtype=float).reshape(3)
        pb = r @ pc + t
        nb = r @ nc
        n_norm = np.linalg.norm(nb)
        if n_norm > 1e-12:
            nb = nb / n_norm
        out_pts.append({
            'name': p.get('name'),
            'pixel': p.get('pixel'),
            'point_camera_m': [float(x) for x in pc],
            'normal_camera': [float(x) for x in nc],
            'point_base_m': [float(x) for x in pb],
            'point_base_mm': [float(x * 1000.0) for x in pb],
            'normal_base': [float(x) for x in nb],
            'valid_depth_samples': p.get('valid'),
            'residual_median_mm': p.get('residual_median_mm'),
        })
    return {
        'type': 'acupoints_in_robot_base',
        'source_result': str(result_path),
        'extrinsics': str(extrinsics_path),
        'extrinsics_rmse_mm': rmse,
        'count': len(out_pts),
        'usage': '机器人目标点可基于 point_base_m，并沿 normal_base 加 standoff/press 偏移。',
        'acupoints': out_pts,
    }


def main():
    parser = argparse.ArgumentParser(description='把 D405 识别出的穴位从相机坐标批量转换到机器人基坐标')
    parser.add_argument('--result', default='/home/zzq/PTR/therapy_robot/data/d405_samples/back_20260617_212933_470/analysis_result.json')
    parser.add_argument('--extrinsics', default='/home/zzq/PTR/therapy_robot/calibration/camera_to_base.json')
    parser.add_argument('--out', default='/home/zzq/PTR/therapy_robot/data/d405_samples/back_20260617_212933_470/acupoints_base.json')
    args = parser.parse_args()
    if not Path(args.extrinsics).exists():
        raise SystemExit(f'外参文件不存在: {args.extrinsics}，请先运行 calibrate_camera_to_base.py')
    out = transform_points(args.result, args.extrinsics)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ok': True, 'out': str(out_path), 'count': out['count'], 'extrinsics_rmse_mm': out['extrinsics_rmse_mm']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
