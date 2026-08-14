import argparse
import json
from pathlib import Path

import cv2
import numpy as np

#python back_coordinate_from_mask.py --mask back_mask.png --image back.png
class DetectError(RuntimeError):
    pass


def read_mask(mask_path: str) -> np.ndarray:
    mask = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
    if mask is None:
        raise FileNotFoundError(f"无法读取 mask: {mask_path}")
    _, mask_bin = cv2.threshold(mask, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return mask_bin

def edge_to_region_mask(edge_img: np.ndarray) -> np.ndarray:
    _, edge = cv2.threshold(edge_img, 127, 255, cv2.THRESH_BINARY)

    cv2.imwrite("debug_1_edge_binary.png", edge)

    # 先加粗边界
    k_dilate = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    edge_d = cv2.dilate(edge, k_dilate, iterations=2)
    cv2.imwrite("debug_2_edge_dilate.png", edge_d)

    # 再闭运算
    k_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    edge_c = cv2.morphologyEx(edge_d, cv2.MORPH_CLOSE, k_close, iterations=2)
    cv2.imwrite("debug_3_edge_close.png", edge_c)

    contours, _ = cv2.findContours(edge_c, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        raise ValueError("边界图中没有找到可用轮廓")

    largest_contour = max(contours, key=cv2.contourArea)

    mask = np.zeros_like(edge_c)
    cv2.drawContours(mask, [largest_contour], -1, 255, thickness=cv2.FILLED)
    cv2.imwrite("debug_4_region_mask.png", mask)

    return mask

def read_mask(mask_path):
    img = cv2.imread(mask_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(f"无法读取: {mask_path}")

    _, img = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)

    white_ratio = np.count_nonzero(img) / img.size

    # 如果白色区域很少，说明更像边界图而不是区域mask
    if white_ratio < 0.05:
        print("检测到输入更像边界图，自动转换为区域mask...")
        img = edge_to_region_mask(img)

    return img

def keep_largest_component(mask: np.ndarray) -> np.ndarray:
    num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    if num_labels <= 1:
        return mask
    largest_label = 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])
    out = np.zeros_like(mask)
    out[labels == largest_label] = 255
    return out


def fill_holes(mask: np.ndarray) -> np.ndarray:
    h, w = mask.shape
    flood = mask.copy()
    flood_mask = np.zeros((h + 2, w + 2), dtype=np.uint8)
    cv2.floodFill(flood, flood_mask, (0, 0), 255)
    flood_inv = cv2.bitwise_not(flood)
    return cv2.bitwise_or(mask, flood_inv)


def preprocess_mask(mask: np.ndarray) -> np.ndarray:
    k1 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    k2 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (11, 11))
    out = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k1, iterations=1)
    out = cv2.morphologyEx(out, cv2.MORPH_CLOSE, k2, iterations=2)
    out = keep_largest_component(out)
    out = fill_holes(out)
    out = keep_largest_component(out)
    return out


def edge_row_profile(edge_img: np.ndarray):
    """
    从边界图中逐行提取左右边界。
    输入:
        edge_img: 白色边界，黑色背景
    输出:
        left_x, right_x, width, valid_rows
    """
    h, w = edge_img.shape
    left_x = np.full(h, -1, dtype=np.int32)
    right_x = np.full(h, -1, dtype=np.int32)
    width = np.zeros(h, dtype=np.int32)
    valid_rows = np.zeros(h, dtype=bool)

    for y in range(h):
        xs = np.where(edge_img[y] > 0)[0]
        if len(xs) >= 2:
            left_x[y] = xs.min()
            right_x[y] = xs.max()
            width[y] = right_x[y] - left_x[y]
            valid_rows[y] = True

    return left_x, right_x, width, valid_rows


def smooth_1d(x: np.ndarray, k: int) -> np.ndarray:
    if k <= 1:
        return x.copy()
    if k % 2 == 0:
        k += 1
    pad = k // 2
    xpad = np.pad(x, (pad, pad), mode="edge")
    kernel = np.ones(k, dtype=np.float32) / k
    return np.convolve(xpad, kernel, mode="valid")


