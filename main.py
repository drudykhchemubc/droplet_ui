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

    # Per-monitor DPI awareness (above) stops Windows from auto-scaling the
    # window, but Tk still assumes a 96-DPI screen unless told otherwise. On
    # displays with a higher Windows scaling setting (common on smaller/high-
    # res laptops), that mismatch makes every widget render tiny relative to
    # the screen. Query the real DPI and rescale Tk's fonts/geometry to match.
    try:
        dpi = ctypes.windll.user32.GetDpiForSystem()
        root.tk.call('tk', 'scaling', dpi / 72.0)
    except Exception:
        pass

    app = MicrodropletApp(root)
    root.mainloop()
