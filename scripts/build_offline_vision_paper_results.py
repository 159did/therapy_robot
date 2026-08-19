#!/usr/bin/env python3
"""Build presentation figures and tables from locked offline vision reports."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


LOCKS = {
    "formal_use_allowed": False,
    "promotion_locked": True,
    "execution_allowed": False,
}
OUTPUT_NAMES = (
    "01_input_overview.png",
    "01_input_rgb.png",
    "02_target_region.png",
    "03_acupoints_annotated.png",
    "04_normal_vs_blocked.png",
    "acupoint_results.csv",
    "acupoint_results.md",
    "low_confidence_result.json",
    "normal_result.json",
    "paper_results_summary.json",
)
FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Medium.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in FONT_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            return ImageFont.truetype(str(path), size=size)
    return ImageFont.load_default()


def require_locked_report(report: dict[str, Any], label: str) -> None:
    for key, expected in LOCKS.items():
        if report.get(key) is not expected:
            raise ValueError(f"{label}_{key}_lock_invalid")
    hardware = report.get("hardware_access")
    if not isinstance(hardware, dict) or any(value is not False for value in hardware.values()):
        raise ValueError(f"{label}_hardware_access_not_false")
    for item in report.get("acupoints", []):
        target = item.get("simulation_endpoint_target")
        if target is not None and target.get("executable") is not False:
            raise ValueError(f"{label}_executable_target_present")


def load_report(path: Path, label: str) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise ValueError(f"{label}_report_invalid")
    require_locked_report(report, label)
    return report


def text_box(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, fill: tuple[int, int, int, int], text_fill: tuple[int, int, int], size: int = 22) -> None:
    x, y = xy
    fnt = font(size)
    box = draw.textbbox((x, y), text, font=fnt)
    draw.rounded_rectangle((box[0] - 10, box[1] - 6, box[2] + 10, box[3] + 6), radius=8, fill=fill)
    draw.text((x, y), text, font=fnt, fill=text_fill)


def base_canvas(title: str, width: int = 1600, height: int = 980) -> tuple[Image.Image, ImageDraw.ImageDraw]:
    image = Image.new("RGB", (width, height), (20, 28, 40))
    draw = ImageDraw.Draw(image, "RGBA")
    draw.rectangle((0, 0, width, 88), fill=(26, 54, 76, 255))
    draw.text((44, 24), title, font=font(34), fill=(245, 249, 252, 255))
    draw.text((width - 520, 31), "B5-VISION | 离线结果展示", font=font(22), fill=(189, 220, 232, 255))
    return image, draw


def paste_scaled(canvas: Image.Image, source: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, int, float]:
    left, top, right, bottom = box
    max_width, max_height = right - left, bottom - top
    scale = min(max_width / source.width, max_height / source.height)
    resized = source.resize((round(source.width * scale), round(source.height * scale)), Image.Resampling.LANCZOS)
    x = left + (max_width - resized.width) // 2
    y = top + (max_height - resized.height) // 2
    canvas.paste(resized, (x, y))
    return x, y, scale


def draw_status(draw: ImageDraw.ImageDraw, report: dict[str, Any], xy: tuple[int, int], label: str, width: int = 330) -> None:
    valid = report.get("pipeline_valid") is True
    status = "离线仿真目标已生成（不可执行）" if valid else "BLOCKING：不生成仿真目标"
    color = (35, 150, 105, 235) if valid else (190, 63, 67, 235)
    x, y = xy
    height = 90
    draw.rounded_rectangle((x, y, x + width, y + height), radius=8, fill=color)
    draw.text((x + 14, y + 9), label, font=font(19), fill=(224, 248, 239, 255))
    draw.text((x + 14, y + 43), status, font=font(19), fill=(255, 255, 255, 255))


def draw_points(draw: ImageDraw.ImageDraw, report: dict[str, Any], origin: tuple[int, int], scale: float, offset_y: int = 0, blocked: bool = False, label_size: int = 19) -> None:
    for item in report.get("acupoints", []):
        x, y = item["pixel"]
        px = round(origin[0] + x * scale)
        py = round(origin[1] + y * scale + offset_y)
        valid = item.get("valid") is True and item.get("simulation_endpoint_target") is not None
        color = (40, 218, 140, 255) if valid and not blocked else (242, 92, 88, 255)
        radius = max(7, round(5 * scale))
        draw.ellipse((px - radius, py - radius, px + radius, py + radius), fill=color, outline=(255, 255, 255, 255), width=3)
        confidence = float(item.get("coordinate_confidence", 0.0))
        label = f"{item['name']}  ({x},{y})  c={confidence:.2f}"
        label_font = font(label_size)
        label_bounds = draw.textbbox((0, 0), label, font=label_font)
        label_width = label_bounds[2] - label_bounds[0]
        tx = px - label_width - 24 if item["name"].endswith("-L") else px + 14
        ty = max(96, py - 22)
        text_box(draw, (tx, ty), label, (12, 20, 29, 225), (248, 251, 252), label_size)


def render_input(image: Image.Image, normal: dict[str, Any], out_path: Path) -> None:
    canvas, draw = base_canvas("01  原始输入图 | RGB 背部样本")
    x, y, scale = paste_scaled(canvas, image, (48, 120, 1180, 900))
    draw.rectangle((x, y, x + round(image.width * scale), y + round(image.height * scale)), outline=(115, 215, 230, 255), width=3)
    draw.text((1230, 150), "输入", font=font(26), fill=(158, 211, 224, 255))
    draw.text((1230, 205), f"{image.width} × {image.height} px", font=font(25), fill=(245, 249, 252, 255))
    draw.text((1230, 270), "离线 RGB-D 样本", font=font(25), fill=(245, 249, 252, 255))
    draw.text((1230, 335), f"image SHA-256\n{normal['input']['image_sha256'][:16]}…", font=font(20), fill=(184, 199, 209, 255), spacing=10)
    draw_status(draw, normal, (1215, 760), "正常输入")
    canvas.save(out_path, quality=95)


def render_region(image: Image.Image, normal: dict[str, Any], out_path: Path) -> None:
    canvas, draw = base_canvas("02  目标区域 | 深度支持与背部框")
    x, y, scale = paste_scaled(canvas, image, (48, 120, 1180, 900))
    bbox = normal["target_region"]["bbox_px"]
    bx0, by0, bx1, by1 = [round(value * scale) for value in bbox]
    bx0, by0, bx1, by1 = x + bx0, y + by0, x + bx1, y + by1
    overlay = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay, "RGBA")
    overlay_draw.rectangle((x, y, x + round(image.width * scale), y + round(image.height * scale)), fill=(6, 12, 18, 80))
    overlay_draw.rectangle((bx0, by0, bx1, by1), fill=(24, 150, 110, 55), outline=(65, 230, 165, 255), width=7)
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(canvas, "RGBA")
    draw.text((1230, 150), "目标区域", font=font(26), fill=(158, 211, 224, 255))
    draw.text((1230, 205), f"bbox = {bbox}", font=font(22), fill=(245, 249, 252, 255))
    draw.text((1230, 265), f"区域置信度 = {normal['target_region']['confidence']:.3f}", font=font(22), fill=(245, 249, 252, 255))
    draw.text((1230, 325), f"深度覆盖率 = {normal['target_region']['depth_coverage']:.3f}", font=font(22), fill=(245, 249, 252, 255))
    draw.text((1230, 385), f"中心深度 = {normal['target_region']['center_depth_m']:.4f} m", font=font(22), fill=(245, 249, 252, 255))
    draw_status(draw, normal, (1215, 760), "正常输入")
    canvas.save(out_path, quality=95)


def render_acupoints(image: Image.Image, normal: dict[str, Any], out_path: Path) -> None:
    canvas, draw = base_canvas("03  穴位结果 | 像素坐标与置信度")
    x, y, scale = paste_scaled(canvas, image, (48, 120, 1180, 900))
    draw_points(draw, normal, (x, y), scale)
    draw.text((1230, 150), "输出", font=font(26), fill=(158, 211, 224, 255))
    draw.text((1230, 205), f"穴位数量 = {normal['acupoint_count']}", font=font(24), fill=(245, 249, 252, 255))
    draw.text((1230, 265), "坐标框架：", font=font(22), fill=(184, 199, 209, 255))
    draw.text((1230, 305), "RGB 像素 → 相机 →", font=font(22), fill=(245, 249, 252, 255))
    draw.text((1230, 345), "robot_base_candidate", font=font(22), fill=(245, 249, 252, 255))
    draw.text((1230, 410), "仿真目标 executable=false", font=font(22), fill=(125, 232, 180, 255))
    draw_status(draw, normal, (1215, 760), "正常输入")
    canvas.save(out_path, quality=95)


def render_comparison(image: Image.Image, normal: dict[str, Any], blocked: dict[str, Any], out_path: Path) -> None:
    canvas, draw = base_canvas("04  正常 / BLOCKING 对比 | 质量不足时闭锁")
    left_box, right_box = (46, 130, 778, 720), (822, 130, 1554, 720)
    lx, ly, lscale = paste_scaled(canvas, image, left_box)
    rx, ry, rscale = paste_scaled(canvas, image, right_box)
    draw_points(draw, normal, (lx, ly), lscale, label_size=16)
    draw_points(draw, blocked, (rx, ry), rscale, blocked=True, label_size=16)
    draw.rectangle(left_box, outline=(50, 190, 130, 255), width=5)
    draw.rectangle(right_box, outline=(210, 72, 77, 255), width=5)
    draw_status(draw, normal, (50, 750), "正常 | min-confidence=0.40", width=728)
    draw_status(draw, blocked, (824, 750), "低置信度 | min-confidence=0.99", width=728)
    draw.text((50, 872), "阻塞原因：7 个穴位低于阈值，目标区域置信度低于阈值", font=font(20), fill=(245, 206, 153, 255))
    draw.text((50, 916), "两种结果均保持 formal_use_allowed=false / promotion_locked=true / execution_allowed=false", font=font(19), fill=(188, 208, 220, 255))
    canvas.save(out_path, quality=95)


def write_table(normal: dict[str, Any], path: Path) -> None:
    fieldnames = ["穴位名称", "图像坐标_px", "相机坐标_m", "候选机器人坐标_m", "坐标置信度", "有效", "仿真目标", "可执行"]
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for item in normal["acupoints"]:
            writer.writerow({
                "穴位名称": item["name"],
                "图像坐标_px": json.dumps(item["pixel"], ensure_ascii=False),
                "相机坐标_m": json.dumps(item.get("point_camera_m"), ensure_ascii=False),
                "候选机器人坐标_m": json.dumps(item.get("point_robot_candidate_m"), ensure_ascii=False),
                "坐标置信度": f"{item.get('coordinate_confidence', 0.0):.6f}",
                "有效": str(item.get("valid") is True).lower(),
                "仿真目标": str(item.get("simulation_endpoint_target") is not None).lower(),
                "可执行": str((item.get("simulation_endpoint_target") or {}).get("executable", False)).lower(),
            })


def write_markdown(normal: dict[str, Any], blocked: dict[str, Any], image_path: Path, path: Path) -> None:
    lines = [
        "# B5-VISION 论文视觉结果表",
        "",
        "输入：`" + str(image_path) + "`，离线 RGB-D 背部样本。完整字段见 `acupoint_results.csv`。",
        "",
        "| 穴位 | 图像坐标 px | 相机坐标 m | 候选机器人坐标 m | 置信度 | 仿真目标 |",
        "|---|---:|---:|---:|---:|---|",
    ]
    for item in normal["acupoints"]:
        lines.append(
            "| {name} | `{pixel}` | `{camera}` | `{robot}` | {confidence:.3f} | {target} |".format(
                name=item["name"], pixel=item["pixel"], camera=item.get("point_camera_m"), robot=item.get("point_robot_candidate_m"), confidence=item.get("coordinate_confidence", 0.0), target="是（不可执行）" if item.get("simulation_endpoint_target") else "否"
            )
        )
    lines.extend([
        "",
        "## 正常 / 阻塞对比",
        "",
        f"正常输入：`pipeline_valid={normal.get('pipeline_valid')}`，7 个穴位输出；正式外参阻塞：`{normal.get('formal_blocking_reasons')}`。",
        f"低置信度输入：`pipeline_valid={blocked.get('pipeline_valid')}`，阻塞原因：`{blocked.get('blocking_reasons')}`；仿真目标为空。",
        "",
        "安全锁：`formal_use_allowed=false`，`promotion_locked=true`，`execution_allowed=false`。",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_outputs(image_path: Path, normal_path: Path, blocked_path: Path, out_dir: Path) -> dict[str, Any]:
    image = Image.open(image_path).convert("RGB")
    normal = load_report(normal_path, "normal")
    blocked = load_report(blocked_path, "blocked")
    if normal.get("pipeline_valid") is not True or normal.get("acupoint_count") != 7:
        raise ValueError("normal_report_must_be_valid_with_seven_acupoints")
    if blocked.get("pipeline_valid") is not False or not any(str(reason).startswith("low_confidence:") for reason in blocked.get("blocking_reasons", [])):
        raise ValueError("blocked_report_must_be_low_confidence")
    if any(item.get("simulation_endpoint_target") is not None for item in blocked.get("acupoints", [])):
        raise ValueError("blocked_report_contains_simulation_target")
    out_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(image_path, out_dir / "01_input_rgb.png")
    render_input(image, normal, out_dir / "01_input_overview.png")
    render_region(image, normal, out_dir / "02_target_region.png")
    render_acupoints(image, normal, out_dir / "03_acupoints_annotated.png")
    render_comparison(image, normal, blocked, out_dir / "04_normal_vs_blocked.png")
    write_table(normal, out_dir / "acupoint_results.csv")
    write_markdown(normal, blocked, image_path, out_dir / "acupoint_results.md")
    summary = {
        "schema_version": "b5.vision-paper-results.v1",
        "image_sha256": sha256_file(image_path),
        "normal_result": {"path": str(normal_path), "pipeline_id": normal.get("pipeline_id"), "pipeline_valid": True, "acupoint_count": normal.get("acupoint_count")},
        "blocked_result": {"path": str(blocked_path), "pipeline_id": blocked.get("pipeline_id"), "pipeline_valid": False, "blocking_reasons": blocked.get("blocking_reasons")},
        "locks": LOCKS,
        "hardware_access": normal.get("hardware_access"),
        "outputs": list(OUTPUT_NAMES),
    }
    (out_dir / "paper_results_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Create offline-only paper figures and tables from B5 vision JSON")
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--normal-result", required=True, type=Path)
    parser.add_argument("--blocked-result", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        summary = build_outputs(args.image, args.normal_result, args.blocked_result, args.out_dir)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        parser.error(str(error))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
