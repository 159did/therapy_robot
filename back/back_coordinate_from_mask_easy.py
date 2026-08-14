import cv2
import numpy as np
import json


def edge_row_profile(edge_img: np.ndarray):
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


def smooth_1d(arr, ksize=11):
    pad = ksize // 2
    arr_pad = np.pad(arr.astype(np.float32), (pad, pad), mode='edge')
    kernel = np.ones(ksize, dtype=np.float32) / ksize
    return np.convolve(arr_pad, kernel, mode='valid')


def find_neck_and_shoulder_from_edges(edge_img: np.ndarray):
    left_x, right_x, width, valid_rows = edge_row_profile(edge_img)

    valid_idx = np.where(valid_rows)[0]
    if len(valid_idx) < 20:
        raise ValueError("有效行太少，无法识别肩颈")

    y_top = int(valid_idx.min())
    y_bottom = int(valid_idx.max())
    body_h = y_bottom - y_top + 1

    if body_h < 30:
        raise ValueError("前景高度太小，无法稳定识别肩颈")

    # 只在上半部分搜索肩颈
    search_top = y_top
    search_bottom = y_top + int(body_h * 0.45)
    if search_bottom <= search_top + 10:
        raise ValueError("搜索区域太小")

    width_s = smooth_1d(width, ksize=11)

    # 肩部：上半部分中最宽处
    shoulder_y = int(np.argmax(width_s[search_top:search_bottom]) + search_top)

    # 颈部：肩部上方最窄处
    if shoulder_y - search_top < 5:
        raise ValueError("肩部位置过高，无法识别颈部")

    neck_y = int(np.argmin(width_s[search_top:shoulder_y]) + search_top)

    shoulder_left = (int(left_x[shoulder_y]), int(shoulder_y))
    shoulder_right = (int(right_x[shoulder_y]), int(shoulder_y))
    shoulder_center = (
        int((left_x[shoulder_y] + right_x[shoulder_y]) / 2),
        int(shoulder_y)
    )

    neck_left = (int(left_x[neck_y]), int(neck_y))
    neck_right = (int(right_x[neck_y]), int(neck_y))
    neck_center = (
        int((left_x[neck_y] + right_x[neck_y]) / 2),
        int(neck_y)
    )

    return {
        "neck_left": neck_left,
        "neck_right": neck_right,
        "neck_center": neck_center,
        "shoulder_left": shoulder_left,
        "shoulder_right": shoulder_right,
        "shoulder_center": shoulder_center,
    }


def draw_result(image, edge_img, result):
    if len(image.shape) == 2:
        vis = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
    else:
        vis = image.copy()

    # 叠加边界
    edge_color = np.zeros_like(vis)
    edge_color[:, :, 1] = edge_img
    vis = cv2.addWeighted(vis, 1.0, edge_color, 0.5, 0)

    # 画关键点
    colors = {
        "neck_left": (0, 255, 255),
        "neck_right": (0, 255, 255),
        "neck_center": (0, 0, 255),
        "shoulder_left": (255, 0, 0),
        "shoulder_right": (255, 0, 0),
        "shoulder_center": (0, 165, 255),
    }

    for name, pt in result.items():
        cv2.circle(vis, pt, 5, colors.get(name, (0, 255, 0)), -1)
        cv2.putText(vis, name, (pt[0] + 5, pt[1] - 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, colors.get(name, (0, 255, 0)), 1)

    # 画肩线和颈线
    cv2.line(vis, result["shoulder_left"], result["shoulder_right"], (255, 0, 0), 2)
    cv2.line(vis, result["neck_left"], result["neck_right"], (0, 255, 255), 2)

    # 画坐标原点和坐标轴
    origin = np.array(result["neck_center"], dtype=np.float32)
    sl = np.array(result["shoulder_left"], dtype=np.float32)
    sr = np.array(result["shoulder_right"], dtype=np.float32)

    ex = sr - sl
    norm = np.linalg.norm(ex)
    if norm > 1e-6:
        ex = ex / norm
        ey = np.array([-ex[1], ex[0]], dtype=np.float32)

        # 保证 y 轴朝图像下方
        if ey[1] < 0:
            ey = -ey

        scale = 80
        px = tuple(np.round(origin + ex * scale).astype(int))
        py = tuple(np.round(origin + ey * scale).astype(int))

        cv2.arrowedLine(vis, tuple(origin.astype(int)), px, (0, 0, 255), 2, tipLength=0.15)
        cv2.arrowedLine(vis, tuple(origin.astype(int)), py, (0, 255, 255), 2, tipLength=0.15)
        cv2.putText(vis, "X", (px[0] + 5, px[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 255), 2)
        cv2.putText(vis, "Y", (py[0] + 5, py[1]), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

    return vis


def save_json(path, result):
    result_json = {k: [int(v[0]), int(v[1])] for k, v in result.items()}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result_json, f, ensure_ascii=False, indent=2)


def main():
    edge_path = "back_edges.png"
    image_path = "back.png"
    out_path = "back_edge_coordinate_result.png"
    json_path = "back_edge_coordinate_result.json"

    edge_img = cv2.imread(edge_path, cv2.IMREAD_GRAYSCALE)
    if edge_img is None:
        raise FileNotFoundError(f"无法读取边界图: {edge_path}")

    _, edge_img = cv2.threshold(edge_img, 127, 255, cv2.THRESH_BINARY)

    color_img = cv2.imread(image_path)
    if color_img is None:
        color_img = cv2.cvtColor(edge_img, cv2.COLOR_GRAY2BGR)

    result = find_neck_and_shoulder_from_edges(edge_img)
    vis = draw_result(color_img, edge_img, result)

    cv2.imwrite(out_path, vis)
    save_json(json_path, result)

    print("识别完成")
    print(f"可视化结果: {out_path}")
    print(f"关键点JSON: {json_path}")
    for k, v in result.items():
        print(f"{k}: {v}")


if __name__ == "__main__":
    main()