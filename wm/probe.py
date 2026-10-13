# -*- coding: utf-8 -*-
"""探针：检测微信朋友圈窗口能否通过 UI Automation 直接读到文字。
用法：python -m wm.probe
结果同时写入 data/probe_report.txt，方便发给开发者判断。"""
import os
import time

import uiautomation as auto

from . import db, windows

REPORT = os.path.join(db.DB_DIR, "probe_report.txt")


def walk_texts(ctrl, stop_event=None, max_depth=24, max_nodes=3000):
    """深度优先遍历控件树，收集所有文字控件的文本。"""
    texts = []
    count = [0]

    def rec(node, depth):
        if stop_event is not None and stop_event.is_set():
            return
        if count[0] > max_nodes or depth > max_depth:
            return
        count[0] += 1
        try:
            if node.ControlType == auto.ControlType.TextControl:
                name = node.Name or ""
                for piece in name.splitlines():
                    piece = piece.strip()
                    if piece:
                        texts.append(piece)
        except Exception:
            pass
        try:
            children = node.GetChildren()
        except Exception:
            return
        for ch in children:
            rec(ch, depth + 1)

    rec(ctrl, 0)
    return texts


def probe_window(win):
    ctrl = auto.ControlFromHandle(win["hwnd"])
    if ctrl is None:
        return {"ok": False, "reason": "UI Automation 无法附加到该窗口", "texts": []}
    auto.SetGlobalSearchTimeout(2)
    t0 = time.time()
    try:
        texts = walk_texts(ctrl)
    except Exception as e:
        return {"ok": False, "reason": "遍历控件树失败：%s" % e, "texts": []}
    return {"ok": True, "elapsed": round(time.time() - t0, 1), "texts": texts}


def run_probe(log=print):
    lines = []

    def out(s):
        log(s)
        lines.append(s)

    wins = windows.list_wechat_windows()
    out("找到 %d 个微信窗口：" % len(wins))
    for i, w in enumerate(wins):
        out("  [%d] 进程=%s 标题=%r 位置=%s" % (i, w.get("exe", "?"), w["title"], w["rect"]))
    if not wins:
        out("没有找到微信窗口。请先登录电脑版微信（建议 4.0.3 以上版本）。")
        out("若微信已登录但仍提示找不到，请确认微信版本为新版（进程 Weixin.exe）。")
        _save(lines)
        return

    from .collector import count_time_markers  # 延迟导入，避免循环引用

    auto.SetGlobalSearchTimeout(2)

    # 第一轮：界面直读（UIA），按“日期标记数量”判断是否朋友圈内容
    out("")
    out("—— 第 1 轮：界面直读（UI Automation）——")
    uia_best = None
    for i, w in enumerate(wins):
        r = probe_window(w)
        texts = r.get("texts", []) if r["ok"] else []
        marks = count_time_markers(texts)
        out("  [%d] 进程=%s 标题=%r：直读 %d 行，日期标记 %d 个。"
            % (i, w.get("exe", "?"), w["title"], len(texts), marks))
        if marks >= 2 and uia_best is None:
            uia_best = (w, texts)
    if uia_best:
        w, texts = uia_best
        out("")
        out("判定：UI 直读可用，窗口标题 %r 能读到朋友圈日期标记。" % w["title"])
        out("      采集时选“自动检测”即可。内容样例：")
        for t in texts[:60]:
            out("   | " + t)
        _save(lines)
        return

    # 第二轮：截图识字（OCR）逐窗口实测
    out("")
    out("—— 第 2 轮：直读未发现朋友圈内容，改用截图识字（OCR）实测，")
    out("   首次加载引擎约几十秒，请稍候…… ——")
    try:
        import numpy as np
        from PIL import ImageGrab
        from rapidocr_onnxruntime import RapidOCR
        ocr = RapidOCR()
    except Exception as e:
        out("OCR 引擎加载失败：%s" % e)
        _save(lines)
        return

    ocr_best = None
    for i, w in enumerate(wins):
        # 后台截图：窗口被其他程序遮挡也能识别，不需要置前
        rect = windows.get_rect(w["hwnd"])
        if not rect:
            continue
        img = windows.capture_window(w["hwnd"])
        if img is None:
            img = ImageGrab.grab(bbox=rect, all_screens=True)
        result, _ = ocr(np.array(img.convert("RGB")))
        items = []
        if result:
            for item in result:
                try:
                    box, text, score = item[0], item[1], item[2]
                except Exception:
                    continue
                if not text or not score or score < 0.5:
                    continue
                ys = [p[1] for p in box]
                xs = [p[0] for p in box]
                items.append((sum(ys) / 4.0, sum(xs) / 4.0, text.strip()))
        items.sort(key=lambda x: (round(x[0] / 12.0), x[1]))
        texts = [t for _, _, t in items if t]
        marks = count_time_markers(texts)
        out("  [%d] 进程=%s 标题=%r：OCR %d 行，日期标记 %d 个。"
            % (i, w.get("exe", "?"), w["title"], len(texts), marks))
        if marks >= 2 and ocr_best is None:
            ocr_best = (w, texts)

    out("")
    if ocr_best:
        w, texts = ocr_best
        out("判定：OCR 能正常读到朋友圈内容（进程 %s 标题 %r）。" % (w.get("exe", "?"), w["title"]))
        out("      采集时选“强制 OCR”最稳（自动检测也会自动切到 OCR）。内容样例：")
        for t in texts[:60]:
            out("   | " + t)
    else:
        out("判定：所有微信窗口里都没识别到朋友圈内容。")
        out("      请先在微信里打开目标好友的朋友圈相册（能往下翻历史的页面），")
        out("      并保证它没被其他窗口遮挡，再重新运行探针/开始采集。")
    _save(lines)


def _save(lines):
    os.makedirs(os.path.dirname(REPORT), exist_ok=True)
    with open(REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n报告已保存：%s" % REPORT)


if __name__ == "__main__":
    run_probe()
