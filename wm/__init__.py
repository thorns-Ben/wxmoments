# -*- coding: utf-8 -*-
"""朋友圈采集与搜索工具。
包导入时先加载项目内 libs 目录（如果存在），实现绿色便携：
依赖既可以全局安装，也可以放在本项目 libs 目录里。"""
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_LIBS = os.path.join(_ROOT, "libs")
if os.path.isdir(_LIBS):
    sys.path.insert(0, _LIBS)
    # 兼容 --target 方式安装的 pywin32（复制 pywin32.pth 的效果）
    for sub in ("win32", os.path.join("win32", "lib"), "Pythonwin", "pywin32_system32"):
        p = os.path.join(_LIBS, sub)
        if os.path.isdir(p) and p not in sys.path:
            sys.path.append(p)
    _sys32 = os.path.join(_LIBS, "pywin32_system32")
    if os.path.isdir(_sys32):
        try:
            os.add_dll_directory(_sys32)
        except Exception:
            pass

# 进程级 DPI 感知：保证窗口坐标/截图在缩放屏上按物理像素对齐
try:
    import ctypes
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)      # PER_MONITOR_AWARE
    except Exception:
        ctypes.windll.user32.SetProcessDPIAware()
except Exception:
    pass