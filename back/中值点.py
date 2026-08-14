import cv2
import numpy as np
import matplotlib.pyplot as plt

def extract_torso_contour(image_path, visualize=True):
    """
    从人体背部边缘二值图像中提取躯干的左右轮廓。
    每行取中间的两个白色像素点作为躯干轮廓点。

    参数:
        image_path (str): 二值图像路径（背景黑，轮廓白）
        visualize (bool): 是否显示结果图像

    返回:
        left_pts (list of (x, y)): 左侧躯干轮廓点
        right_pts (list of (x, y)): 右侧躯干轮廓点
    """
    # 读取图像并转为灰度
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        raise FileNotFoundError(f"无法读取图像: {image_path}")

    # 二值化（确保像素值为0或255）
    _, binary = cv2.threshold(img, 127, 255, cv2.THRESH_BINARY)

    h, w = binary.shape
    left_pts = []
    right_pts = []

    for y in range(h):
        row = binary[y, :]
        # 获取该行所有白色像素的x坐标
        white_x = np.where(row > 0)[0]
        n = len(white_x)
        if n < 2:
            continue  # 不足两个点则跳过该行

        # 取排序后中间的两个点
        # 使用 (n//2 - 1) 和 (n//2) 确保无论奇偶都取到中间两个点
        mid1 = n // 2 - 1
        mid2 = n // 2
        if mid1 < 0 or mid2 >= n:
            continue

        x1 = white_x[mid1]
        x2 = white_x[mid2]
        # 保证左小右大
        if x1 > x2:
            x1, x2 = x2, x1

        left_pts.append((x1, y))
        right_pts.append((x2, y))

    if visualize:
        import matplotlib.pyplot as plt
        import matplotlib
        # 设置中文字体
        matplotlib.rcParams['font.sans-serif'] = ['SimHei']  # 或 ['Microsoft YaHei']
        matplotlib.rcParams['axes.unicode_minus'] = False

        img_color = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
        for pt in left_pts:
            cv2.circle(img_color, pt, 1, (0, 0, 255), -1)
        for pt in right_pts:
            cv2.circle(img_color, pt, 1, (255, 0, 0), -1)

        plt.figure(figsize=(10, 8))
        plt.imshow(cv2.cvtColor(img_color, cv2.COLOR_BGR2RGB))
        plt.title("提取的躯干左右轮廓 (红:左, 蓝:右)")
        plt.axis('off')
        plt.show()

    return left_pts, right_pts

# 使用示例
if __name__ == "__main__":
    # 请将 'back_edges.png' 替换为您的图像路径
    left, right = extract_torso_contour('back_edges.png', visualize=True)

    # 可选：保存点集到文件
    with open('torso_contour.txt', 'w') as f:
        f.write("左侧轮廓点 (x,y):\n")
        for pt in left:
            f.write(f"{pt[0]},{pt[1]}\n")
        f.write("\n右侧轮廓点 (x,y):\n")
        for pt in right:
            f.write(f"{pt[0]},{pt[1]}\n")