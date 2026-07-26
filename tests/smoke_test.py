#!/usr/bin/env python3
"""冒烟测试：真的去点、拖、删、撤销、保存，然后核对导出的表。

跑法：.venv/bin/python tests/smoke_test.py
"""

from __future__ import annotations

import csv
import json
import math
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "00_工具程序"))

from PySide6.QtCore import QPoint, Qt          # noqa: E402
from PySide6.QtTest import QTest               # noqa: E402
from PySide6.QtWidgets import QApplication     # noqa: E402

import iol_core as core                        # noqa: E402
from iol_tilt_labeler_qt import MainWindow     # noqa: E402

FAILED: list[str] = []
PASSED = 0


def check(name: str, ok: bool, detail: str = ""):
    global PASSED
    if ok:
        PASSED += 1
        print(f"  ✓ {name}")
    else:
        FAILED.append(f"{name} {detail}")
        print(f"  ✗ {name} {detail}")


def click(canvas, x, y, modifier=Qt.NoModifier):
    """在图像坐标 (x, y) 处点一下。"""
    w = canvas.image_to_widget(x, y)
    QTest.mouseClick(canvas, Qt.LeftButton, modifier, QPoint(int(w.x()), int(w.y())))


def drag(canvas, x0, y0, x1, y1):
    a = canvas.image_to_widget(x0, y0)
    b = canvas.image_to_widget(x1, y1)
    QTest.mousePress(canvas, Qt.LeftButton, Qt.NoModifier, QPoint(int(a.x()), int(a.y())))
    QTest.mouseMove(canvas, QPoint(int(b.x()), int(b.y())))
    QTest.mouseRelease(canvas, Qt.LeftButton, Qt.NoModifier, QPoint(int(b.x()), int(b.y())))


