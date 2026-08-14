#这一版可以识别人体的最大轮廓，并将脊椎绘制为曲线，但是要求手臂的摆放也是对称的，不能识别躯干，算是效果比较好的一版。
import cv2
import numpy as np
import json


def interp_nan(arr: np.ndarray) -> np.ndarray:
    arr = arr.astype(np.float32)
    idx = np.arange(len(arr))
    valid = np.isfinite(arr)
    if valid.sum() < 2:
        raise ValueError("有效点太少，无法插值")
    return np.interp(idx, idx[valid], arr[valid])


def smooth_1d(arr: np.ndarray, ksize: int = 11) -> np.ndarray:
    ksize = max(3, int(ksize))
    if ksize % 2 == 0:
        ksize += 1
    pad = ksize // 2
    arr_pad = np.pad(arr.astype(np.float32), (pad, pad), mode="edge")
    kernel = np.ones(ksize, dtype=np.float32) / ksize
    return np.convolve(arr_pad, kernel, mode="valid")


def norm01(arr: np.ndarray) -> np.ndarray:
    mn = np.min(arr)
    mx = np.max(arr)
    if mx - mn < 1e-6:
        return np.zeros_like(arr, dtype=np.float32)
    return (arr - mn) / (mx - mn)


def edge_row_profile(edge_img: np.ndarray):
    h, w = edge_img.shape
    left = np.full(h, np.nan, dtype=np.float32)
    right = np.full(h, np.nan, dtype=np.float32)
    valid = np.zeros(h, dtype=bool)

    for y in range(h):
        xs = np.where(edge_img[y] > 0)[0]
        if len(xs) >= 2:
            left[y] = xs.min()
            right[y] = xs.max()
            valid[y] = True

    return left, right, valid


def find_local_min(arr: np.ndarray, start: int, end: int) -> int:
    start = max(0, start)
    end = min(len(arr), end)
    if end <= start + 2:
        return start
    return int(start + np.argmin(arr[start:end]))


def detect_back_geometry_from_edges(edge_img: np.ndarray):
    left_raw, right_raw, valid_rows = edge_row_profile(edge_img)

    valid_idx = np.where(valid_rows)[0]
    if len(valid_idx) < 40:
        raise ValueError("有效行太少，无法稳定识别")

    y_top = int(valid_idx.min())
    y_bottom = int(valid_idx.max())
    body_h = y_bottom - y_top + 1

    # 原始边界插值 + 平滑
    left = interp_nan(left_raw)
    right = interp_nan(right_raw)

    left_s = smooth_1d(left, 9)
    right_s = smooth_1d(right, 9)

    width = right_s - left_s
    center = 0.5 * (left_s + right_s)

    # -------- 1) 改进肩部识别：宽度 + 曲率 --------
    search_top = y_top + max(2, int(0.02 * body_h))
    search_bottom = y_top + int(0.38 * body_h)
    search_bottom = min(search_bottom, y_bottom - 5)

    d2_left = np.abs(np.gradient(np.gradient(left_s)))
    d2_right = np.abs(np.gradient(np.gradient(right_s)))
    curvature_score = d2_left + d2_right

    width_score = norm01(width[search_top:search_bottom])
    curv_score = norm01(curvature_score[search_top:search_bottom])

    # 宽度占主导，曲率做辅助
    shoulder_score = 0.7 * width_score + 0.3 * curv_score
    shoulder_y = int(search_top + np.argmax(shoulder_score))

    # -------- 2) 改进颈部识别：在肩部上方找最窄处 --------
    neck_top = y_top + max(2, int(0.01 * body_h))
    neck_bottom = max(neck_top + 3, shoulder_y - 3)
    neck_y = int(neck_top + np.argmin(width[neck_top:neck_bottom]))

    # -------- 3) 找腋下过渡线：肩下方宽度回落的局部最小 --------
    axilla_search_top = shoulder_y + 3
    axilla_search_bottom = min(y_bottom, shoulder_y + int(0.22 * body_h))
    axilla_y = find_local_min(width, axilla_search_top, axilla_search_bottom)

    # -------- 4) 去臂抑制：只在 axilla_y 以下处理 --------
    half_width = 0.5 * width
    half_base = smooth_1d(half_width, 31)

    # 允许少量自然起伏
    margin = max(6.0, 0.03 * np.max(width))

    torso_half = half_width.copy()
    torso_half[axilla_y:] = np.minimum(
        half_width[axilla_y:],
        half_base[axilla_y:] + margin
    )

    # 中心线也做平滑
    center_curve = smooth_1d(center, 21)

    left_torso = center_curve - torso_half
    right_torso = center_curve + torso_half

    # 再平滑一次，让边界更自然
    left_torso = smooth_1d(left_torso, 11)
    right_torso = smooth_1d(right_torso, 11)
    center_curve = 0.5 * (left_torso + right_torso)

    # -------- 5) 曲线坐标系：切线 / 法线 / 弧长 --------
    dx_dy = np.gradient(center_curve)

    tangent = np.stack([dx_dy, np.ones_like(dx_dy)], axis=1)
    tangent_norm = np.linalg.norm(tangent, axis=1, keepdims=True) + 1e-6
    tangent = tangent / tangent_norm

    normal = np.stack([np.ones_like(dx_dy), -dx_dy], axis=1)
    normal_norm = np.linalg.norm(normal, axis=1, keepdims=True) + 1e-6
    normal = normal / normal_norm

    ds = np.sqrt(1.0 + dx_dy * dx_dy)
    s = np.cumsum(ds)
    s = s - s[neck_y]

    result = {
        "neck_left": (int(round(left_s[neck_y])), int(neck_y)),
        "neck_right": (int(round(right_s[neck_y])), int(neck_y)),
        "neck_center": (int(round(center_curve[neck_y])), int(neck_y)),
        "shoulder_left": (int(round(left_s[shoulder_y])), int(shoulder_y)),
        "shoulder_right": (int(round(right_s[shoulder_y])), int(shoulder_y)),
        "shoulder_center": (int(round(center_curve[shoulder_y])), int(shoulder_y)),
        "axilla_left": (int(round(left_torso[axilla_y])), int(axilla_y)),
        "axilla_right": (int(round(right_torso[axilla_y])), int(axilla_y)),
        "axilla_center": (int(round(center_curve[axilla_y])), int(axilla_y)),
        "y_top": int(y_top),
        "y_bottom": int(y_bottom),
        "neck_y": int(neck_y),
        "shoulder_y": int(shoulder_y),
        "axilla_y": int(axilla_y),
        "center_curve": center_curve,
        "left_raw": left_s,
        "right_raw": right_s,
        "left_torso": left_torso,
        "right_torso": right_torso,
        "s": s,
        "normal": normal,
        "tangent": tangent,
    }
    return result


