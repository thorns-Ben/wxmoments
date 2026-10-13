"""Windows GUI entry point, including a frozen-bundle smoke test."""
import json
import os
from pathlib import Path
import sys
import tempfile
import traceback


def self_test(output):
    from wm import db, probe, windows
    from wm.collector import Collector
    from wm.gui import App, HELP_TEXT
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    import uiautomation as auto

    report = {"frozen": bool(getattr(sys, "frozen", False)),
              "default_database": db.DB_PATH, "probe_report": probe.REPORT}
    with tempfile.TemporaryDirectory(prefix="wechat-release-test-") as tmp:
        db.DB_DIR = tmp
        db.DB_PATH = os.path.join(tmp, "moments.db")
        db.init_db()
        assert db.add_post("Release test", "今天", "测试内容 release 12345")
        assert not db.add_post("Release test", "今天", "测试内容 release 12345")
        assert len(db.search_posts("测试内容")) == 1
        assert db.export_txt(os.path.join(tmp, "export.txt")) == 1
        report["database"] = "insert, deduplicate, search, export passed"
        app = App()
        app.withdraw()
        try:
            app.update()
            app.var_kw.set("测试内容")
            app.on_search()
            assert len(app.result_rows) == 1
            assert len(app.tree.get_children()) == 1
            if report["frozen"]:
                assert "【源码版运行窗口提醒" not in HELP_TEXT
                assert Path(report["default_database"]).parent.parent == Path(sys.executable).parent
            report["gui"] = "Tk widgets and search passed"
            assert auto.GetRootControl() is not None
            report["uia"] = "Windows UI Automation loaded"
            # Test background capture against our own test window, never WeChat.
            import win32gui
            app.deiconify()
            app.update()
            hwnd = win32gui.GetAncestor(app.winfo_id(), 2)
            image = windows.capture_window(hwnd)
            assert image is not None and image.width > 100
            report["capture"] = "background capture of test GUI passed"
        finally:
            app.destroy()
        collector = Collector("Release test", use_ocr=True, log=lambda _: None)
        collector._ensure_ocr()
        image = Image.new("RGB", (1000, 180), "white")
        font = ImageFont.truetype(os.path.join(os.environ["WINDIR"], "Fonts", "arial.ttf"), 48)
        ImageDraw.Draw(image).text((30, 50), "Release test 12345", fill="black", font=font)
        results, _ = collector._ocr(np.array(image))
        assert results, "Bundled OCR failed to recognize synthetic text"
        recognized = " ".join(row[1] for row in results)
        assert "12345" in recognized, recognized
        report["ocr"] = recognized
    report["ok"] = True
    Path(output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def main():
    # Some OCR libraries use stdout/stderr even in a windowed executable.
    for stream in ("stdout", "stderr"):
        if getattr(sys, stream) is None:
            setattr(sys, stream, open(os.devnull, "w", encoding="utf-8"))
    testing = len(sys.argv) == 3 and sys.argv[1] == "--self-test"
    try:
        if testing:
            self_test(sys.argv[2])
        else:
            from wm.gui import main as gui_main
            gui_main()
        return 0
    except Exception:
        details = traceback.format_exc()
        if testing:
            Path(sys.argv[2]).write_text(json.dumps({"ok": False, "error": details},
                                                  ensure_ascii=False, indent=2), encoding="utf-8")
            return 1
        from tkinter import messagebox
        from wm import db
        try:
            Path(db.DB_DIR).mkdir(parents=True, exist_ok=True)
            log = Path(db.DB_DIR) / "crash.log"
            with log.open("a", encoding="utf-8") as handle:
                handle.write(details + "\n")
            hint = f"错误详情已保存到：\n{log}"
        except OSError:
            hint = "请把整个程序文件夹解压到有写入权限的位置，例如桌面。"
        messagebox.showerror("朋友圈工具启动失败", f"请确认已完整解压发布包。\n\n{hint}\n\n{details.splitlines()[-1]}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
