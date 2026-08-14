import cv2
import numpy as np
import json


def smooth_1d(arr, ksize=9):
    ksize = max(3, int(ksize))
    if ksize % 2 == 0:
        ksize += 1
    pad = ksize // 2
    arr_pad = np.pad(arr.astype(np.float32), (pad, pad), mode='edge')
    kernel = np.ones(ksize, dtype=np.float32) / ksize
    return np.convolve(arr_pad, kernel, mode='valid')


def extract_segments_from_row(binary_row):
    """
    从一行二值图中提取所有白色连续段
    返回 [(x1, x2), ...]
    """
    xs = np.where(binary_row > 0)[0]
    if len(xs) == 0:
        return []

    segments = []
    start = xs[0]
    prev = xs[0]

    for x in xs[1:]:
        if x == prev + 1:
            prev = x
        else:
            segments.append((start, prev))
            start = x
            prev = x
    segments.append((start, prev))
    return segments


def choose_middle_segment(edge_img):
    """
    每一行只选最靠近图像中线的那一段
    """
    h, w = edge_img.shape
    img_center_x = w / 2.0

    left = np.full(h, np.nan, dtype=np.float32)
    right = np.full(h, np.nan, dtype=np.float32)
    center = np.full(h, np.nan, dtype=np.float32)
    width = np.full(h, np.nan, dtype=np.float32)
    valid = np.zeros(h, dtype=bool)

    for y in range(h):
        segments = extract_segments_from_row(edge_img[y])
        if len(segments) == 0:
            continue

        best_seg = None
        best_dist = 1e18

        for seg in segments:
            x1, x2 = seg
            c = 0.5 * (x1 + x2)
            dist = abs(c - img_center_x)

            if dist < best_dist:
                best_dist = dist
                best_seg = seg

        x1, x2 = best_seg
        left[y] = x1
        right[y] = x2
        center[y] = 0.5 * (x1 + x2)
        width[y] = x2 - x1 + 1
        valid[y] = True

    return left, right, center, width, valid


def fill_missing_by_interp(arr):
    idx = np.arange(len(arr))
    valid = np.isfinite(arr)
    if valid.sum() < 2:
        raise ValueError("有效行太少，无法插值")
    return np.interp(idx, idx[valid], arr[valid])


def detect_neck_and_shoulder(left, right, center, width, valid):
    valid_idx = np.where(valid)[0]
    if len(valid_idx) < 30:
        raise ValueError("有效行太少，无法识别颈部和肩部")

    y_top = int(valid_idx.min())
    y_bottom = int(valid_idx.max())
    body_h = y_bottom - y_top + 1

    left_i = fill_missing_by_interp(left)
    right_i = fill_missing_by_interp(right)
    center_i = fill_missing_by_interp(center)
    width_i = fill_missing_by_interp(width)

    left_s = smooth_1d(left_i, 9)
    right_s = smooth_1d(right_i, 9)
    center_s = smooth_1d(center_i, 15)
    width_s = smooth_1d(width_i, 11)

    # 搜索范围：只看上半身
    search_top = y_top + max(2, int(body_h * 0.02))
    search_mid = y_top + int(body_h * 0.20)
    search_bottom = y_top + int(body_h * 0.45)

    search_mid = max(search_mid, search_top + 5)
    search_bottom = min(search_bottom, y_bottom)

    if search_bottom <= search_top + 10:
        raise ValueError("搜索范围过小")

    # 颈部：上部偏窄
    neck_y = int(np.argmin(width_s[search_top:search_mid]) + search_top)

    # 肩部：颈部下方偏宽
    shoulder_top = min(neck_y + 3, search_bottom - 3)
    shoulder_bottom = search_bottom
    if shoulder_bottom <= shoulder_top + 3:
        shoulder_top = search_mid
        shoulder_bottom = search_bottom

    shoulder_y = int(np.argmax(width_s[shoulder_top:shoulder_bottom]) + shoulder_top)

    result = {
        "left": left_s,
        "right": right_s,
        "center": center_s,
        "width": width_s,
        "valid": valid,
        "y_top": y_top,
        "y_bottom": y_bottom,
        "neck_y": neck_y,
        "shoulder_y": shoulder_y,
        "neck_left": (int(round(left_s[neck_y])), int(neck_y)),
        "neck_right": (int(round(right_s[neck_y])), int(neck_y)),
        "neck_center": (int(round(center_s[neck_y])), int(neck_y)),
        "shoulder_left": (int(round(left_s[shoulder_y])), int(shoulder_y)),
        "shoulder_right": (int(round(right_s[shoulder_y])), int(shoulder_y)),
        "shoulder_center": (int(round(center_s[shoulder_y])), int(shoulder_y)),
    }
    return result