def find_neck_and_shoulder(mask: np.ndarray):
    left_x, right_x, width, valid_rows = edge_row_profile(mask)
    top_y = int(valid_rows[0])
    bottom_y = int(valid_rows[-1])
    H = bottom_y - top_y + 1
    if H < 40:
        raise DetectError("前景高度太小，无法稳定识别肩颈")

    body_width = width[top_y:bottom_y + 1].copy()
    k = max(9, int(H * 0.03) | 1)
    width_smooth = smooth_1d(body_width, k)

    def clamp_range(a: int, b: int):
        a = max(top_y, min(a, bottom_y))
        b = max(top_y, min(b, bottom_y))
        if a > b:
            a, b = b, a
        return a, b

    shoulder_a, shoulder_b = clamp_range(top_y + int(0.10 * H), top_y + int(0.45 * H))
    shoulder_seg = width_smooth[shoulder_a - top_y: shoulder_b - top_y + 1]
    shoulder_y = int(shoulder_a + np.argmax(shoulder_seg))

    neck_a, neck_b = clamp_range(top_y + int(0.03 * H), shoulder_y - int(0.04 * H))
    if neck_b - neck_a < 5:
        neck_a, neck_b = clamp_range(top_y + int(0.02 * H), top_y + int(0.22 * H))
    neck_seg = width_smooth[neck_a - top_y: neck_b - top_y + 1]
    neck_y = int(neck_a + np.argmin(neck_seg))

    neck_left = np.array([left_x[neck_y], neck_y], dtype=np.float32)
    neck_right = np.array([right_x[neck_y], neck_y], dtype=np.float32)
    shoulder_left = np.array([left_x[shoulder_y], shoulder_y], dtype=np.float32)
    shoulder_right = np.array([right_x[shoulder_y], shoulder_y], dtype=np.float32)

    if np.any(neck_left < 0) or np.any(neck_right < 0) or np.any(shoulder_left < 0) or np.any(shoulder_right < 0):
        raise DetectError("无法在目标行上取到左右边界")

    neck_center = (neck_left + neck_right) / 2.0
    shoulder_center = (shoulder_left + shoulder_right) / 2.0
    shoulder_width = float(np.linalg.norm(shoulder_right - shoulder_left))
    if shoulder_width < 20:
        raise DetectError("肩宽太小，识别结果不可靠")

    ex = shoulder_right - shoulder_left
    ex = ex / (np.linalg.norm(ex) + 1e-8)
    ey = np.array([-ex[1], ex[0]], dtype=np.float32)
    if np.dot(ey, np.array([0.0, 1.0], dtype=np.float32)) < 0:
        ey = -ey

    return {
        "top_y": top_y,
        "bottom_y": bottom_y,
        "neck_y": int(neck_y),
        "shoulder_y": int(shoulder_y),
        "points": {
            "neck_left": neck_left,
            "neck_right": neck_right,
            "neck_center": neck_center,
            "shoulder_left": shoulder_left,
            "shoulder_right": shoulder_right,
            "shoulder_center": shoulder_center,
        },
        "axis": {
            "origin": neck_center.copy(),
            "ex": ex,
            "ey": ey,
            "scale_shoulder_width_px": shoulder_width,
        },
    }


def point_to_back_coord(p_xy, origin, ex, ey, scale):
    p = np.array(p_xy, dtype=np.float32)
    v = p - origin
    u = float(np.dot(v, ex) / scale)
    v2 = float(np.dot(v, ey) / scale)
    return u, v2


