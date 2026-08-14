import cv2
import numpy as np

img = cv2.imread("back_mask.png", cv2.IMREAD_GRAYSCALE)

if img is None:
    print("读取失败")
else:
    print("shape:", img.shape)
    print("min:", img.min())
    print("max:", img.max())
    print("unique values:", np.unique(img)[:20])