# -*- coding: utf-8 -*-
"""图形界面：① 采集  ② 搜索  ③ 使用说明。"""
import queue
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

from . import db
from .collector import Collector
from .probe import run_probe

_LAUNCH_HELP = ("""【EXE 版启动】

解压整个发布包后，双击 wechat-find.exe 即可运行，无需安装 Python。
请保留同目录的 _internal 文件夹；数据保存在 EXE 同目录的 data 文件夹。
EXE 版没有黑色命令行窗口。
""" if getattr(sys, "frozen", False) else """【源码版运行窗口提醒（重要）】

通过 run.bat 启动后，请勿关闭它打开的命令行窗口（黑色窗口）。
这个命令行窗口可以最小化，关闭它会导致工具退出、采集中断。
程序正常退出后，命令行窗口会自动关闭。
""")

HELP_TEXT = _LAUNCH_HELP + """

【采集期间】

微信里的朋友圈窗口需要保持打开，不要最小化。
退出时，请先点“停止”并等待采集结束，再关闭工具的图形界面。


【使用步骤】

1. 电脑微信升级到 4.0.3 以上版本并登录（微信官网下载最新版即可）。

2. 在微信里打开目标好友的“资料页” → 点击“朋友圈”板块，
   进入 TA 的朋友圈相册（可以一路往下翻历史的那个页面）。
   让这个朋友圈窗口保持打开、显示在屏幕上。

3. 回到本工具，在“① 采集”页填写好友备注名（随便起，仅用于分类），
   点“开始采集”。工具在【后台】自动滚动和识别：不占用你的鼠标、
   不抢窗口焦点，微信窗口被其他窗口盖住也照常采集——
   只要【不要最小化】朋友圈窗口即可，你可以正常用电脑做别的事。

4. 提示“采集结束”后，到“② 搜索”页输入关键词即可搜索。
   搜索范围：正文 + 评论 + 点赞名单 + 时间。

5. 朋友圈很多时可以分几次采：随时可以点“停止”，
   下次再点“开始采集”会自动接着往下、不会重复。


【安全须知（重要）】

· 单次采集建议不超过 1~2 小时；多年动态分几天采完最稳。
· 若微信弹出“操作频繁/安全验证”，工具会自动停止，
  请先在微信里完成验证、等几个小时再继续。
· 本工具只模拟鼠标滚动和读取屏幕，不碰微信协议、不注入微信，
  但微信用户协议禁止自动化，风险虽低但不为零，请自行把握。
· 只能抓到你这个微信号本来就能看到的内容：
  对方设置了“三天可见/半年可见”、已删除、分组屏蔽的，抓不到。
· 数据全部保存在本机 data\\moments.db，不上传任何服务器。
  仅限个人备份与查找，请勿转发、传播或商用。


【两种采集模式】

· 自动检测（推荐）：先尝试直接读取界面文字，读不到自动转截图识字（OCR）。
· 强制 OCR：探针报告说“自绘界面”时使用；首次加载识别引擎需几十秒。
  注意：微信 4.x（进程 Weixin.exe）是自绘界面，UI 直读不到文字，
  选“自动检测”会自动切换到 OCR，也可以直接选“强制 OCR”。

【常见问题】

Q: 点开始提示“没有找到微信窗口”？
A: 先确认微信已登录，并把好友朋友圈相册页面打开再点开始。

Q: OCR 模式识别有错别字？
A: 截图识字存在少量误差，不影响关键词大致定位，点开结果可对照原微信。

Q: 换电脑怎么办？
A: 把整个文件夹拷走即可，data\\moments.db 就是全部数据。
"""


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("朋友圈采集与搜索工具")
        self.geometry("900x680")
        self.minsize(760, 560)
        self.msg_queue = queue.Queue()
        self.collector = None
        self.worker = None
        self.result_rows = []
        db.init_db()
        self._build_ui()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(150, self._poll_queue)

    def on_close(self):
        if self.worker and self.worker.is_alive():
            self.on_stop()
            self.var_status.set("状态：正在停止，结束后自动退出")
            self.after(200, self._close_when_stopped)
        else:
            self.destroy()

    def _close_when_stopped(self):
        if self.worker and self.worker.is_alive():
            self.after(200, self._close_when_stopped)
        else:
            self.destroy()

    # ---------------- 界面 ----------------

    def _build_ui(self):
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=10)
        tab_c = ttk.Frame(nb)
        tab_s = ttk.Frame(nb)
        tab_h = ttk.Frame(nb)
        nb.add(tab_c, text="  ① 采集  ")
        nb.add(tab_s, text="  ② 搜索  ")
        nb.add(tab_h, text="  ③ 使用说明  ")
        nb.bind("<<NotebookTabChanged>>", lambda e: self._refresh_friends())
        self._build_collect(tab_c)
        self._build_search(tab_s)
        self._build_help(tab_h)

    def _build_collect(self, tab):
        top = ttk.LabelFrame(tab, text="第一步：在微信里打开好友的朋友圈相册，然后点开始")
        top.pack(fill="x", padx=8, pady=8)

        row = ttk.Frame(top)
        row.pack(fill="x", padx=10, pady=8)
        ttk.Label(row, text="好友备注名：").pack(side="left")
        self.var_name = tk.StringVar()
        ttk.Entry(row, textvariable=self.var_name, width=22).pack(side="left", padx=(0, 18))
        ttk.Label(row, text="采集模式：").pack(side="left")
        self.var_mode = tk.StringVar(value="auto")
        ttk.Radiobutton(row, text="自动检测", variable=self.var_mode,
                        value="auto").pack(side="left")
        ttk.Radiobutton(row, text="强制OCR", variable=self.var_mode,
                        value="ocr").pack(side="left", padx=(4, 18))

        btns = ttk.Frame(top)
        btns.pack(fill="x", padx=10, pady=(0, 10))
        self.btn_probe = ttk.Button(btns, text="环境探针（先测能不能读）", command=self.on_probe)
        self.btn_probe.pack(side="left")
        self.btn_start = ttk.Button(btns, text="开始采集", command=self.on_start)
        self.btn_start.pack(side="left", padx=8)
        self.btn_stop = ttk.Button(btns, text="停止", command=self.on_stop, state="disabled")
        self.btn_stop.pack(side="left")
        self.var_status = tk.StringVar(value="状态：空闲")
        ttk.Label(btns, textvariable=self.var_status, foreground="#555").pack(side="left", padx=18)

        logf = ttk.LabelFrame(tab, text="运行日志")
        logf.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.txt_log = tk.Text(logf, height=16, wrap="word", state="disabled",
                               background="#1e1e1e", foreground="#d4d4d4", font=("Consolas", 10))
        self.txt_log.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
        sb = ttk.Scrollbar(logf, command=self.txt_log.yview)
        sb.pack(side="right", fill="y", pady=8, padx=(0, 8))
        self.txt_log["yscrollcommand"] = sb.set

    def _build_search(self, tab):
        top = ttk.Frame(tab)
        top.pack(fill="x", padx=8, pady=10)
        ttk.Label(top, text="好友：").pack(side="left")
        self.var_friend = tk.StringVar(value="全部")
        self.cb_friend = ttk.Combobox(top, textvariable=self.var_friend,
                                      values=["全部"], width=14, state="readonly")
        self.cb_friend.pack(side="left", padx=(0, 14))
        ttk.Label(top, text="关键词：").pack(side="left")
        self.var_kw = tk.StringVar()
        ent = ttk.Entry(top, textvariable=self.var_kw, width=28)
        ent.pack(side="left")
        ent.bind("<Return>", lambda e: self.on_search())
        ttk.Button(top, text="搜索", command=self.on_search).pack(side="left", padx=8)
        ttk.Button(top, text="导出结果为txt", command=self.on_export).pack(side="left")

        cols = ("time", "friend", "preview")
        self.tree = ttk.Treeview(tab, columns=cols, show="headings")
        self.tree.heading("time", text="时间")
        self.tree.heading("friend", text="好友")
        self.tree.heading("preview", text="内容（双击看全文）")
        self.tree.column("time", width=150, anchor="w")
        self.tree.column("friend", width=120, anchor="w")
        self.tree.column("preview", width=560, anchor="w")
        self.tree.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        sb = ttk.Scrollbar(tab, orient="vertical", command=self.tree.yview)
        sb.place(relx=1.0, rely=0.28, relheight=0.68, anchor="ne")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.bind("<Double-1>", self.on_show_detail)
        self.var_count = tk.StringVar(value="共 0 条")
        ttk.Label(tab, textvariable=self.var_count, foreground="#555").pack(anchor="w", padx=10)

    def _build_help(self, tab):
        txt = tk.Text(tab, wrap="word", font=("Microsoft YaHei UI", 11))
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        txt.insert("1.0", HELP_TEXT)
        txt.configure(state="disabled")

    # ---------------- 日志/队列 ----------------

    def log(self, msg):
        self.msg_queue.put(("log", str(msg)))

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self.msg_queue.get_nowait()
                if kind == "log":
                    self.txt_log.configure(state="normal")
                    self.txt_log.insert("end", payload + "\n")
                    self.txt_log.see("end")
                    self.txt_log.configure(state="disabled")
                elif kind == "done":
                    self._set_running(False)
                    self._refresh_friends()
        except queue.Empty:
            pass
        self.after(150, self._poll_queue)

    def _set_running(self, running):
        self.btn_start.configure(state="disabled" if running else "normal")
        self.btn_probe.configure(state="disabled" if running else "normal")
        self.btn_stop.configure(state="normal" if running else "disabled")
        self.var_status.set("状态：后台采集中……可正常使用电脑" if running else "状态：空闲")

    # ---------------- 采集 ----------------

    def on_probe(self):
        self.btn_probe.configure(state="disabled")
        self.log("运行环境探针……")

        def work():
            try:
                run_probe(log=self.log)
            except Exception as e:
                self.log("探针异常：%s" % e)
            finally:
                self.msg_queue.put(("done_probe", None))

        threading.Thread(target=work, daemon=True).start()
        # 探针通常十几秒内完成，15 秒后恢复按钮
        self.after(15000, lambda: self.btn_probe.configure(state="normal"))

    def on_start(self):
        name = self.var_name.get().strip()
        if not name:
            messagebox.showwarning("提示", "请先填写好友备注名。")
            return
        use_ocr = self.var_mode.get() == "ocr"
        stop_event = threading.Event()
        self.collector = Collector(name, use_ocr=use_ocr, log=self.log, stop_event=stop_event)
        self._set_running(True)
        self.log("=" * 50)

        def work():
            try:
                self.collector.run()
            except Exception as e:
                self.log("采集线程异常：%s" % e)
            finally:
                self.msg_queue.put(("done", None))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def on_stop(self):
        if self.collector:
            self.collector.stop()
            self.log("已请求停止，等待当前屏幕读完……")

    # ---------------- 搜索 ----------------

    def _refresh_friends(self):
        try:
            friends = ["全部"] + [n for n, _c in db.list_friends()]
            self.cb_friend.configure(values=friends)
            if self.var_friend.get() not in friends:
                self.var_friend.set("全部")
        except Exception:
            pass

    def on_search(self):
        kw = self.var_kw.get().strip()
        friend = self.var_friend.get()
        rows = db.search_posts(kw, friend if friend != "全部" else None)
        self.result_rows = rows
        for item in self.tree.get_children():
            self.tree.delete(item)
        for r in rows:
            preview = r["content"].replace("\n", "  ")[:90]
            self.tree.insert("", "end", values=(r["time_raw"], r["friend"], preview))
        self.var_count.set("共 %d 条" % len(rows))

    def on_show_detail(self, _event=None):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        if idx >= len(self.result_rows):
            return
        r = self.result_rows[idx]
        win = tk.Toplevel(self)
        win.title("朋友圈全文")
        win.geometry("620x460")
        txt = tk.Text(win, wrap="word", font=("Microsoft YaHei UI", 11))
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        txt.insert("1.0", "好友：%s\n时间：%s\n%s\n\n%s"
                   % (r["friend"], r["time_raw"], "=" * 40, r["content"]))
        txt.configure(state="disabled")

    def on_export(self):
        kw = self.var_kw.get().strip()
        friend = self.var_friend.get()
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("文本文件", "*.txt")],
            initialfile="朋友圈搜索结果.txt",
        )
        if not path:
            return
        try:
            n = db.export_txt(path, keyword=kw,
                              friend_name=friend if friend != "全部" else None)
            messagebox.showinfo("导出完成", "已导出 %d 条到：\n%s" % (n, path))
        except Exception as e:
            messagebox.showerror("导出失败", str(e))


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
