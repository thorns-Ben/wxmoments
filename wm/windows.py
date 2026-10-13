# -*- coding: utf-8 -*-
"""定位电脑版微信窗口。

兼容两代微信：
· 3.x 老版：进程 WeChat.exe，朋友圈独立窗口标题含“朋友圈”；
· 4.x 新版（2025 起）：主进程 Weixin.exe，朋友圈/小程序/视频号等内容
  跑在独立的 WeChatAppEx.exe（CEF 内核）里，且朋友圈窗口的 Win32 标题
  为空——“朋友圈”三个字画在网页内容里，不能再按标题找。

定位优先级：前台微信窗口 > 标题含“朋友圈”的窗口 > WeChatAppEx 内容窗口
（最大的一个）> 最大的微信窗口。
"""
import ctypes
from ctypes import wintypes

import win32gui
import win32process

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_DWMWA_CLOAKED = 14

# 微信相关进程名（小写）
_WECHAT_EXES = {"wechat.exe", "weixin.exe", "wechatappex.exe"}
# 4.x 安装/插件目录特征（兜底匹配）
_WECHAT_PATH_KEYS = ("xwechat",)

# 辅助窗口标题（不是内容窗口）
_BAD_TITLES = {
    "Default IME", "MSCTFIME UI", "CandidateWindow", "Mode Indicator",
    "WxTrayIconMessageWindow", "GDI+ Hook Window",
}

_MIN_W = 300   # 内容窗口最小宽
_MIN_H = 300   # 内容窗口最小高


def _process_path_of_pid(pid):
    try:
        h = ctypes.windll.kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                return buf.value
        finally:
            ctypes.windll.kernel32.CloseHandle(h)
    except Exception:
        pass
    return ""


def _is_wechat_process(path):
    p = (path or "").lower()
    base = p.rsplit("\\", 1)[-1]
    return base in _WECHAT_EXES or any(k in p for k in _WECHAT_PATH_KEYS)


def _is_cloaked(hwnd):
    """DWM 隐藏窗口（如切换到其他虚拟桌面、最小化到任务视图的窗口）。"""
    val = wintypes.DWORD(0)
    try:
        ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd, _DWMWA_CLOAKED, ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        return False
    return bool(val.value)


def _is_content_window(hwnd, title, rect):
    l, t, r, b = rect
    if l <= -10000 or t <= -10000:          # 最小化（坐标约 -32000）
        return False
    if (r - l) < _MIN_W or (b - t) < _MIN_H:
        return False
    if title in _BAD_TITLES:
        return False
    try:
        if not win32gui.IsWindowVisible(hwnd):   # 隐藏的后台窗口
            return False
    except Exception:
        pass
    if _is_cloaked(hwnd):
        return False
    return True


def _window_info(hwnd, path):
    return {
        "hwnd": hwnd,
        "title": win32gui.GetWindowText(hwnd),
        "rect": win32gui.GetWindowRect(hwnd),
        "pid": win32process.GetWindowThreadProcessId(hwnd)[1],
        "exe": path.rsplit("\\", 1)[-1],
        "exe_path": path,
    }


def list_wechat_windows():
    """返回所有微信内容窗口：[{hwnd,title,rect,pid,exe,exe_path}]。

    4.x 朋友圈窗口标题为空，靠进程名 + 窗口区域判定。
    """
    result = []
    seen = set()

    def _cb(hwnd, _):
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        path = _process_path_of_pid(pid)
        if not _is_wechat_process(path):
            return
        title = win32gui.GetWindowText(hwnd)
        rect = win32gui.GetWindowRect(hwnd)
        if not _is_content_window(hwnd, title, rect):
            return
        if hwnd in seen:
            return
        seen.add(hwnd)
        result.append(_window_info(hwnd, path))

    win32gui.EnumWindows(_cb, None)
    return result


def _area(w):
    l, t, r, b = w["rect"]
    return (r - l) * (b - t)


def find_moments_window():
    """朋友圈窗口：3.x 标题含“朋友圈”；4.x 取 WeChatAppEx 最大的内容窗口。"""
    wins = list_wechat_windows()
    for w in wins:
        if "朋友圈" in (w["title"] or ""):
            return w
    appex = [w for w in wins if w["exe"].lower() == "wechatappex.exe"]
    if appex:
        return max(appex, key=_area)
    return None