def draw_geometry(image: np.ndarray, edge_img: np.ndarray, result: dict) -> np.ndarray:
    if image is None:
        vis = cv2.cvtColor(edge_img, cv2.COLOR_GRAY2BGR)
    else:
        vis = image.copy()

    # 叠加边界
    edge_color = np.zeros_like(vis)
    edge_color[:, :, 1] = edge_img
    vis = cv2.addWeighted(vis, 1.0, edge_color, 0.5, 0)

    y_top = result["y_top"]
    y_bottom = result["y_bottom"]

    # 画原始边界（上部）
    pts_left_raw = []
    pts_right_raw = []
    for y in range(y_top, y_bottom + 1):
        pts_left_raw.append([int(round(result["left_raw"][y])), y])
        pts_right_raw.append([int(round(result["right_raw"][y])), y])

    cv2.polylines(vis, [np.array(pts_left_raw)], False, (255, 180, 0), 1)
    cv2.polylines(vis, [np.array(pts_right_raw)], False, (255, 180, 0), 1)

    # 画去臂后的躯干边界
    pts_left_torso = []
    pts_right_torso = []
    pts_center = []
    for y in range(y_top, y_bottom + 1):
        pts_left_torso.append([int(round(result["left_torso"][y])), y])
        pts_right_torso.append([int(round(result["right_torso"][y])), y])
        pts_center.append([int(round(result["center_curve"][y])), y])

    cv2.polylines(vis, [np.array(pts_left_torso)], False, (255, 0, 255), 2)
    cv2.polylines(vis, [np.array(pts_right_torso)], False, (255, 0, 255), 2)
    cv2.polylines(vis, [np.array(pts_center)], False, (0, 255, 0), 2)

    # 画关键横线
    cv2.line(vis, result["neck_left"], result["neck_right"], (0, 255, 255), 2)
    cv2.line(vis, result["shoulder_left"], result["shoulder_right"], (255, 0, 0), 2)
    cv2.line(vis, result["axilla_left"], result["axilla_right"], (0, 128, 255), 2)

    # 画关键点
    key_points = [
        "neck_left", "neck_right", "neck_center",
        "shoulder_left", "shoulder_right", "shoulder_center",
        "axilla_left", "axilla_right", "axilla_center"
    ]
    for name in key_points:
        pt = result[name]
        cv2.circle(vis, pt, 4, (0, 0, 255), -1)
        cv2.putText(vis, name, (pt[0] + 4, pt[1] - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 0), 1)

    # 在颈中点处画局部坐标轴
    ny = result["neck_y"]
    origin = np.array(result["neck_center"], dtype=np.float32)
    t = result["tangent"][ny]
    n = result["normal"][ny]

    p_t = tuple(np.round(origin + 70 * t).astype(int))
    p_n = tuple(np.round(origin + 70 * n).astype(int))

    cv2.arrowedLine(vis, tuple(origin.astype(int)), p_t, (0, 0, 255), 2, tipLength=0.15)
    cv2.arrowedLine(vis, tuple(origin.astype(int)), p_n, (0, 255, 255), 2, tipLength=0.15)
    cv2.putText(vis, "t", (p_t[0] + 4, p_t[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 255), 2)
    cv2.putText(vis, "n", (p_n[0] + 4, p_n[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)

    return vis


if __name__ == "__main__":
    edge_img = cv2.imread("back_edges.png", cv2.IMREAD_GRAYSCALE)
    color_img = cv2.imread("back.png")

    if edge_img is None:
        raise FileNotFoundError("无法读取 back_edges.png")

    _, edge_img = cv2.threshold(edge_img, 127, 255, cv2.THRESH_BINARY)

    result = detect_back_geometry_from_edges(edge_img)
    vis = draw_geometry(color_img, edge_img, result)

    cv2.imwrite("back_geometry_refined.png", vis)
    print("识别完成")
    print("结果图: back_geometry_refined.png")
    print("neck_center:", result["neck_center"])
    print("shoulder_center:", result["shoulder_center"])
    print("axilla_center:", result["axilla_center"])