def draw_result(image, edge_img, result):
    if image is None:
        vis = cv2.cvtColor(edge_img, cv2.COLOR_GRAY2BGR)
    else:
        vis = image.copy()

    # 叠加原始边界图
    edge_color = np.zeros_like(vis)
    edge_color[:, :, 1] = edge_img
    vis = cv2.addWeighted(vis, 1.0, edge_color, 0.4, 0)

    # 画躯干左右边界和中心线
    pts_left = []
    pts_right = []
    pts_center = []

    for y in range(result["y_top"], result["y_bottom"] + 1):
        if np.isfinite(result["left"][y]) and np.isfinite(result["right"][y]):
            pts_left.append([int(round(result["left"][y])), y])
            pts_right.append([int(round(result["right"][y])), y])
            pts_center.append([int(round(result["center"][y])), y])

    if len(pts_left) > 1:
        cv2.polylines(vis, [np.array(pts_left)], False, (255, 0, 255), 2)
    if len(pts_right) > 1:
        cv2.polylines(vis, [np.array(pts_right)], False, (255, 0, 255), 2)
    if len(pts_center) > 1:
        cv2.polylines(vis, [np.array(pts_center)], False, (0, 255, 0), 2)

    # 画颈线和肩线
    cv2.line(vis, result["neck_left"], result["neck_right"], (0, 255, 255), 2)
    cv2.line(vis, result["shoulder_left"], result["shoulder_right"], (255, 0, 0), 2)

    # 画关键点
    for name in [
        "neck_left", "neck_right", "neck_center",
        "shoulder_left", "shoulder_right", "shoulder_center"
    ]:
        pt = result[name]
        cv2.circle(vis, pt, 4, (0, 0, 255), -1)
        cv2.putText(
            vis, name, (pt[0] + 5, pt[1] - 5),
            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 0), 1
        )

    return vis


def main():
    edge_path = "back_edges.png"
    image_path = "back.png"
    out_path = "back_middle_segment_result.png"
    json_path = "back_middle_segment_result.json"

    edge_img = cv2.imread(edge_path, cv2.IMREAD_GRAYSCALE)
    if edge_img is None:
        raise FileNotFoundError(f"无法读取 {edge_path}")

    _, edge_img = cv2.threshold(edge_img, 127, 255, cv2.THRESH_BINARY)

    image = cv2.imread(image_path)
    if image is None:
        image = None

    left, right, center, width, valid = choose_middle_segment(edge_img)
    result = detect_neck_and_shoulder(left, right, center, width, valid)
    vis = draw_result(image, edge_img, result)

    cv2.imwrite(out_path, vis)

    result_json = {
        "neck_left": list(result["neck_left"]),
        "neck_right": list(result["neck_right"]),
        "neck_center": list(result["neck_center"]),
        "shoulder_left": list(result["shoulder_left"]),
        "shoulder_right": list(result["shoulder_right"]),
        "shoulder_center": list(result["shoulder_center"]),
        "y_top": int(result["y_top"]),
        "y_bottom": int(result["y_bottom"]),
        "neck_y": int(result["neck_y"]),
        "shoulder_y": int(result["shoulder_y"]),
    }

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(result_json, f, ensure_ascii=False, indent=2)

    print("识别完成")
    print(f"结果图: {out_path}")
    print(f"结果JSON: {json_path}")
    print("neck_center:", result["neck_center"])
    print("shoulder_center:", result["shoulder_center"])


if __name__ == "__main__":
    main()