def find_foreground_wechat():
    """前台窗口属于微信进程则返回它（用户把朋友圈窗口置于最前时最可靠）。"""
    hwnd = win32gui.GetForegroundWindow()
    if not hwnd:
        return None
    _, pid = win32process.GetWindowThreadProcessId(hwnd)
    path = _process_path_of_pid(pid)
    if not _is_wechat_process(path):
        return None
    info = _window_info(hwnd, path)
    if not _is_content_window(hwnd, info["title"], info["rect"]):
        return None
    return info


def get_rect(hwnd):
    """返回窗口当前区域 (l,t,r,b)；最小化/无效时返回 None。"""
    try:
        l, t, r, b = win32gui.GetWindowRect(hwnd)
    except Exception:
        return None
    if l <= -10000 or t <= -10000 or (r - l) < _MIN_W or (b - t) < _MIN_H:
        return None
    try:
        if not win32gui.IsWindowVisible(hwnd):
            return None
    except Exception:
        return None
    return (l, t, r, b)


def raise_window(hwnd):
    """恢复并置前窗口。用 AttachThreadInput 绕过 SetForegroundWindow 的焦点锁。
    失败不抛异常（返回 False），调用方只需提示用户手动置前即可。"""
    try:
        import win32api
        import win32con
        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        cur_tid = ctypes.windll.kernel32.GetCurrentThreadId()
        fg = win32gui.GetForegroundWindow()
        fg_tid = win32process.GetWindowThreadProcessId(fg)[0]
        tgt_tid = win32process.GetWindowThreadProcessId(hwnd)[0]
        attached = []
        try:
            for other in (fg_tid, tgt_tid):
                if other and other != cur_tid:
                    try:
                        win32process.AttachThreadInput(cur_tid, other, True)
                        attached.append(other)
                    except Exception:
                        pass
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        finally:
            for other in attached:
                try:
                    win32process.AttachThreadInput(cur_tid, other, False)
                except Exception:
                    pass
        return True
    except Exception:
        return False


def pick_target_window():
    """采集目标：前台微信窗口 > 标题含“朋友圈” > WeChatAppEx 内容窗口 > 最大微信窗口。
    返回 (窗口信息或None, 说明文字)。"""
    fg = find_foreground_wechat()
    if fg:
        return fg, ("已锁定最前面的微信窗口（进程 %s）。请确认它正显示着目标好友的朋友圈相册。"
                    % fg["exe"])

    wins = list_wechat_windows()
    if not wins:
        return None, ("没有找到微信窗口。请先登录电脑版微信（建议 4.0.3 以上），"
                      "打开目标好友的朋友圈相册页，并让该窗口显示在最前面。")

    titled = [w for w in wins if "朋友圈" in (w["title"] or "")]
    if titled:
        w = max(titled, key=_area)
        return w, "已定位到朋友圈窗口：%r" % w["title"]

    appex = [w for w in wins if w["exe"].lower() == "wechatappex.exe"]
    if appex:
        w = max(appex, key=_area)
        return w, ("已定位到微信内容窗口（进程 %s，4.x 朋友圈就开在这里）。"
                   "请确认它正显示着目标好友的朋友圈相册。" % w["exe"])

    w = max(wins, key=_area)
    return w, ("未找到独立的朋友圈窗口，将使用最大的微信窗口（进程 %s，标题 %r）。"
               "请让朋友圈相册页显示在最前面后再试。" % (w["exe"], w["title"]))


# ---------- 后台截图 / 后台滚动（不动鼠标、不需要前台） ----------

import time as _time

_PW_RENDERFULLCONTENT = 0x02   # PrintWindow：要求窗口自行渲染完整内容（含被遮挡部分）
_WM_MOUSEWHEEL = 0x020A
_WM_KEYDOWN = 0x0100
_WM_KEYUP = 0x0101
_VK_NEXT = 0x22                # Page Down
_WHEEL_DELTA = 120


def _pack_lparam(lo, hi):
    return (int(lo) & 0xFFFF) | ((int(hi) & 0xFFFF) << 16)