def draw_result(base_img: np.ndarray, mask: np.ndarray, result: dict) -> np.ndarray:
    if base_img.ndim == 2:
        vis = cv2.cvtColor(base_img, cv2.COLOR_GRAY2BGR)
    else:
        vis = base_img.copy()

    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if contours:
        cv2.drawContours(vis, contours, -1, (0, 255, 0), 2)

    pts = result["points"]
    colors = {
        "neck_left": (255, 255, 0),
        "neck_right": (255, 255, 0),
        "neck_center": (0, 0, 255),
        "shoulder_left": (255, 0, 0),
        "shoulder_right": (255, 0, 0),
        "shoulder_center": (0, 165, 255),
    }
    for name, p in pts.items():
        x, y = int(round(float(p[0]))), int(round(float(p[1])))
        cv2.circle(vis, (x, y), 6, colors[name], -1)
        cv2.putText(vis, name, (x + 8, y - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.5, colors[name], 1, cv2.LINE_AA)

    cv2.line(vis,
             tuple(np.round(pts["neck_left"]).astype(int)),
             tuple(np.round(pts["neck_right"]).astype(int)),
             (255, 255, 0), 2)
    cv2.line(vis,
             tuple(np.round(pts["shoulder_left"]).astype(int)),
             tuple(np.round(pts["shoulder_right"]).astype(int)),
             (255, 0, 0), 2)

    origin = result["axis"]["origin"]
    ex = result["axis"]["ex"]
    ey = result["axis"]["ey"]
    scale = result["axis"]["scale_shoulder_width_px"]
    ox, oy = int(round(float(origin[0]))), int(round(float(origin[1])))

    x_end = origin + ex * scale * 0.35
    y_end = origin + ey * scale * 0.35
    cv2.arrowedLine(vis, (ox, oy), tuple(np.round(x_end).astype(int)), (0, 0, 255), 3, tipLength=0.15)
    cv2.arrowedLine(vis, (ox, oy), tuple(np.round(y_end).astype(int)), (0, 255, 255), 3, tipLength=0.15)
    cv2.putText(vis, "X", tuple(np.round(x_end + np.array([6, -6])).astype(int)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
    cv2.putText(vis, "Y", tuple(np.round(y_end + np.array([6, -6])).astype(int)), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2)

    return vis


def save_json(path: str, result: dict):
    serializable = {
        "top_y": int(result["top_y"]),
        "bottom_y": int(result["bottom_y"]),
        "neck_y": int(result["neck_y"]),
        "shoulder_y": int(result["shoulder_y"]),
        "points": {k: [float(v[0]), float(v[1])] for k, v in result["points"].items()},
        "axis": {
            "origin": [float(result["axis"]["origin"][0]), float(result["axis"]["origin"][1])],
            "ex": [float(result["axis"]["ex"][0]), float(result["axis"]["ex"][1])],
            "ey": [float(result["axis"]["ey"][0]), float(result["axis"]["ey"][1])],
            "scale_shoulder_width_px": float(result["axis"]["scale_shoulder_width_px"]),
        }
    }
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(serializable, f, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description='从背部 mask 识别肩颈，并建立背部局部坐标系')
    parser.add_argument('--mask', required=True, help='输入二值 mask 图片路径，人体为白色，背景为黑色')
    parser.add_argument('--image', default=None, help='原图路径，可选；若提供则在原图上叠加结果')
    parser.add_argument('--out', default='back_coordinate_result.png', help='输出可视化结果图')
    parser.add_argument('--json', default='back_coordinate_result.json', help='输出关键点和坐标系参数')
    args = parser.parse_args()

    mask = preprocess_mask(read_mask(args.mask))
    if args.image:
        base_img = cv2.imread(args.image)
        if base_img is None:
            raise FileNotFoundError(f'无法读取原图: {args.image}')
    else:
        base_img = cv2.cvtColor(mask, cv2.COLOR_GRAY2BGR)

    result = find_neck_and_shoulder(mask)
    vis = draw_result(base_img, mask, result)
    cv2.imwrite(args.out, vis)
    save_json(args.json, result)

    print('识别完成')
    print(f'可视化结果: {args.out}')
    print(f'关键点JSON: {args.json}')
    for k, v in result['points'].items():
        print(f'{k}: ({v[0]:.1f}, {v[1]:.1f})')


if __name__ == '__main__':
    main()