def main() -> int:
    work = Path("/tmp/iol_smoke")
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    cal = core.generate_calibration_images(work / "x")     # -> work/IOL校准测试图
    images = sorted(p for p in cal.iterdir() if p.suffix.lower() == ".png")

    app = QApplication.instance() or QApplication([])
    win = MainWindow()
    win.resize(1280, 840)
    win.show()
    QTest.qWaitForWindowExposed(win)
    win.start_session(images, cal)
    QTest.qWait(100)

    canvas = win.canvas
    print("\n[1] 打开与列表")
    check("载入全部图片", len(win.images) == len(images), f"{len(win.images)}/{len(images)}")
    check("文件列表行数一致", win.file_list.count() == len(images))
    check("输出目录已建", (cal / "IOL_Tilt_Output" / "annotated").is_dir())

    print("\n[2] 取点与自动跳步")
    win.set_mode("pupil")
    click(canvas, 200, 400)
    click(canvas, 1000, 380)
    label = win.current_label()
    check("A-B 记录 2 点", len(label["pupil_plane"]) == 2, str(label["pupil_plane"]))
    check("点满 A-B 自动跳到前表面", win.mode == "anterior", win.mode)
    check("A 点坐标接近点击位置",
          abs(label["pupil_plane"][0][0] - 200) < 2 and abs(label["pupil_plane"][0][1] - 400) < 2,
          str(label["pupil_plane"][0]))

    def curve(x, base):
        return base + 0.00055 * (x - 600) ** 2

    for x in (430, 520, 680, 770):
        click(canvas, x, curve(x, 330))
    win.set_mode("posterior")
    for x in (430, 520, 680, 770):
        click(canvas, x, curve(x, 390))
    label = win.current_label()
    check("前表面 4 点", len(label["anterior"]) == 4)
    check("后表面 4 点", len(label["posterior"]) == 4)
    check("超出上限不再加点",
          (win.set_mode("pupil"), click(canvas, 600, 600), len(win.current_label()["pupil_plane"]))[-1] == 2)

    print("\n[3] 预览结果")
    result = core.compute_result(win.current_label())
    # 点击落到整数屏幕像素，实际坐标会有亚像素偏差，按实际存下来的点算期望值
    (ax, ay), (bx, by) = win.current_label()["pupil_plane"]
    expected_pupil = math.degrees(math.atan(abs(by - ay) / abs(bx - ax)))
    check("A-B 角度与几何一致", abs(result["pupil_angle"] - expected_pupil) < 1e-6,
          f"{result['pupil_angle']:.3f} vs {expected_pupil:.3f}")
    check("自动轴优先", result["axis_source"] == "auto_circle", result["axis_source"])
    check("最终夹角 = |IOL - A-B|",
          abs(result["final_angle"] - abs(result["difference"])) < 1e-9)

    print("\n[4] 拖动 / 删除 / 撤销 / 重做")
    win.set_mode("anterior")
    before = list(win.current_label()["anterior"][0])
    drag(canvas, before[0], before[1], before[0] + 30, before[1] + 12)
    after = win.current_label()["anterior"][0]
    check("拖动改变点位", abs(after[0] - before[0] - 30) < 2 and abs(after[1] - before[1] - 12) < 2,
          f"{before} -> {after}")
    win.undo()
    check("撤销回到拖动前", abs(win.current_label()["anterior"][0][0] - before[0]) < 0.01,
          str(win.current_label()["anterior"][0]))
    win.redo()
    check("重做恢复拖动后", abs(win.current_label()["anterior"][0][0] - after[0]) < 0.01)
    win.undo()

    n_before = len(win.current_label()["anterior"])
    pt = win.current_label()["anterior"][1]
    click(canvas, pt[0], pt[1], Qt.AltModifier)
    check("⌥点击删除该点", len(win.current_label()["anterior"]) == n_before - 1,
          f"{n_before} -> {len(win.current_label()['anterior'])}")
    win.undo()
    check("撤销恢复删除", len(win.current_label()["anterior"]) == n_before)

    win.canvas.selected = ("anterior", 0)
    x_before = win.current_label()["anterior"][0][0]
    win.nudge_selected(1, 0)
    check("方向键微调 1px", abs(win.current_label()["anterior"][0][0] - x_before - 1) < 1e-6)

    print("\n[5] 保存与导出")
    win.note_edit.setText("冒烟测试")
    ok = win.save_current()
    check("保存成功", ok)
    out = cal / "IOL_Tilt_Output"
    saved = win.current_label().get("result") or {}
    ann = saved.get("annotated_file", "")
    check("annotated_file 是真实路径", bool(ann) and ann != "None" and Path(ann).exists(), ann)
    check("标注图已生成", any((out / "annotated").glob("*_annotated.png")))
    check("labels.json 已写", (out / "labels.json").exists())
    check("csv 已写", (out / "iol_tilt_results.csv").exists())
    check("xlsx 已写", (out / "iol_tilt_results.xlsx").exists())

    with (out / "iol_tilt_results.csv").open(encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    check("表格只有四列",
          list(rows[0].keys()) == ["IOL轴角度", "A-B角度", "最终夹角", "备注"], str(list(rows[0].keys())))
    check("行数 = 图片数", len(rows) == len(images), f"{len(rows)}/{len(images)}")
    check("备注写入表格", rows[0]["备注"] == "冒烟测试", rows[0]["备注"])
    check("最终夹角与内存结果一致",
          rows[0]["最终夹角"] == core.final_angle_text(saved), rows[0]["最终夹角"])
    check("未标注的图留空", rows[1]["最终夹角"] == "")

    data = json.loads((out / "labels.json").read_text(encoding="utf-8"))
    check("labels.json 覆盖全部图片", len(data) == len(images))

    print("\n[6] 状态与切图")
    check("已完成计数", win.done_count() == 1, str(win.done_count()))
    check("状态栏有提示", "已保存" in win.status_text.text(), win.status_text.text())
    win.next_image()
    check("切到第二张", win.index == 1)
    check("第二张点位是空的", not win.current_label()["pupil_plane"])
    check("撤销栈按图独立", not win.current_stack().past)
    win.prev_image()
    check("切回第一张仍有结果", bool(win.current_label().get("result")))
    check("第一张撤销栈还在", bool(win.current_stack().past))

    print("\n[7] 图像调节")
    win.slider_contrast.setValue(60)
    win.btn_invert.setChecked(True)
    QTest.qWait(50)
    check("反相后画面已重建", canvas.image is not None and canvas.invert is True)
    win.reset_adjust()
    check("复位后回到原图", canvas.brightness == 0 and canvas.contrast == 0 and not canvas.invert)

    win.close()
    print(f"\n通过 {PASSED} 项，失败 {len(FAILED)} 项")
    for item in FAILED:
        print("  失败：" + item)
    return 1 if FAILED else 0


if __name__ == "__main__":
    sys.exit(main())
