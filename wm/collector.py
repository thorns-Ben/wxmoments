# -*- coding: utf-8 -*-
"""朋友圈采集器（后台模式）。
工作方式：定位微信朋友圈窗口 -> 后台截图(OCR)或直读 -> 按时间标记切成单条朋友圈
-> 去重入库 -> 后台消息滚动（不移动真实鼠标、不抢前台，窗口被遮挡也能采）。
连续若干屏无新内容判定翻到底；遇到风控提示自动停止。
"""
import random
import re
import threading
import time

from . import db, windows
from .probe import walk_texts

# 朋友圈时间标记。
# 两种视图：①好友朋友圈相册——左侧大日期分隔符在分组【顶部】：
#   “置顶/今天/昨天”→“2026年”→“9月5日”（月份分隔可能只显示“9月”，
#   日+月竖排 OCR 可能识别成“05 9月”）；
# ②信息流——相对时间在一条动态【底部】，如“3小时前/昨天/刚刚”。
_ALBUM_MARKER_PATTERNS = [
    re.compile(r"^\s*置顶\s*$"),
    re.compile(r"^\s*今天\s*$"),
    re.compile(r"^\s*\d{4}\s*年(\s*\d{1,2}\s*月(\s*\d{1,2}\s*日?)?)?\s*$"),
    re.compile(r"^\s*\d{1,2}\s*月\s*\d{1,2}\s*日?\s*$"),
    re.compile(r"^\s*\d{1,2}\s*月\s*$"),
    re.compile(r"^\s*\d{1,2}\s*日?\s*\d{1,2}\s*月\s*$"),
]
_FEED_MARKER_PATTERNS = [
    re.compile(r"^\s*\d+\s*分钟前\s*$"),
    re.compile(r"^\s*\d+\s*小时前\s*$"),
    re.compile(r"^\s*\d+\s*天前\s*$"),
    re.compile(r"^\s*(昨天|前天)(\s+\d{1,2}:\d{2})?\s*$"),
    re.compile(r"^\s*刚刚\s*$"),
]
_TIME_PATTERNS = _ALBUM_MARKER_PATTERNS + _FEED_MARKER_PATTERNS
# OCR 可能把“日期类”分隔符与相邻内容粘在一行，短行做兜底搜索。
# 注意：“置顶/今天”极易出现在正文开头（如“今天去医院了”），只允许整行精确匹配，
# 不放进模糊兜底，避免把帖子正文误判为分隔符。
_MARKER_SEARCH = re.compile(
    r"(20\d{2}\s*年|\d{1,2}\s*月\s*\d{1,2}\s*日|\d+\s*(分钟|小时|天)前)")

# 风控/验证提示，出现就立即停
RISK_KEYWORDS = [
    "操作频繁", "操作过于频繁", "访问过于频繁",
    "安全验证", "请完成验证", "环境异常",
]

NO_NEW_LIMIT = 12        # 连续多少屏无新内容判定翻到底
SCROLL_TICKS = 6         # 每屏滚轮格数（一次滚得更多）
REST_EVERY = 60          # 每多少屏短暂休息一次（速度优先，只歇几秒）


def is_time_marker(line):
    s = (line or "").strip()
    if not s:
        return False
    if any(p.match(s) for p in _TIME_PATTERNS):
        return True
    return len(s) <= 12 and bool(_MARKER_SEARCH.search(s))


def is_feed_marker(line):
    """信息流时间标记（块尾）：X分钟前/X小时前/X天前/昨天/前天/刚刚。"""
    s = (line or "").strip()
    return bool(s) and any(p.match(s) for p in _FEED_MARKER_PATTERNS)


def count_time_markers(lines):
    return sum(1 for x in lines if is_time_marker(x))


def split_posts(lines):
    """把按阅读顺序读到的文字行切成单条动态。
    · 相册视图（置顶/今天/年/月日）：日期标签在分组【顶部】，标签之后、
      下一个标签之前的内容属于该标签；
    · 信息流视图（X分钟前/昨天/刚刚）：时间行在动态【底部】，标签之前、
      上一个标签之后的内容属于该标签。
    相册最后一个分组（如“今天”的帖子）正常入库；信息流最后一个残块丢弃，
    下一屏完整后会被抓到。"""
    posts = []
    cur = None       # None=首个标记前；相册标签名；'__feed__'=信息流模式
    buf = []

    def _flush(marker):
        if buf:
            content = "\n".join(buf).strip()
            if content:
                posts.append((marker, content))

    for line in lines:
        s = (line or "").strip()
        if not s:
            continue
        if is_time_marker(s):
            if is_feed_marker(s):
                # 信息流：时间行在动态底部，上方缓冲（含首个标记前的内容）属于这条时间
                _flush(s)
                cur = "__feed__"
                buf = []
            else:
                # 相册：关闭上一个标签分组；首个标签之前是封面/签名噪声，丢弃
                if cur not in (None, "__feed__"):
                    _flush(cur)
                cur = s
                buf = []
        else:
            buf.append(s)

    # 结束时：相册最后一个分组入库；信息流残块丢弃
    if cur not in (None, "__feed__"):
        _flush(cur)
    return posts


