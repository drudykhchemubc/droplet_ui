import math
import re
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from animated_tab_design import PillToggle, _rounded_rect
from cnc_hardware import cnc_query

AXES = ('X', 'Y', 'Z')
STEP_SETS = {'fine': (0.1, 1.0), 'coarse': (1.0, 10.0)}
_SETTING_RE = re.compile(r'^\$(\d+)=([-+\d.]+)')
_F = 'Segoe UI'

# blue tints of the app accent (#007AFF)
_OUTER, _INNER, _HOVER = '#E6F0FF', '#CCE0FF', '#B3D1FF'
_CENTER_HOVER = '#0066DD'


def _fmt(v):
    return f"{v:g}"


def _dpi_factor(widget):
    """Sizes below are in 96-DPI pixels; match the font scaling main.py applies."""
    return max(1.0, float(widget.tk.call('tk', 'scaling')) / (96 / 72))


class CncLink:
    """Sends GRBL commands on a worker thread, one batch at a time, so the UI
    never blocks on the serial port."""

    def __init__(self, get_cnc, log_cb, is_busy):
        self._get_cnc = get_cnc
        self._log = log_cb
        self._is_busy = is_busy
        self._lock = threading.Lock()

    def send(self, widget, commands, done=None, quiet=False):
        cnc = self._get_cnc()
        if cnc is None:
            if not quiet:
                messagebox.showerror("Error", "CNC not connected.", parent=widget)
            return
        if self._is_busy():
            if not quiet:
                messagebox.showerror("Error", "The CNC cannot be moved while a run is in progress.",
                                     parent=widget)
            return

        def worker():
            results = []
            with self._lock:
                try:
                    for cmd in commands:
                        results.append(cnc_query(cnc, cmd, self._log))
                except Exception as e:
                    self._log(f"CNC error: {e}")
                    return
            if done:
                widget.after(0, done, results)

        threading.Thread(target=worker, daemon=True).start()


