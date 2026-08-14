import cv2
import numpy as np
import matplotlib.pyplot as plt
import matplotlib
matplotlib.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'Arial Unicode MS']
matplotlib.rcParams['axes.unicode_minus'] = False

def extract_segments_from_row(row):
    white_x = np.where(row > 0)[0]
    if len(white_x) == 0:
        return []

    segments = []
    start = white_x[0]
    prev = white_x[0]

    for x in white_x[1:]:
        if x == prev + 1:
            prev = x
        else:
            segments.append((start, prev))
            start = x
            prev = x
    segments.append((start, prev))
    return segments


def smooth_1d(arr, ksize=9):
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
        raise ValueError("有效点太少")
    return np.interp(idx, idx[valid], arr[valid])


def choose_middle_two_segments(segments):
    if len(segments) < 2:
        return None, None
    n = len(segments)
    mid1 = n // 2 - 1
    mid2 = n // 2
    if mid1 < 0 or mid2 >= n:
        return None, None
    return segments[mid1], segments[mid2]


def choose_left_right_by_center(segments, center_ref):
    left_candidates = []
    right_candidates = []

    for seg in segments:
        x1, x2 = seg
        c = 0.5 * (x1 + x2)
        if c < center_ref:
            left_candidates.append((abs(c - center_ref), seg))
        elif c > center_ref:
            right_candidates.append((abs(c - center_ref), seg))

    if len(left_candidates) == 0 or len(right_candidates) == 0:
        return None, None

    left_candidates.sort(key=lambda x: x[0])
    right_candidates.sort(key=lambda x: x[0])

    return left_candidates[0][1], right_candidates[0][1]


def extract_torso_contour_refined(image_path, visualize=True):
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(f"无法读取图像: {image_path}")

    _, binary = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)
    h, w = binary.shape

    # -----------------------------
    # 第一遍：粗略中线（中间两个段）
    # -----------------------------
    center0 = np.full(h, np.nan, dtype=np.float32)

    for y in range(h):
        segments = extract_segments_from_row(binary[y, :])
        seg_left, seg_right = choose_middle_two_segments(segments)
        if seg_left is None or seg_right is None:
            continue

        x1 = 0.5 * (seg_left[0] + seg_left[1])
        x2 = 0.5 * (seg_right[0] + seg_right[1])
        if x1 > x2:
            x1, x2 = x2, x1

        center0[y] = 0.5 * (x1 + x2)

    center_ref = smooth_1d(interp_nan(center0), 21)

    # -----------------------------
    # 第二遍：按参考中线左右分别选段
    # -----------------------------
    left_x = np.full(h, np.nan, dtype=np.float32)
    right_x = np.full(h, np.nan, dtype=np.float32)

    for y in range(h):
        segments = extract_segments_from_row(binary[y, :])
        if len(segments) < 2:
            continue

        seg_left, seg_right = choose_left_right_by_center(segments, center_ref[y])
        if seg_left is None or seg_right is None:
            continue

        x1 = 0.5 * (seg_left[0] + seg_left[1])
        x2 = 0.5 * (seg_right[0] + seg_right[1])

        if x1 > x2:
            x1, x2 = x2, x1

        left_x[y] = x1
        right_x[y] = x2

    valid = np.isfinite(left_x) & np.isfinite(right_x)
    if valid.sum() < 20:
        raise ValueError("有效轮廓太少")

    left_s = smooth_1d(interp_nan(left_x), 9)
    right_s = smooth_1d(interp_nan(right_x), 9)
    center_s = smooth_1d((left_s + right_s) / 2.0, 15)
    width_s = smooth_1d(right_s - left_s, 11)

    valid_idx = np.where(valid)[0]
    y_top = int(valid_idx.min())
    y_bottom = int(valid_idx.max())
    body_h = y_bottom - y_top + 1

    search_top = y_top + max(2, int(body_h * 0.02))
    search_mid = y_top + int(body_h * 0.20)
    search_bottom = y_top + int(body_h * 0.45)
    search_mid = max(search_mid, search_top + 5)
    search_bottom = min(search_bottom, y_bottom)

    neck_y = int(np.argmin(width_s[search_top:search_mid]) + search_top)

    shoulder_top = min(neck_y + 3, search_bottom - 3)
    shoulder_bottom = search_bottom
    if shoulder_bottom <= shoulder_top + 3:
        shoulder_top = search_mid
        shoulder_bottom = search_bottom

    shoulder_y = int(np.argmax(width_s[shoulder_top:shoulder_bottom]) + shoulder_top)

    result = {
        "binary": binary,
        "left": left_s,
        "right": right_s,
        "center": center_s,
        "width": width_s,
        "neck_left": (int(round(left_s[neck_y])), int(neck_y)),
        "neck_right": (int(round(right_s[neck_y])), int(neck_y)),
        "neck_center": (int(round(center_s[neck_y])), int(neck_y)),
        "shoulder_left": (int(round(left_s[shoulder_y])), int(shoulder_y)),
        "shoulder_right": (int(round(right_s[shoulder_y])), int(shoulder_y)),
        "shoulder_center": (int(round(center_s[shoulder_y])), int(shoulder_y)),
    }

    if visualize:
        img_color = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)

        for y in range(h):
            if np.isfinite(left_s[y]):
                cv2.circle(img_color, (int(round(left_s[y])), y), 1, (0, 0, 255), -1)
            if np.isfinite(right_s[y]):
                cv2.circle(img_color, (int(round(right_s[y])), y), 1, (255, 0, 0), -1)
            if np.isfinite(center_s[y]):
                cv2.circle(img_color, (int(round(center_s[y])), y), 1, (0, 255, 0), -1)

        cv2.line(img_color, result["neck_left"], result["neck_right"], (0, 255, 255), 2)
        cv2.line(img_color, result["shoulder_left"], result["shoulder_right"], (255, 255, 0), 2)

        plt.figure(figsize=(10, 8))
        plt.imshow(cv2.cvtColor(img_color, cv2.COLOR_BGR2RGB))
        plt.title("改进后的躯干轮廓与中心线")
        plt.axis("off")
        plt.show()

    return result


if __name__ == "__main__":
    result = extract_torso_contour_refined("back_edges.png", visualize=True)
    print("neck_center:", result["neck_center"])
    print("shoulder_center:", result["shoulder_center"])