class Collector:
    def __init__(self, friend_name, use_ocr=False, log=print, stop_event=None):
        self.friend_name = (friend_name or "").strip()
        self.use_ocr = use_ocr
        self.log = log
        self.stop_event = stop_event or threading.Event()
        self._ocr = None
        self._image_grab = None

    def stop(self):
        self.stop_event.set()

    # ---------- 读数通道 ----------

    def _read_lines_uia(self, hwnd):
        import uiautomation as auto
        ctrl = auto.ControlFromHandle(hwnd)
        if ctrl is None:
            return None
        try:
            return walk_texts(ctrl, stop_event=self.stop_event)
        except Exception as e:
            self.log("读屏异常：%s" % e)
            return None

    def _ensure_ocr(self):
        if self._ocr is None:
            self.log("正在加载 OCR 识别引擎（首次约几十秒）……")
            import numpy as np  # noqa: F401  依赖自检
            from PIL import ImageGrab
            from rapidocr_onnxruntime import RapidOCR
            self._ocr = RapidOCR()
            self._image_grab = ImageGrab
            self.log("OCR 引擎就绪。")

    def _read_lines_ocr(self, hwnd, rect):
        self._ensure_ocr()
        # 首选后台截图（窗口被遮挡也能截到）；失败再退回屏幕抓取
        img = windows.capture_window(hwnd)
        if img is None:
            l, t, r, b = rect
            img = self._image_grab.grab(bbox=(l, t, r, b), all_screens=True)
        import numpy as np
        result, _ = self._ocr(np.array(img.convert("RGB")))
        if not result:
            return []
        # result: [[四点坐标, 文本, 置信度], ...]，按从上到下、从左到右排序
        items = []
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
        return [t for _, _, t in items if t]

    # ---------- 滚动（后台消息，不碰鼠标） ----------

    def _scroll_down(self, hwnd):
        """后台滚轮：投递 WM_MOUSEWHEEL，不动鼠标、不抢前台。"""
        windows.scroll_background(hwnd, ticks=SCROLL_TICKS)

    def _sleep(self, seconds):
        end = time.time() + seconds
        while time.time() < end:
            if self.stop_event.is_set():
                return
            time.sleep(0.2)

    # ---------- 主流程 ----------

    def _find_content_window(self, force_ocr):
        """在所有微信窗口里找出真正显示朋友圈内容的那个。
        判据：画面中能读到 >=2 个日期/时间标记（菜单、聊天列表都不含日期分隔符）。
        返回 (窗口信息, 'uia'|'ocr')；找不到返回 (None, None)。"""
        wins = windows.list_wechat_windows()
        if not wins:
            self.log("没有找到微信窗口。请先登录电脑版微信并打开好友的朋友圈相册。")
            return None, None
        self.log("找到 %d 个微信窗口，正在逐个确认哪个显示着朋友圈……" % len(wins))

        def _desc(w):
            return "进程=%s 标题=%r" % (w.get("exe", "?"), w["title"])

        if not force_ocr:
            for w in wins:
                lines = self._read_lines_uia(w["hwnd"]) or []
                marks = count_time_markers(lines)
                self.log("  %s：直读 %d 行，日期标记 %d 个。" % (_desc(w), len(lines), marks))
                if marks >= 2:
                    self.log("  ↑ 该窗口可直读朋友圈内容。")
                    return w, "uia"
            self.log("直读未发现朋友圈内容（新版微信为自绘界面，属正常），改用截图识字确认……")

        self._ensure_ocr()
        for w in wins:
            # 后台截图即可识别内容，不需要置前窗口、不影响用户当前操作
            rect = windows.get_rect(w["hwnd"])
            if not rect:
                continue
            lines = self._read_lines_ocr(w["hwnd"], rect)
            marks = count_time_markers(lines)
            self.log("  %s：OCR %d 行，日期标记 %d 个。" % (_desc(w), len(lines), marks))
            if marks >= 2:
                self.log("  ↑ 已确认朋友圈内容窗口。")
                return w, "ocr"
        return None, None

    def run(self):
        db.init_db()
        if not self.friend_name:
            self.log("请先填写好友备注名（给数据打标签用）。")
            return False

        win, channel = self._find_content_window(self.use_ocr)
        if win is None:
            self.log("没能在微信窗口里识别到朋友圈内容。请确认：")
            self.log("  1) 微信里已打开该好友的朋友圈相册（能一路往下翻历史的页面）；")
            self.log("  2) 朋友圈窗口没有被最小化（被其他窗口遮挡没关系），然后重新点“开始采集”。")
            return False
        hwnd = win["hwnd"]
        self.log("目标窗口：进程=%s 标题=%r 区域=%s"
                 % (win.get("exe", "?"), win["title"], win["rect"]))

        # 后台模式：不置前、不动鼠标。仅要求窗口未最小化（被其他窗口遮挡没关系）。
        if not windows.get_rect(hwnd):
            self.log("目标窗口已最小化或不可见，请恢复窗口（可以被其他窗口盖住，但不要最小化）后重新开始。")
            return False

        use_ocr = (channel == "ocr")
        self.log("采集通道：%s（后台运行，不占用鼠标）。"
                 % ("截图识字 OCR" if use_ocr else "界面直读 UIA"))

        total_new = 0
        no_new = 0
        scrolls = 0
        prev_sig = None
        fallback_used = False
        self.log("开始采集。你可以正常使用电脑，微信窗口被其他窗口盖住也没关系，但不要最小化它。")
        try:
            while not self.stop_event.is_set():
                rect = windows.get_rect(hwnd)
                if not rect:
                    self.log("微信窗口被最小化，已暂停。请恢复窗口后重新点“开始采集”（已采内容不会丢）。")
                    break
                if use_ocr:
                    lines = self._read_lines_ocr(hwnd, rect)
                else:
                    lines = self._read_lines_uia(hwnd)
                    if lines is None:
                        self.log("界面直读中途失效，自动切换 OCR 继续。")
                        use_ocr = True
                        continue
                if lines is None:
                    self.log("读屏失败，采集中止。可稍后重新开始（已采内容不会丢）。")
                    break

                joined = "\n".join(lines)
                hit_risk = [kw for kw in RISK_KEYWORDS if kw in joined]
                if hit_risk:
                    self.log("⚠️ 检测到风控提示（%s）！已自动停止。"
                             "请先在微信里完成验证/稍后再试，切勿强行继续。" % hit_risk[0])
                    self.stop_event.set()
                    return False

                posts = split_posts(lines)
                new = 0
                for t_raw, content in posts:
                    if db.add_post(self.friend_name, t_raw, content):
                        new += 1
                total_new += new

                sig = tuple(lines)
                if new:
                    no_new = 0
                    self.log("第 %d 屏：识别 %d 条，新增 %d 条，累计新增 %d 条。"
                             % (scrolls + 1, len(posts), new, total_new))
                else:
                    no_new += 1
                    self.log("第 %d 屏：无新内容（%d/%d）……"
                             % (scrolls + 1, no_new, NO_NEW_LIMIT))

                if no_new >= NO_NEW_LIMIT:
                    self.log("连续 %d 屏没有新内容，判定已翻到底，采集结束。" % NO_NEW_LIMIT)
                    break

                scrolls += 1
                if sig == prev_sig and not fallback_used:
                    # 后台滚轮后画面完全没动：改用 PageDown 备用滚动
                    fallback_used = True
                    self.log("后台滚轮未见画面变化，改用 PageDown 备用方式滚动……")
                    windows.page_down_background(hwnd, times=3)
                else:
                    if sig != prev_sig:
                        fallback_used = False
                    self._scroll_down(hwnd)
                prev_sig = sig

                if scrolls % REST_EVERY == 0:
                    rest = random.uniform(6, 12)
                    self.log("短暂休息 %.0f 秒……" % rest)
                    self._sleep(rest)
                else:
                    self._sleep(random.uniform(0.4, 0.8))
        except Exception as e:
            self.log("采集异常：%s" % e)
            return False

        total = db.post_count(self.friend_name)
        if self.stop_event.is_set() and no_new < NO_NEW_LIMIT:
            self.log("已手动停止。本次新增 %d 条；该好友库内共 %d 条（下次继续不重复）。"
                     % (total_new, total))
        else:
            self.log("采集完成。本次新增 %d 条；该好友库内共 %d 条。" % (total_new, total))
        return True