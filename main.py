#!/usr/bin/env python3

import ctypes
try:                                          # Fix blurry/pixelated UI on high-DPI Windows
    ctypes.windll.shcore.SetProcessDpiAwareness(2)   # per-monitor DPI aware
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

import tkinter as tk
from app_gui import MicrodropletApp

if __name__ == '__main__':
    root = tk.Tk()
    app = MicrodropletApp(root)
    root.mainloop()
