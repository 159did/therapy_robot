import cv2
import numpy as np
import json
import matplotlib.pyplot as plt


def smooth_1d(arr, ksize=21):
    arr = np.asarray(arr, dtype=np.float32)
    ksize = max(3, int(ksize))
    if ksize % 2 == 0:
        ksize += 1
    pad = ksize // 2
    arr_pad = np.pad(arr, (pad, pad), mode='edge')
    kernel = np.ones(ksize, dtype=np.float32) / ksize
    return np.convolve(arr_pad, kernel, mode='valid')


def interp_nan(arr):
    arr = np.asarray(arr, dtype=np.float32)
    idx = np.arange(len(arr))
    valid = np.isfinite(arr)
    if valid.sum() < 2:
        raise ValueError("有效点太少，无法插值")
    return np.interp(idx, idx[valid], arr[valid])


def limit_step(arr, max_step=2.5):
    """
    限制相邻采样点横向变化，避免中心线局部乱飞
    """
    out = arr.copy().astype(np.float32)
    for i in range(1, len(out)):
        d = out[i] - out[i - 1]
        if abs(d) > max_step:
            out[i] = out[i - 1] + np.sign(d) * max_step
    return out


def build_centerline(left, right):
    left_i = interp_nan(left)
    right_i = interp_nan(right)

    center_raw = 0.5 * (left_i + right_i)

    # 两层平滑：先强平滑，再限步长，再轻平滑
    center_s = smooth_1d(center_raw, 25)
    center_s = limit_step(center_s, max_step=2.0)
    center_s = smooth_1d(center_s, 15)

    return center_raw, center_s


def compute_arc_length(centerline, y_start, y_end):
    ys = np.arange(y_start, y_end + 1)
    xs = centerline[y_start:y_end + 1]

    ds = np.sqrt(np.diff(xs) ** 2 + np.diff(ys.astype(np.float32)) ** 2)
    s = np.zeros(len(xs), dtype=np.float32)
    s[1:] = np.cumsum(ds)
    return ys, xs, s


def sample_by_arc_length(ys, xs, s, num_segments=10):
    """
    按弧长等分，返回 num_segments+1 个分界点
    """
    total_len = s[-1]
    targets = np.linspace(0, total_len, num_segments + 1)

    sample_pts = []
    for st in targets:
        idx = np.argmin(np.abs(s - st))
        sample_pts.append((float(xs[idx]), float(ys[idx]), float(s[idx]), int(idx)))

    return sample_pts, total_len


def build_segments(sample_pts):
    """
    根据弧长采样点建立分段
    """
    segments = []
    for i in range(len(sample_pts) - 1):
        x1, y1, s1, idx1 = sample_pts[i]
        x2, y2, s2, idx2 = sample_pts[i + 1]

        start = np.array([x1, y1], dtype=np.float32)
        end = np.array([x2, y2], dtype=np.float32)
        center = 0.5 * (start + end)

        vec = end - start
        length = float(np.linalg.norm(vec))

        if length < 1e-6:
            tangent = np.array([0.0, 1.0], dtype=np.float32)
        else:
            tangent = vec / length

        # 法线
        normal = np.array([tangent[1], -tangent[0]], dtype=np.float32)

        segments.append({
            "index": i + 1,
            "start": start,
            "end": end,
            "center": center,
            "length": length,
            "tangent": tangent,
            "normal": normal,
        })
    return segments


