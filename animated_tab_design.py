import tkinter as tk
import tkinter.font as tkfont


class SmoothNotebook(tk.Frame):
    """Notebook with a pill indicator that slides smoothly between tabs."""
    _STEPS = 12
    _MS = 14          # 170 ms total

    def __init__(self, parent, C, **kw):
        super().__init__(parent, bg=C['bg'], **kw)
        self._C = C
        self._pages = []      # [(label, frame), ...]
        self._positions = []  # [(x0, x1), ...]
        self._current = 0
        self._pill_x = 8.0
        self._pill_w = 0.0
        self._anim_job = None
        self._BAR_H = 44
        self._PAD_Y = 6

        self._font = tkfont.Font(family='Segoe UI', size=10)
        self._font_bold = tkfont.Font(family='Segoe UI', size=10, weight='bold')
        self._TAB_PAD = 22    # horizontal padding each side of label

        self._bar = tk.Canvas(self, bg=C['fill'], height=self._BAR_H,
                              highlightthickness=0, bd=0)
        self._bar.pack(fill=tk.X, side=tk.TOP)
        self._bar.bind('<Configure>', lambda _e: self._draw())

        tk.Frame(self, bg=C['border'], height=1).pack(fill=tk.X, side=tk.TOP)

        self._body = tk.Frame(self, bg=C['bg'])
        self._body.pack(fill=tk.BOTH, expand=True)

    def add(self, frame, text=''):
        idx = len(self._pages)
        self._pages.append((text, frame))
        frame.place(x=0, y=0, relwidth=1, relheight=1)
        if idx == 0:
            frame.lift()
        else:
            frame.lower()
        self._positions = self._calc_positions()
        if idx == 0 and self._positions:
            self._pill_x = self._positions[0][0]
            self._pill_w = self._positions[0][1] - self._positions[0][0]
        self._draw()

    def _calc_positions(self):
        x = 8
        out = []
        for label, _ in self._pages:
            w = self._font_bold.measure(label) + self._TAB_PAD * 2
            out.append((x, x + w))
            x += w + 6
        return out

    def _rounded_rect(self, x0, y0, x1, y1, r, **kw):
        r = max(1, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
        pts = [
            x0+r, y0,   x1-r, y0,
            x1,   y0,   x1,   y0+r,
            x1,   y1-r, x1,   y1,
            x1-r, y1,   x0+r, y1,
            x0,   y1,   x0,   y1-r,
            x0,   y0+r, x0,   y0,
            x0+r, y0,
        ]
        return self._bar.create_polygon(pts, smooth=True, **kw)

    def _draw(self):
        C = self._C
        self._bar.delete('all')
        if not self._pages or not self._positions:
            return
        h = self._BAR_H
        py = self._PAD_Y
        r = (h - 2 * py) // 2

        self._rounded_rect(self._pill_x + 0, py + 1,
                           self._pill_x + self._pill_w + 0, h - py + 1,
                           r, fill='#C8C8CC', outline='', tags='shadow')
        self._rounded_rect(self._pill_x, py,
                           self._pill_x + self._pill_w, h - py,
                           r, fill=C['surface'], outline='', tags='pill')

        for i, (label, _) in enumerate(self._pages):
            x0, x1 = self._positions[i]
            tag = f'_tab{i}'
            self._bar.create_text(
                (x0 + x1) / 2, h / 2,
                text=label,
                fill=C['accent'] if i == self._current else C['text2'],
                font=self._font_bold if i == self._current else self._font,
                tags=tag,
            )
            self._bar.tag_bind(tag, '<Button-1>', lambda _e, n=i: self._select(n))
            self._bar.tag_bind(tag, '<Enter>',
                               lambda _e: self._bar.config(cursor='hand2'))
            self._bar.tag_bind(tag, '<Leave>',
                               lambda _e: self._bar.config(cursor=''))

    def _select(self, idx):
        if idx == self._current:
            return
        if self._anim_job:
            self.after_cancel(self._anim_job)
        sx, sw = self._pill_x, self._pill_w
        self._current = idx
        self._pages[idx][1].lift()
        self._positions = self._calc_positions()
        tx = self._positions[idx][0]
        tw = self._positions[idx][1] - tx
        self._draw()
        self._animate(sx, sw, tx, tw, self._STEPS)

    def _animate(self, sx, sw, tx, tw, n):
        if n <= 0:
            self._pill_x, self._pill_w = tx, tw
            self._draw()
            return
        t = 1.0 - n / self._STEPS
        e = 1 - (1 - t) ** 3               # ease-out cubic
        self._pill_x = sx + (tx - sx) * e
        self._pill_w = sw + (tw - sw) * e
        self._draw()
        self._anim_job = self.after(
            self._MS, self._animate, sx, sw, tx, tw, n - 1)
