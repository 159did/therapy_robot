#!/usr/bin/env python3
import argparse
import json
import math
from pathlib import Path

import numpy as np

AXIS_META = {
    'K0': {'unit': 'mm', 'kind': 'linear', 'recommended_min_samples': 2},
    'K1': {'unit': 'deg', 'kind': 'rotary', 'recommended_min_samples': 3},
    'K2': {'unit': 'deg', 'kind': 'rotary', 'recommended_min_samples': 3},
    'K3': {'unit': 'deg', 'kind': 'rotary', 'recommended_min_samples': 3},
    'K4': {'unit': 'deg', 'kind': 'rotary', 'recommended_min_samples': 3},
}


def load_samples(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    axes = data.get('axes', data)
    if not isinstance(axes, dict):
        raise ValueError('标定文件需要包含 axes 对象')
    return axes


def fit_axis(samples):
    xs = []
    ys = []
    for i, s in enumerate(samples):
        if 'native' not in s or 'physical' not in s:
            raise ValueError(f'样本 {i} 缺少 native 或 physical')
        x = float(s['native'])
        y = float(s['physical'])
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError(f'样本 {i} 包含非数字')
        xs.append(x)
        ys.append(y)
    if len(xs) < 2:
        raise ValueError('每个轴至少需要 2 个样本')
    x = np.asarray(xs, dtype=float)
    y = np.asarray(ys, dtype=float)
    a = np.vstack([x, np.ones_like(x)]).T
    scale, offset = np.linalg.lstsq(a, y, rcond=None)[0]
    pred = scale * x + offset
    err = pred - y
    rmse = float(np.sqrt(np.mean(err ** 2)))
    max_abs = float(np.max(np.abs(err)))
    span_native = float(np.max(x) - np.min(x))
    span_physical = float(np.max(y) - np.min(y))
    return {
        'scale_physical_per_native': float(scale),
        'offset_physical': float(offset),
        'sign': 1 if scale >= 0 else -1,
        'rmse_physical': rmse,
        'max_abs_error_physical': max_abs,
        'span_native': span_native,
        'span_physical': span_physical,
        'samples': [
            {
                'native': float(nx),
                'physical': float(py),
                'pred_physical': float(pp),
                'error_physical': float(ee),
            }
            for nx, py, pp, ee in zip(x, y, pred, err)
        ],
    }


def validate_axis(axis_name, fit, sample_count):
    warnings = []
    meta = AXIS_META.get(axis_name, {'unit': 'unit', 'recommended_min_samples': 3})
    if sample_count < meta['recommended_min_samples']:
        warnings.append(f'样本数 {sample_count} 偏少，建议至少 {meta["recommended_min_samples"]} 个')
    if abs(fit['span_native']) < 1e-9:
        warnings.append('native 范围为 0，无法可靠标定')
    if abs(fit['span_physical']) < 1e-9:
        warnings.append('physical 范围为 0，无法可靠标定')
    unit = meta.get('unit', 'unit')
    if meta.get('kind') == 'rotary' and fit['max_abs_error_physical'] > 1.0:
        warnings.append(f'最大角度残差 {fit["max_abs_error_physical"]:.3f}{unit} 偏大，检查读数或是否存在回差')
    if meta.get('kind') == 'linear' and fit['max_abs_error_physical'] > 2.0:
        warnings.append(f'最大线性残差 {fit["max_abs_error_physical"]:.3f}{unit} 偏大，检查尺量或是否存在机械间隙')
    return warnings


def main():
    parser = argparse.ArgumentParser(description='拟合机器人 K0-K4 轴 native 到 mm/deg 的线性标定参数')
    parser.add_argument('--samples', default='/home/zzq/PTR/therapy_robot/calibration/robot_axis_samples.json')
    parser.add_argument('--out', default='/home/zzq/PTR/therapy_robot/calibration/robot_axis_calibration.json')
    args = parser.parse_args()

    axes = load_samples(args.samples)
    result = {
        'type': 'robot_axis_linear_calibration',
        'source': str(args.samples),
        'model': 'physical = native * scale_physical_per_native + offset_physical',
        'axes': {},
    }
    for axis_name, axis_data in axes.items():
        samples = axis_data.get('samples', axis_data if isinstance(axis_data, list) else [])
        if not samples:
            continue
        fit = fit_axis(samples)
        meta = AXIS_META.get(axis_name, {})
        fit['unit'] = axis_data.get('unit', meta.get('unit', 'unit')) if isinstance(axis_data, dict) else meta.get('unit', 'unit')
        fit['kind'] = axis_data.get('kind', meta.get('kind', 'unknown')) if isinstance(axis_data, dict) else meta.get('kind', 'unknown')
        fit['zero_native_for_physical_zero'] = float(-fit['offset_physical'] / fit['scale_physical_per_native']) if abs(fit['scale_physical_per_native']) > 1e-12 else None
        fit['warnings'] = validate_axis(axis_name, fit, len(samples))
        result['axes'][axis_name] = fit

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    summary = {
        'ok': True,
        'out': str(out_path),
        'axes': {
            name: {
                'scale': axis['scale_physical_per_native'],
                'offset': axis['offset_physical'],
                'rmse': axis['rmse_physical'],
                'max_abs_error': axis['max_abs_error_physical'],
                'warnings': axis['warnings'],
            }
            for name, axis in result['axes'].items()
        },
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
