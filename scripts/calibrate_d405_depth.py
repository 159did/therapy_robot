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
        measured = s.get('measured_z_m', s.get('camera_z_m'))
        actual = s.get('actual_z_m', s.get('actual_distance_m'))
        if measured is None or actual is None:
            raise ValueError(f'样本 {i} 缺少 measured_z_m 或 actual_z_m')
        clean.append({'name': s.get('name', f'p{i + 1}'), 'measured': float(measured), 'actual': float(actual)})
    if len(clean) < 2:
        raise ValueError('至少需要 2 个不同距离样本，建议 4~8 个')
    return clean


def fit_depth(samples):
    measured = np.asarray([s['measured'] for s in samples], dtype=float)
    actual = np.asarray([s['actual'] for s in samples], dtype=float)
    a = np.vstack([measured, np.ones_like(measured)]).T
    scale, offset = np.linalg.lstsq(a, actual, rcond=None)[0]
    pred = scale * measured + offset
    err = pred - actual
    return {
        'model': 'actual_z_m = measured_z_m * scale + offset_m',
        'scale': float(scale),
        'offset_m': float(offset),
        'rmse_mm': float(np.sqrt(np.mean(err ** 2)) * 1000.0),
        'max_abs_error_mm': float(np.max(np.abs(err)) * 1000.0),
        'samples': [
            {'name': s['name'], 'measured_z_m': s['measured'], 'actual_z_m': s['actual'], 'corrected_z_m': float(p), 'error_mm': float(e * 1000.0)}
            for s, p, e in zip(samples, pred, err)
        ],
    }


def main():
    parser = argparse.ArgumentParser(description='标定 D405 深度 Z 的线性尺度/零偏')
    parser.add_argument('--samples', default='/home/zzq/PTR/therapy_robot/calibration/d405_depth_samples.json')
    parser.add_argument('--out', default='/home/zzq/PTR/therapy_robot/calibration/d405_depth_calibration.json')
    args = parser.parse_args()
    fit = fit_depth(load_samples(args.samples))
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({'type': 'd405_depth_z_calibration', **fit}, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'ok': True, 'out': str(out_path), 'scale': fit['scale'], 'offset_m': fit['offset_m'], 'rmse_mm': fit['rmse_mm'], 'max_abs_error_mm': fit['max_abs_error_mm']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