def capture_window(hwnd):
    """后台截图：用 PrintWindow 让窗口把自己渲染进位图，
    即使被其他窗口完全遮挡也能截到内容（最小化除外）。
    返回客户区 PIL.Image；失败（最小化/渲染空白）返回 None。"""
    try:
        import numpy as np
        import win32ui
        from PIL import Image
        l, t, r, b = win32gui.GetWindowRect(hwnd)
        _cl, _ct, cw, ch = win32gui.GetClientRect(hwnd)
        if cw <= 0 or ch <= 0 or (r - l) <= 0 or (b - t) <= 0:
            return None
        hdc_win = win32gui.GetWindowDC(hwnd)
        src = win32ui.CreateDCFromHandle(hdc_win)
        dst = src.CreateCompatibleDC()
        bmp = win32ui.CreateBitmap()
        bmp.CreateCompatibleBitmap(src, r - l, b - t)
        dst.SelectObject(bmp)
        ok = ctypes.windll.user32.PrintWindow(hwnd, dst.GetSafeHdc(),
                                              _PW_RENDERFULLCONTENT)
        info = bmp.GetInfo()
        arr = np.frombuffer(bmp.GetBitmapBits(True), dtype=np.uint8)
        arr = arr.reshape(info["bmHeight"], info["bmWidth"], 4)[:, :, :3].copy()
        win32gui.DeleteObject(bmp.GetHandle())
        dst.DeleteDC()
        src.DeleteDC()
        win32gui.ReleaseDC(hwnd, hdc_win)
        if not ok:
            return None
        # 裁出客户区（去掉标题栏/边框），坐标换算到窗口位图
        cl, ct = win32gui.ClientToScreen(hwnd, (0, 0))
        ox, oy = cl - l, ct - t
        client = arr[oy:oy + ch, ox:ox + cw]
        if client.size == 0:
            return None
        # 全黑/全白/无内容判定（最小化或渲染失败时几乎是纯色）
        if float(client.std()) < 6:
            return None
        return Image.fromarray(client)
    except Exception:
        return None


# 滚动消息接收方优先级：
# 微信 4.x 的朋友圈内容是嵌入 Weixin.exe 的原生子窗（Qt 框架 + MMUI 渲染面），
# 滚轮/按键必须发给它；Chrome 的 D3D/RenderWidget 外壳不响应后台消息。
_SCROLL_TARGET_PREFS = ("Qt515", "Qt", "MMUIRender", "RenderWidget")


def _find_render_child(hwnd):
    """找真正响应滚动消息的子窗口（含跨进程嵌入的子窗），找不到返回 None。"""
    children = []

    def _cb(ch, _):
        try:
            cls = win32gui.GetClassName(ch)
            r = win32gui.GetWindowRect(ch)
        except Exception:
            return True
        if (r[2] - r[0]) > 100 and (r[3] - r[1]) > 100:
            children.append((ch, cls, r))
        return True

    try:
        win32gui.EnumChildWindows(hwnd, _cb, None)
    except Exception:
        return None
    if not children:
        return None
    for pref in _SCROLL_TARGET_PREFS:
        hits = [c for c in children if pref in c[1]]
        if hits:
            return max(hits, key=lambda c: (c[2][2] - c[2][0]) * (c[2][3] - c[2][1]))[0]
    return max(children, key=lambda c: (c[2][2] - c[2][0]) * (c[2][3] - c[2][1]))[0]


def scroll_background(hwnd, ticks=6, notch_delay=0.08):
    """后台向下滚动：向渲染窗口投递 WM_MOUSEWHEEL。
    不移动真实鼠标、不抢焦点、窗口被遮挡也能滚。返回消息接收窗口句柄。"""
    target = _find_render_child(hwnd) or hwnd
    l, t, r, b = win32gui.GetWindowRect(target)
    x = (l + r) // 2
    y = t + (b - t) // 2 + (b - t) // 8   # 落在内容区，避开顶部工具栏
    lparam = _pack_lparam(x, y)           # WM_MOUSEWHEEL 用屏幕坐标
    wparam = ((-_WHEEL_DELTA) & 0xFFFF) << 16   # 低位按键状态=0，高位滚轮量=-120
    for _ in range(ticks):
        win32gui.PostMessage(target, _WM_MOUSEWHEEL, wparam, lparam)
        _time.sleep(notch_delay)
    return target


def page_down_background(hwnd, times=2):
    """后台备用滚动：投递 PageDown 按键消息（滚轮消息不生效时用）。"""
    target = _find_render_child(hwnd) or hwnd
    for _ in range(times):
        win32gui.PostMessage(target, _WM_KEYDOWN, _VK_NEXT, 0)
        _time.sleep(0.05)
        win32gui.PostMessage(target, _WM_KEYUP, _VK_NEXT, 0)
        _time.sleep(0.15)