def draw_spine_segments(binary_img, left, right, center_raw, center_s, y_start, y_end, segments):
    img_color = cv2.cvtColor(binary_img, cv2.COLOR_GRAY2BGR)

    # 画左右轮廓
    for y in range(y_start, y_end + 1):
        if np.isfinite(left[y]):
            cv2.circle(img_color, (int(round(left[y])), y), 1, (0, 0, 255), -1)
        if np.isfinite(right[y]):
            cv2.circle(img_color, (int(round(right[y])), y), 1, (255, 0, 0), -1)

    # 原始中心线（浅绿）
    pts_raw = []
    pts_s = []
    for y in range(y_start, y_end + 1):
        pts_raw.append((int(round(center_raw[y])), y))
        pts_s.append((int(round(center_s[y])), y))

    if len(pts_raw) > 1:
        cv2.polylines(img_color, [np.array(pts_raw)], False, (100, 255, 100), 1)
    if len(pts_s) > 1:
        cv2.polylines(img_color, [np.array(pts_s)], False, (0, 255, 0), 2)

    # 画节段
    for seg in segments:
        p1 = tuple(np.round(seg["start"]).astype(int))
        p2 = tuple(np.round(seg["end"]).astype(int))
        pc = tuple(np.round(seg["center"]).astype(int))
        n = seg["normal"]

        # 线段
        cv2.line(img_color, p1, p2, (0, 255, 255), 2)
        # 节段中心
        cv2.circle(img_color, pc, 3, (255, 255, 255), -1)

        # 画法线
        p_n1 = (int(round(pc[0] + 20 * n[0])), int(round(pc[1] + 20 * n[1])))
        p_n2 = (int(round(pc[0] - 20 * n[0])), int(round(pc[1] - 20 * n[1])))
        cv2.line(img_color, p_n1, p_n2, (255, 128, 0), 2)

        cv2.putText(img_color, f"S{seg['index']}", (pc[0] + 4, pc[1] - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

    return img_color


def main():
    # 这里假设你已经有一张边界图
    img = cv2.imread("back_edges.png", cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError("无法读取 back_edges.png")

    _, binary = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)

    h, w = binary.shape

    # --------
    # 这里用一个简单的中间两段法示例来生成 left/right
    # 你也可以替换成你现有程序算出来的 left/right
    # --------
    left = np.full(h, np.nan, dtype=np.float32)
    right = np.full(h, np.nan, dtype=np.float32)

    for y in range(h):
        xs = np.where(binary[y] > 0)[0]
        if len(xs) < 2:
            continue

        # 这里简化：直接取所有白点中间两个点
        mid1 = len(xs) // 2 - 1
        mid2 = len(xs) // 2
        if mid1 < 0 or mid2 >= len(xs):
            continue

        x1 = xs[mid1]
        x2 = xs[mid2]
        if x1 > x2:
            x1, x2 = x2, x1

        left[y] = x1
        right[y] = x2

    valid = np.isfinite(left) & np.isfinite(right)
    valid_idx = np.where(valid)[0]
    if len(valid_idx) < 30:
        raise ValueError("有效轮廓太少")

    y_start = int(valid_idx.min())
    y_end = int(valid_idx.max())

    center_raw, center_s = build_centerline(left, right)

    ys, xs, s = compute_arc_length(center_s, y_start, y_end)
    sample_pts, total_len = sample_by_arc_length(ys, xs, s, num_segments=10)
    segments = build_segments(sample_pts)

    vis = draw_spine_segments(binary, left, right, center_raw, center_s, y_start, y_end, segments)
    cv2.imwrite("back_spine_segments_result.png", vis)

    result_json = {
        "y_start": y_start,
        "y_end": y_end,
        "total_arc_length": float(total_len),
        "segments": [
            {
                "index": seg["index"],
                "start": [float(seg["start"][0]), float(seg["start"][1])],
                "end": [float(seg["end"][0]), float(seg["end"][1])],
                "center": [float(seg["center"][0]), float(seg["center"][1])],
                "length": float(seg["length"]),
                "tangent": [float(seg["tangent"][0]), float(seg["tangent"][1])],
                "normal": [float(seg["normal"][0]), float(seg["normal"][1])],
            }
            for seg in segments
        ]
    }

    with open("back_spine_segments_result.json", "w", encoding="utf-8") as f:
        json.dump(result_json, f, ensure_ascii=False, indent=2)

    print("处理完成")
    print("结果图: back_spine_segments_result.png")
    print("结果JSON: back_spine_segments_result.json")
    print("总弧长:", total_len)


if __name__ == "__main__":
    main()