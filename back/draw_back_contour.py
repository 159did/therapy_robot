import cv2
import numpy as np


def draw_back_contour(image_path, output_path="back_contour_result.png"):
    # 1. 读取图片
    img = cv2.imread(image_path)
    if img is None:
        print("图片读取失败，请检查路径")
        return

    # 2. 备份原图
    result = img.copy()

    # 3. 灰度化
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 4. 高斯模糊去噪
    blur = cv2.GaussianBlur(gray, (5, 5), 0)

    # 5. Canny边缘检测
    edges = cv2.Canny(blur, 50, 150)

    # 6. 闭运算，让轮廓更连续
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (7, 7))
    edges_closed = cv2.morphologyEx(edges, cv2.MORPH_CLOSE, kernel)

    # 7. 查找轮廓
    contours, _ = cv2.findContours(
        edges_closed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )

    if len(contours) == 0:
        print("没有找到轮廓")
    else:
        # 8. 取最大轮廓
        largest_contour = max(contours, key=cv2.contourArea)

        # 保存边界图：方便观察轮廓效果
        cv2.imwrite("back_edges.png", edges_closed)

        # 保存填充后的mask：给后续肩颈识别/坐标系建立使用
        mask = np.zeros(gray.shape, dtype=np.uint8)
        cv2.drawContours(mask, [largest_contour], -1, 255, thickness=cv2.FILLED)
        cv2.imwrite("back_mask.png", mask)

        print("已保存 back_edges.png 和 back_mask.png")

    if len(contours) == 0:
        print("没有找到轮廓")
        return

    # 8. 取面积最大的轮廓
    largest_contour = max(contours, key=cv2.contourArea)

    # 9. 在原图上画轮廓
    cv2.drawContours(result, [largest_contour], -1, (0, 255, 0), 2)

    # 10. 保存结果
    cv2.imwrite(output_path, result)

    # 11. 显示中间结果
    cv2.imshow("Original", img)
    cv2.imshow("Edges", edges)
    cv2.imshow("Edges Closed", edges_closed)
    cv2.imshow("Contour Result", result)

    cv2.waitKey(0)
    cv2.destroyAllWindows()

    print(f"结果已保存到: {output_path}")


if __name__ == "__main__":
    image_path = "back.png"   # 改成你的图片路径
    draw_back_contour(image_path)