class JogPad(tk.Canvas):
    """Round X/Y jog pad in the Universal G-code Sender style: inner ring jogs the
    small step, outer ring the large step, centre button returns to the origin."""

    _R_OUT, _R_IN, _R_C, _GAP = 112, 70, 28, 8
    # (axis, sign, arc start angle) — tk arcs run counter-clockwise from 3 o'clock
    _SECTORS = (('Y', 1, 45), ('X', -1, 135), ('Y', -1, 225), ('X', 1, 315))

    def __init__(self, parent, C, on_jog, on_home, **kw):
        k = _dpi_factor(parent)
        self._R_OUT, self._R_IN, self._R_C, self._GAP = (
            v * k for v in (self._R_OUT, self._R_IN, self._R_C, self._GAP))
        self._k = k
        size = 2 * self._R_OUT + 4
        super().__init__(parent, width=size, height=size, bg=C['surface'],
                         highlightthickness=0, bd=0, **kw)
        self._C = C
        self._on_jog = on_jog
        self._on_home = on_home
        self._c = size / 2
        self._steps = STEP_SETS['coarse']
        self._hover = None
        self.bind('<Motion>', lambda e: self._set_hover(self._hit(e.x, e.y)))
        self.bind('<Leave>', lambda _e: self._set_hover(None))
        self.bind('<Button-1>', self._on_click)
        self._draw()

    def set_steps(self, small, large):
        self._steps = (small, large)
        self._draw()

    def _hit(self, x, y):
        """Return ('home',) or (axis, sign, ring) for a canvas point, else None."""
        dx, dy = x - self._c, self._c - y
        r = math.hypot(dx, dy)
        if r <= self._R_C:
            return ('home',)
        if r > self._R_OUT:
            return None
        if min(abs(dx - dy), abs(dx + dy)) / math.sqrt(2) < self._GAP / 2:
            return None                       # in the white gap between sectors
        ang = math.degrees(math.atan2(dy, dx)) % 360
        axis, sign, _ = self._SECTORS[int(((ang - 45) % 360) // 90)]
        return (axis, sign, 0 if r <= self._R_IN else 1)

    def _polar(self, r, deg):
        a = math.radians(deg)
        return self._c + r * math.cos(a), self._c - r * math.sin(a)

    def _draw(self):
        C, c = self._C, self._c
        self.delete('all')
        for ring, radius, base in ((1, self._R_OUT, _OUTER), (0, self._R_IN, _INNER)):
            for axis, sign, start in self._SECTORS:
                fill = _HOVER if (axis, sign, ring) == self._hover else base
                self.create_arc(c - radius, c - radius, c + radius, c + radius,
                                start=start, extent=90, style='pieslice',
                                fill=fill, outline='')
        for deg in (45, 135):                 # white gaps between the four sectors
            self.create_line(*self._polar(self._R_OUT + 2, deg),
                             *self._polar(self._R_OUT + 2, deg + 180),
                             fill=C['surface'], width=self._GAP)

        # axis names in the outer ring
        r_out_mid = (self._R_IN + self._R_OUT) / 2
        for axis, sign, start in self._SECTORS:
            self.create_text(*self._polar(r_out_mid, start + 45),
                             text=f"{'' if sign > 0 else '-'}{axis}",
                             fill=C['accent'], font=(_F, 11, 'bold'))
        # step sizes beside the diagonal gap, as in UGS: + on the upper right, − on the
        # lower left. Text runs parallel to the gap, offset just clear of it so it stays
        # inside its sector.
        small, large = self._steps
        r_in_mid = (self._R_C + self._R_IN) / 2
        off = self._GAP / 2 + 8 * self._k     # gap half-width + half the text height
        for diag, side, sign in ((45, -1, '+'), (225, 1, '-')):
            for r, v in ((r_out_mid, large), (r_in_mid, small)):
                deg = diag + side * math.degrees(math.atan2(off, r))
                self.create_text(*self._polar(math.hypot(r, off), deg),
                                 text=f"{sign}{_fmt(v)}", angle=45,
                                 fill=C['accent'], font=(_F, 9))

        fill = _CENTER_HOVER if self._hover == ('home',) else C['accent']
        self.create_oval(c - self._R_C, c - self._R_C, c + self._R_C, c + self._R_C,
                         fill=fill, outline='')
        h = 11 * self._k                      # house icon
        self.create_polygon(c - h, c - 1, c, c - h, c + h, c - 1,
                            c + h * 0.7, c - 1, c + h * 0.7, c + h * 0.9,
                            c + h * 0.25, c + h * 0.9, c + h * 0.25, c + h * 0.3,
                            c - h * 0.25, c + h * 0.3, c - h * 0.25, c + h * 0.9,
                            c - h * 0.7, c + h * 0.9, c - h * 0.7, c - 1,
                            fill='#FFFFFF', outline='#FFFFFF', joinstyle='round')

    def _set_hover(self, key):
        if key != self._hover:
            self._hover = key
            self.config(cursor='hand2' if key else '')
            self._draw()

    def _on_click(self, e):
        key = self._hit(e.x, e.y)
        if key == ('home',):
            self._on_home()
        elif key:
            axis, sign, ring = key
            self._on_jog(axis, sign * self._steps[ring])


class ZBar(tk.Canvas):
    """Vertical Z jog bar styled to match JogPad: +large, +small, −small, −large."""

    _WIDTH = 58
    _SEGMENTS = ((1, 1), (1, 0), (-1, 0), (-1, 1))   # (sign, ring) top to bottom

    def __init__(self, parent, C, height, on_jog, **kw):
        k = _dpi_factor(parent)
        self._bw, self._bh, self._gap = self._WIDTH * k, height, 8 * k
        super().__init__(parent, width=self._bw, height=self._bh, bg=C['surface'],
                         highlightthickness=0, bd=0, **kw)
        self._C = C
        self._on_jog = on_jog
        self._steps = STEP_SETS['coarse']
        self._hover = None
        self.bind('<Motion>', lambda e: self._set_hover(self._hit(e.y)))
        self.bind('<Leave>', lambda _e: self._set_hover(None))
        self.bind('<Button-1>', self._on_click)
        self._draw()

    def set_steps(self, small, large):
        self._steps = (small, large)
        self._draw()

    def _hit(self, y):
        i = int(y // (self._bh / 4))
        return i if 0 <= i < 4 else None

    def _draw(self):
        C, w, h = self._C, self._bw, self._bh
        q = h / 4
        self.delete('all')
        fills = [_HOVER if i == self._hover else (_OUTER if ring else _INNER)
                 for i, (_sign, ring) in enumerate(self._SEGMENTS)]
        # rounded capsule ends, then the two square middle segments drawn over them
        _rounded_rect(self, 0, 0, w, 2 * q, w / 2, fill=fills[0], outline='')
        _rounded_rect(self, 0, 2 * q, w, h, w / 2, fill=fills[3], outline='')
        self.create_rectangle(0, q, w, 2 * q, fill=fills[1], outline='')
        self.create_rectangle(0, 2 * q, w, 3 * q, fill=fills[2], outline='')
        for i in (1, 3):
            self.create_line(0, i * q, w, i * q, fill=C['surface'], width=self._gap)
        self.create_line(0, 2 * q, w, 2 * q, fill=C['surface'], width=self._gap / 2)
        for i, (sign, ring) in enumerate(self._SEGMENTS):
            s = '+' if sign > 0 else '-'
            if ring:
                self.create_text(w / 2, (i + 0.5) * q, text=f"{'' if sign > 0 else '-'}Z",
                                 fill=C['accent'], font=(_F, 11, 'bold'))
            else:
                self.create_text(w / 2, (i + 0.5) * q, text=f"{s}{_fmt(self._steps[0])}",
                                 fill=C['accent'], font=(_F, 9))
        # large-step values under/over the Z labels
        for i, s in ((0, '+'), (3, '-')):
            self.create_text(w / 2, (i + 0.5) * q + (14 if i == 0 else -14) * _dpi_factor(self),
                             text=f"{s}{_fmt(self._steps[1])}", fill=C['accent'], font=(_F, 9))

    def _set_hover(self, i):
        if i != self._hover:
            self._hover = i
            self.config(cursor='hand2' if i is not None else '')
            self._draw()

    def _on_click(self, e):
        i = self._hit(e.y)
        if i is not None:
            sign, ring = self._SEGMENTS[i]
            self._on_jog('Z', sign * self._steps[ring])


class JogControls(tk.Frame):
    """X/Y pad, Z bar, step size and jog speed."""

    def __init__(self, parent, C, link):
        super().__init__(parent, bg=C['surface'])
        self._link = link
        self._step_var = tk.StringVar(value='coarse')
        self._feed_var = tk.IntVar(value=1000)

        self._pad = JogPad(self, C, self.jog, self.go_home)
        self._pad.grid(row=0, column=0)
        self._zbar = ZBar(self, C, int(self._pad['height']), self.jog)
        self._zbar.grid(row=0, column=1, padx=(16, 0))

        # settings column beside the pads; the app adds its own buttons below (row 2+)
        opts = self.options = tk.Frame(self, bg=C['surface'])
        opts.grid(row=0, column=2, sticky='n', padx=(24, 0))
        ttk.Label(opts, text="Step (mm)", style='Card.TLabel').grid(
            row=0, column=0, sticky='w', padx=(0, 10), pady=3)
        PillToggle(opts, C, [("0.1 / 1", 'fine'), ("1 / 10", 'coarse')], self._step_var,
                   bg=C['surface']).grid(row=0, column=1, sticky='w', pady=3)
        ttk.Label(opts, text="Jog Speed (mm/min)", style='Card.TLabel').grid(
            row=1, column=0, sticky='w', padx=(0, 10), pady=3)
        ttk.Entry(opts, textvariable=self._feed_var, width=8).grid(
            row=1, column=1, sticky='w', pady=3)

        self._step_var.trace_add('write', lambda *_: self._on_step_change())
        self._on_step_change()

    def small_step(self):
        return STEP_SETS[self._step_var.get()][0]

    def _on_step_change(self):
        small, large = STEP_SETS[self._step_var.get()]
        self._pad.set_steps(small, large)
        self._zbar.set_steps(small, large)

    def _feed(self):
        try:
            return max(1, int(self._feed_var.get()))
        except (tk.TclError, ValueError):
            return 1000

    def jog(self, axis, delta):
        self._link.send(self, [f"$J=G91 G21 {axis}{delta:.3f} F{self._feed()}"])

    def go_home(self):
        f = self._feed()
        self._link.send(self, [f"$J=G90 G21 Z0 F{f}", f"$J=G90 G21 X0 Y0 F{f}"])


class MotorWiringDialog(tk.Toplevel):
    """UGS-style motor wiring check: jog each axis, and flip GRBL's direction
    mask ($3) for any axis that moves the wrong way."""

    def __init__(self, parent, C, link, jog):
        super().__init__(parent)
        self._link = link
        self._jog = jog
        self.title("Calibration")
        self.configure(bg=C['bg'])
        self.resizable(False, False)
        self.transient(parent)

        s = ttk.Style()
        s.configure('Card.TCheckbutton', background=C['surface'], foreground=C['text'],
                    font=(_F, 10))
        s.configure('Outline.TButton', background=C['surface'], foreground=C['accent'],
                    font=(_F, 10, 'bold'), padding=(10, 5), relief='solid', borderwidth=1,
                    bordercolor=C['accent'], lightcolor=C['accent'], darkcolor=C['accent'])
        s.map('Outline.TButton',
              background=[('active', _OUTER), ('pressed', _INNER)])

        outer = ttk.Frame(self, padding=(16, 12))
        outer.pack(fill='both', expand=True)
        card = ttk.Frame(outer, style='Surface.TFrame', padding=(14, 12))
        card.pack(fill='x')

        ttk.Label(card, style='Muted.TLabel', justify='left', wraplength=int(380 * _dpi_factor(self)),
                  text="Test that each motor is wired correctly. Jog each axis with the "
                       "buttons below. If an axis moves in the wrong direction, select "
                       "Reverse Direction for that axis.").pack(anchor='w', pady=(0, 10))

        self._reverse_vars = {a: tk.BooleanVar() for a in AXES}
        grid = ttk.Frame(card, style='Surface.TFrame')
        grid.pack(anchor='w')
        for r, a in enumerate(AXES):
            for c, sign in enumerate((-1, 1)):
                ttk.Button(grid, text=f"{a}{'-' if sign < 0 else '+'}", width=4,
                           style='Outline.TButton',
                           command=lambda ax=a, sg=sign: self._jog.jog(ax, sg * self._jog.small_step())
                           ).grid(row=r, column=c, padx=(0, 8), pady=4)
            ttk.Checkbutton(grid, text="Reverse Direction", style='Card.TCheckbutton',
                            variable=self._reverse_vars[a],
                            command=self._apply_reverse).grid(row=r, column=2, padx=(8, 0))

        foot = ttk.Frame(outer)
        foot.pack(fill='x', pady=(12, 0))
        ttk.Button(foot, text="Reload from Controller", style='Ghost.TButton',
                   command=self.read_settings).pack(side='left')
        ttk.Button(foot, text="Close", style='Accent.TButton',
                   command=self.destroy).pack(side='right')

        self.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width() - self.winfo_width()) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 3
        self.geometry(f'+{px}+{py}')
        self.read_settings(quiet=True)

    def read_settings(self, quiet=False):
        self._link.send(self, ['$$'], done=lambda r: self._on_settings(r[0]), quiet=quiet)

    def _on_settings(self, lines):
        settings = {int(m.group(1)): float(m.group(2))
                    for m in map(_SETTING_RE.match, lines) if m}
        if 3 not in settings or not self.winfo_exists():
            return
        mask = int(settings[3])
        for i, a in enumerate(AXES):
            self._reverse_vars[a].set(bool(mask & (1 << i)))

    def _apply_reverse(self):
        mask = sum(1 << i for i, a in enumerate(AXES) if self._reverse_vars[a].get())
        self._link.send(self, [f"$3={mask}"])
