import hashlib
import json
import os
import string
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

import pandas as pd

PLATE_DEFAULTS = {
    '6':   {'rows': 2,  'cols': 3,  'spacing': 35.0},
    '12':  {'rows': 3,  'cols': 4,  'spacing': 26.0},
    '24':  {'rows': 4,  'cols': 6,  'spacing': 19.3},
    '48':  {'rows': 6,  'cols': 8,  'spacing': 13.0},
    '96':  {'rows': 8,  'cols': 12, 'spacing':  9.0},
    '384': {'rows': 16, 'cols': 24, 'spacing':  4.5},
}

_CLASS_COLORS = {
    'pfd': '#4A90D9', 'perfluorodecalin': '#4A90D9', 'oil': '#4A90D9',
    'organic': '#E8A838',
    'trace': '#7BC67E', 'mark': '#7BC67E',
    'wash': '#C678DD', 'rinse': '#C678DD',
}

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'microdroplet_config.json')


def _darken(hex_color, amount=0.10):
    """Return a slightly darker version of a hex color string."""
    h = hex_color.lstrip('#')
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    r = max(0, int(r * (1 - amount)))
    g = max(0, int(g * (1 - amount)))
    b = max(0, int(b * (1 - amount)))
    return f'#{r:02x}{g:02x}{b:02x}'


def _class_color(cls_str):
    cls = (cls_str or '').lower().strip()
    for key, col in _CLASS_COLORS.items():
        if key in cls:
            return col
    if cls:
        h = int(hashlib.md5(cls.encode()).hexdigest()[:6], 16)
        return f'#{(h>>16)&0xFF:02x}{(h>>8)&0xFF:02x}{h&0xFF:02x}'
    return None


def _load_presets():
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH) as f:
                d = json.load(f)
            pp = d.get('plate_presets', {})
            return pp.get('geometry', {}), pp.get('reactions', {})
        except Exception:
            pass
    return {}, {}


def _save_presets(geo, rxn):
    try:
        existing = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH) as f:
                existing = json.load(f)
        existing['plate_presets'] = {'geometry': geo, 'reactions': rxn}
        with open(CONFIG_PATH, 'w') as f:
            json.dump(existing, f, indent=2)
    except Exception:
        pass


class _WellDialog(tk.Toplevel):
    """Modal dialog to assign or clear a single well."""

    def __init__(self, parent, well_name, data):
        super().__init__(parent)
        self.result = None  # None=cancelled, {}=cleared, dict=saved
        self.title(f"Well {well_name}")
        self.resizable(False, False)
        self.grab_set()
        self.transient(parent)

        f = ttk.Frame(self, padding=(20, 14))
        f.pack()

        ttk.Label(f, text="Chemical name:").grid(row=0, column=0, sticky='e', padx=(0, 8), pady=5)
        self._name = tk.StringVar(value=data.get('chemical_name', ''))
        ttk.Entry(f, textvariable=self._name, width=22).grid(row=0, column=1, sticky='w')

        ttk.Label(f, text="Class:").grid(row=1, column=0, sticky='e', padx=(0, 8), pady=5)
        self._cls = tk.StringVar(value=data.get('class', ''))
        ttk.Combobox(f, textvariable=self._cls, width=20,
                     values=['pfd', 'organic', 'trace', 'wash', 'rinse']
                     ).grid(row=1, column=1, sticky='w')

        bf = ttk.Frame(f)
        bf.grid(row=2, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(bf, text="Clear",  command=self._clear).pack(side='left', padx=(0, 6))
        ttk.Button(bf, text="Cancel", command=self.destroy).pack(side='left', padx=(0, 6))
        ttk.Button(bf, text="Save", style='Accent.TButton',
                   command=self._save).pack(side='left')

        self.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width()  - self.winfo_width())  // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f'+{px}+{py}')
        self.wait_window()

    def _save(self):
        name = self._name.get().strip()
        if name:
            self.result = {'chemical_name': name, 'class': self._cls.get().strip()}
        self.destroy()

    def _clear(self):
        self.result = {}
        self.destroy()


class PlateEditor(ttk.Frame):
    """Interactive well-plate editor embedded in the main notebook."""

    # header dimensions (pixels)
    _HDR_L  = 40   # width of row-letter column
    _HDR_T  = 36   # height of column-number row
    _MARGIN = 1    # outer padding around the well grid (canvas coords)
    _GAP    = 1    # white gap between adjacent cells (pixels)

    def __init__(self, parent, style_colors, log_cb=None):
        super().__init__(parent)
        self._C   = style_colors
        self._log = log_cb or (lambda _: None)

        self._rows = 16
        self._cols = 24
        self._wells: dict = {}   # (ri, ci) → {'chemical_name', 'class'}
        self._zoom = 1.0
        self._resize_job = None
        self._cv_w = 0
        self._cv_h = 0
        self._hover_ri = None
        self._hover_ci = None

        self._geo_presets, self._rxn_presets = _load_presets()
        self._build_controls()
        self._build_canvas()

    # ── controls ───────────────────────────────────────────────────────────────

    def _build_controls(self):
        top = ttk.Frame(self)
        top.pack(fill='x', padx=8, pady=(8, 4))

        cfg = ttk.LabelFrame(top, text="PLATE CONFIGURATION", padding=(10, 6))
        cfg.pack(fill='x', pady=(0, 4))

        ttk.Label(cfg, text="Size", style='Muted.TLabel').grid(
            row=0, column=0, sticky='e', padx=(0, 5))
        self._size_var = tk.StringVar(value='384')
        size_cb = ttk.Combobox(cfg, textvariable=self._size_var, width=7,
                                values=list(PLATE_DEFAULTS) + ['Custom'])
        size_cb.grid(row=0, column=1, sticky='w', padx=(0, 10))
        size_cb.bind('<<ComboboxSelected>>', self._on_size_select)

        fields = [
            ('Rows',           '_rows_var', 16,  True),
            ('Cols',           '_cols_var', 24,  True),
            ('Spacing X (mm)', '_sx_var',   4.5, False),
            ('Spacing Y (mm)', '_sy_var',   4.5, False),
            ('Origin X (mm)',  '_ox_var',   0.0, False),
            ('Origin Y (mm)',  '_oy_var',   0.0, False),
        ]
        for idx, (lbl, attr, default, is_int) in enumerate(fields):
            row = idx // 3
            col = (idx % 3) * 2 + 2
            ttk.Label(cfg, text=lbl, style='Muted.TLabel').grid(
                row=row, column=col, sticky='e', padx=(10, 4))
            var = tk.IntVar(value=default) if is_int else tk.DoubleVar(value=default)
            setattr(self, attr, var)
            ent = ttk.Entry(cfg, textvariable=var, width=7)
            ent.grid(row=row, column=col + 1, sticky='w')
            if lbl == 'Rows':
                self._rows_entry = ent
                ent.configure(state='disabled')
            elif lbl == 'Cols':
                self._cols_entry = ent
                ent.configure(state='disabled')

        ttk.Button(cfg, text="Apply", style='Accent.TButton',
                   command=self._apply_config).grid(
            row=0, column=10, rowspan=2, padx=(16, 0))

        # preset bar
        pbar = ttk.Frame(top)
        pbar.pack(fill='x', pady=(0, 4))

        for title, cb_attr, var_attr, load_fn, save_fn, del_fn in [
            ('GEOMETRY PRESETS', '_geo_cb', '_geo_pvar',
             self._load_geo, self._save_geo, self._del_geo),
            ('REACTION PRESETS', '_rxn_cb', '_rxn_pvar',
             self._load_rxn, self._save_rxn, self._del_rxn),
        ]:
            pf = ttk.LabelFrame(pbar, text=title, padding=(8, 4))
            pf.pack(side='left', padx=(0, 8))
            var = tk.StringVar()
            setattr(self, var_attr, var)
            cb = ttk.Combobox(pf, textvariable=var, width=16)
            cb.pack(side='left', padx=(0, 5))
            setattr(self, cb_attr, cb)
            ttk.Button(pf, text="Load",     style='Ghost.TButton', command=load_fn).pack(side='left', padx=(0, 3))
            ttk.Button(pf, text="Save As…", style='Ghost.TButton', command=save_fn).pack(side='left', padx=(0, 3))
            ttk.Button(pf, text="Delete", style='Danger.TButton',
                       command=del_fn).pack(side='left')

        iof = ttk.LabelFrame(pbar, text="CSV", padding=(8, 4))
        iof.pack(side='left')
        ttk.Button(iof, text="Import", style='Ghost.TButton', command=self._import_csv).pack(side='left', padx=(0, 5))
        ttk.Button(iof, text="Export", style='Accent.TButton',
                   command=self._export_csv).pack(side='left')

        self._refresh_geo_cb()
        self._refresh_rxn_cb()

    def _build_canvas(self):
        body = ttk.Frame(self)
        body.pack(fill='both', expand=True, padx=8, pady=(0, 8))

        C = self._C

        # ── three-canvas spreadsheet layout ──────────────────────────────────
        # grid:  col0=row-letters  col1=wells(expand)  col2=v-scrollbar
        #        row0=col-numbers  row1=wells(expand)  row2=h-scrollbar
        cv_area = tk.Frame(body, bg=C['bg'])
        cv_area.pack(side='left', fill='both', expand=True)
        cv_area.rowconfigure(0, minsize=self._HDR_T)
        cv_area.rowconfigure(1, weight=1)
        cv_area.columnconfigure(0, minsize=self._HDR_L)
        cv_area.columnconfigure(1, weight=1)

        # corner filler (top-left)
        tk.Canvas(cv_area, bg=C['surface'],
                  width=self._HDR_L, height=self._HDR_T,
                  highlightthickness=0).grid(row=0, column=0, sticky='nsew')

        # zoom +/- controls pinned to top-right of the canvas area
        zf = ttk.Frame(cv_area)
        zf.grid(row=0, column=2, sticky='e', padx=(4, 2))
        ttk.Button(zf, text="−", style='Ghost.TButton', width=2,
                   command=self._zoom_out).pack(side='left')
        self._zoom_lbl = ttk.Label(zf, text=f"{int(self._zoom*100)}%",
                                   width=4, anchor='center', style='Muted.TLabel')
        self._zoom_lbl.pack(side='left', padx=2)
        ttk.Button(zf, text="+", style='Ghost.TButton', width=2,
                   command=self._zoom_in).pack(side='left')

        # column-number header canvas (top, scrolls X in sync with main)
        self._col_cv = tk.Canvas(cv_area, bg=C['surface'], height=self._HDR_T,
                                  highlightthickness=0)
        self._col_cv.grid(row=0, column=1, sticky='ew')

        # row-letter header canvas (left, scrolls Y in sync with main)
        self._row_cv = tk.Canvas(cv_area, bg=C['surface'], width=self._HDR_L,
                                  highlightthickness=0)
        self._row_cv.grid(row=1, column=0, sticky='ns')

        # scrollbars
        self._v_sb = ttk.Scrollbar(cv_area, orient='vertical')
        self._v_sb.grid(row=1, column=2, sticky='ns')
        self._h_sb = ttk.Scrollbar(cv_area, orient='horizontal')
        self._h_sb.grid(row=2, column=1, sticky='ew')

        # main well canvas
        self._cv = tk.Canvas(cv_area, bg=C['surface'],
                              highlightthickness=1, highlightbackground=C['border'],
                              xscrollcommand=self._on_xscroll_notify,
                              yscrollcommand=self._on_yscroll_notify)
        self._cv.grid(row=1, column=1, sticky='nsew')

        self._v_sb.config(command=self._cv.yview)
        self._h_sb.config(command=self._cv.xview)

        self._cv.bind('<Button-1>',           self._on_click)
        self._cv.bind('<Configure>',          self._on_canvas_configure)
        self._cv.bind('<Motion>',             self._on_hover)
        self._cv.bind('<Leave>',              lambda _e: self._clear_hover())
        self._cv.bind('<MouseWheel>',         self._on_mousewheel)
        self._cv.bind('<Control-MouseWheel>', self._on_ctrl_mousewheel)

        # legend + hover info panel on the right
        leg = ttk.LabelFrame(body, text="LEGEND", padding=(8, 6))
        leg.pack(side='left', fill='y', padx=(8, 0))

        self._legend_items = tk.Frame(leg, bg=C['surface'])
        self._legend_items.pack(fill='x')

        ttk.Separator(leg, orient='horizontal').pack(fill='x', pady=(8, 4))

        self._show_hover_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(leg, text="Show hover info",
                        variable=self._show_hover_var,
                        command=self._clear_hover).pack(anchor='w')
        self._hover_info = tk.Label(leg, text="", bg=C['surface'],
                                     font=('Segoe UI', 9), justify='left',
                                     fg=C['text2'], wraplength=130, anchor='w')
        self._hover_info.pack(anchor='w', fill='x', pady=(2, 4))

        ttk.Button(leg, text="Clear All", style='Danger.TButton',
                   command=self._clear_all).pack(side='bottom', fill='x', pady=(4, 0))

    # ── scroll sync ────────────────────────────────────────────────────────────

    def _on_xscroll_notify(self, first, last):
        """Called by main canvas when its X view changes; syncs col header."""
        self._h_sb.set(first, last)
        self._col_cv.xview_moveto(first)

    def _on_yscroll_notify(self, first, last):
        """Called by main canvas when its Y view changes; syncs row header."""
        self._v_sb.set(first, last)
        self._row_cv.yview_moveto(first)

    # ── zoom ───────────────────────────────────────────────────────────────────

    def _zoom_in(self):
        self._zoom = min(4.0, round(self._zoom + 0.1, 2))
        self._zoom_lbl.config(text=f"{int(self._zoom * 100)}%")
        self._redraw()

    def _zoom_out(self):
        self._zoom = max(0.1, round(self._zoom - 0.1, 2))
        self._zoom_lbl.config(text=f"{int(self._zoom * 100)}%")
        self._redraw()

    def _on_mousewheel(self, e):
        self._cv.yview_scroll(int(-1 * (e.delta / 120)), 'units')

    def _on_ctrl_mousewheel(self, e):
        cv = self._cv
        old_pw = getattr(self, '_plate_w', None)
        old_ph = getattr(self, '_plate_h', None)
        # Canvas-space position of the cursor before zoom
        anchor_cx = cv.canvasx(e.x)
        anchor_cy = cv.canvasy(e.y)

        if e.delta > 0:
            self._zoom = min(4.0, round(self._zoom + 0.1, 2))
        else:
            self._zoom = max(0.1, round(self._zoom - 0.1, 2))
        self._zoom_lbl.config(text=f"{int(self._zoom * 100)}%")
        self._redraw()

        # Scroll so the canvas point under the cursor stays under the cursor
        if old_pw and old_ph:
            new_pw = self._plate_w
            new_ph = self._plate_h
            xfrac = max(0.0, (anchor_cx / old_pw * new_pw - e.x) / new_pw)
            yfrac = max(0.0, (anchor_cy / old_ph * new_ph - e.y) / new_ph)
            cv.xview_moveto(xfrac)
            self._col_cv.xview_moveto(xfrac)
            cv.yview_moveto(yfrac)
            self._row_cv.yview_moveto(yfrac)

    # ── size / config ──────────────────────────────────────────────────────────

    def _on_size_select(self, _e=None):
        s = self._size_var.get()
        if s in PLATE_DEFAULTS:
            d = PLATE_DEFAULTS[s]
            self._rows_var.set(d['rows'])
            self._cols_var.set(d['cols'])
            self._sx_var.set(d['spacing'])
            self._sy_var.set(d['spacing'])
            self._rows_entry.configure(state='disabled')
            self._cols_entry.configure(state='disabled')
        else:
            self._rows_entry.configure(state='normal')
            self._cols_entry.configure(state='normal')

    def _apply_config(self):
        try:
            rows = max(1, min(26, int(self._rows_var.get())))
            cols = max(1, min(48, int(self._cols_var.get())))
        except Exception:
            messagebox.showerror("Error", "Rows and columns must be whole numbers.",
                                 parent=self.winfo_toplevel())
            return
        if (rows, cols) != (self._rows, self._cols) and self._wells:
            if not messagebox.askyesno(
                    "Resize plate",
                    "Changing dimensions will clear all current well assignments. Continue?",
                    parent=self.winfo_toplevel()):
                return
            self._wells.clear()
        self._rows = rows
        self._cols = cols
        self._redraw()
        self._refresh_legend()
        self._log(f"Plate set to {rows} rows × {cols} cols")

    # ── drawing ────────────────────────────────────────────────────────────────

    def _on_canvas_configure(self, event):
        self._cv_w = event.width
        self._cv_h = event.height
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(120, self._redraw)

    def _redraw(self):
        cv     = self._cv
        col_cv = self._col_cv
        row_cv = self._row_cv
        cv.delete('all')
        col_cv.delete('all')
        row_cv.delete('all')
        self._hover_ri = None
        self._hover_ci = None

        rows, cols = self._rows, self._cols
        w = self._cv_w if self._cv_w > 10 else cv.winfo_width()
        h = self._cv_h if self._cv_h > 10 else cv.winfo_height()
        if w < 10 or h < 10:
            return

        M = self._MARGIN
        auto_cell = min(
            (w - 2 * M) / max(cols, 1),
            (h - 2 * M) / max(rows, 1),
        )
        cell = max(4.0, auto_cell * self._zoom)
        self._cell = cell

        plate_w = 2 * M + cols * cell
        plate_h = 2 * M + rows * cell
        self._plate_w = plate_w
        self._plate_h = plate_h

        cv.configure(scrollregion=(0, 0, plate_w, plate_h), bg='#FFFFFF')
        col_cv.configure(scrollregion=(0, 0, plate_w, self._HDR_T))
        row_cv.configure(scrollregion=(0, 0, self._HDR_L, plate_h))

        cv.xview_moveto(0)
        cv.yview_moveto(0)
        col_cv.xview_moveto(0)
        row_cv.yview_moveto(0)

        font_sz = max(6, min(10, int(cell * 0.38)))
        font    = ('Segoe UI', font_sz)
        gap     = self._GAP

        # column numbers in frozen top header
        for ci in range(cols):
            cx = M + (ci + 0.5) * cell
            col_cv.create_text(cx, self._HDR_T // 2, text=str(ci + 1),
                               font=font, fill='#555', anchor='center')

        # row letters in frozen left header
        for ri in range(rows):
            label = string.ascii_uppercase[ri] if ri < 26 else f'?{ri}'
            cy = M + (ri + 0.5) * cell
            row_cv.create_text(self._HDR_L // 2, cy, text=label,
                               font=font, fill='#555', anchor='center')

        # square cells — white canvas background shows through as gap lines
        for ri in range(rows):
            for ci in range(cols):
                x0 = M + ci * cell
                y0 = M + ri * cell
                x1 = x0 + cell - gap
                y1 = y0 + cell - gap
                fill  = _class_color(self._wells.get((ri, ci), {}).get('class', ''))
                color = fill or '#E5E5EA'
                cv.create_rectangle(x0, y0, x1, y1,
                                    fill=color, outline='',
                                    tags=(f'w{ri}_{ci}',))

    # ── interaction ────────────────────────────────────────────────────────────

    def _hit(self, vx, vy):
        """Convert viewport (mouse event) coords → well (row, col) indices."""
        cx   = self._cv.canvasx(vx)
        cy   = self._cv.canvasy(vy)
        cell = getattr(self, '_cell', 14.0)
        M    = self._MARGIN
        ci   = int((cx - M) / cell)
        ri   = int((cy - M) / cell)
        if 0 <= ri < self._rows and 0 <= ci < self._cols:
            return ri, ci
        return None, None

    def _set_cell_color(self, ri, ci, hover=False):
        """Update a single cell's fill without redrawing the whole plate."""
        fill  = _class_color(self._wells.get((ri, ci), {}).get('class', ''))
        color = fill or '#E5E5EA'
        if hover:
            color = _darken(color, 0.12)
        self._cv.itemconfig(f'w{ri}_{ci}', fill=color)

    def _on_click(self, e):
        ri, ci = self._hit(e.x, e.y)
        if ri is None:
            return
        name = string.ascii_uppercase[ri] + str(ci + 1)
        dlg  = _WellDialog(self.winfo_toplevel(), name, self._wells.get((ri, ci), {}))
        if dlg.result is None:
            return
        if dlg.result:
            self._wells[(ri, ci)] = dlg.result
        else:
            self._wells.pop((ri, ci), None)
        self._redraw()
        self._refresh_legend()

    def _on_hover(self, e):
        ri, ci = self._hit(e.x, e.y)

        if (ri, ci) != (self._hover_ri, self._hover_ci):
            if self._hover_ri is not None:
                self._set_cell_color(self._hover_ri, self._hover_ci, hover=False)
            self._hover_ri = ri
            self._hover_ci = ci
            if ri is not None:
                self._set_cell_color(ri, ci, hover=True)

        if ri is None:
            self._hover_info.config(text="")
            return
        if not self._show_hover_var.get():
            return
        name = string.ascii_uppercase[ri] + str(ci + 1)
        d    = self._wells.get((ri, ci))
        if d:
            self._hover_info.config(text=f"{name}  {d['chemical_name']}\n[{d['class']}]")
        else:
            self._hover_info.config(text=name)

    def _clear_hover(self):
        if self._hover_ri is not None:
            self._set_cell_color(self._hover_ri, self._hover_ci, hover=False)
            self._hover_ri = None
            self._hover_ci = None
        self._hover_info.config(text="")

    def _clear_all(self):
        if messagebox.askyesno("Clear All", "Remove all well assignments?",
                               parent=self.winfo_toplevel()):
            self._wells.clear()
            self._redraw()
            self._refresh_legend()

    # ── legend ─────────────────────────────────────────────────────────────────

    def _refresh_legend(self):
        for w in self._legend_items.winfo_children():
            w.destroy()
        seen = {}
        for d in self._wells.values():
            cls = (d.get('class') or '').strip()
            if cls and cls not in seen:
                seen[cls] = _class_color(cls) or '#888888'
        for cls, col in seen.items():
            row = tk.Frame(self._legend_items, bg=self._C['surface'])
            row.pack(anchor='w', pady=2, fill='x')
            tk.Label(row, bg=col, width=2, height=1).pack(side='left', padx=(0, 6))
            tk.Label(row, text=cls, bg=self._C['surface'],
                     font=('Segoe UI', 9)).pack(side='left')

    # ── CSV import / export ────────────────────────────────────────────────────

    def _import_csv(self):
        path = filedialog.askopenfilename(
            title="Import CSV", filetypes=[('CSV', '*.csv'), ('All', '*.*')],
            parent=self.winfo_toplevel())
        if not path:
            return
        try:
            df = pd.read_csv(path)
            missing = {'plate_row', 'plate_column', 'chemical_name', 'class'} - set(df.columns)
            if missing:
                messagebox.showerror("Error",
                    f"CSV missing columns: {', '.join(missing)}",
                    parent=self.winfo_toplevel())
                return
            self._wells.clear()
            for _, row in df.dropna(subset=['plate_row', 'plate_column']).iterrows():
                r_str = str(row['plate_row']).strip().upper()
                if not r_str or r_str[0] not in string.ascii_uppercase:
                    continue
                ri = string.ascii_uppercase.index(r_str[0])
                ci = int(row['plate_column']) - 1
                if 0 <= ri < self._rows and 0 <= ci < self._cols:
                    self._wells[(ri, ci)] = {
                        'chemical_name': str(row['chemical_name']),
                        'class':         str(row['class']),
                    }
            self._redraw()
            self._refresh_legend()
            self._log(f"Plate Editor: imported {len(self._wells)} wells from {os.path.basename(path)}")
        except Exception as ex:
            messagebox.showerror("Import Error", str(ex), parent=self.winfo_toplevel())

    def _export_csv(self):
        if not self._wells:
            messagebox.showwarning("Nothing to export", "No wells assigned.",
                                   parent=self.winfo_toplevel())
            return
        path = filedialog.asksaveasfilename(
            title="Export CSV", defaultextension='.csv',
            filetypes=[('CSV', '*.csv')], parent=self.winfo_toplevel())
        if not path:
            return
        pd.DataFrame(self._build_rows()).to_csv(path, index=False)
        self._log(f"Plate Editor: exported {len(self._wells)} wells to {os.path.basename(path)}")

    def _build_rows(self):
        rows = []
        for (ri, ci), d in sorted(self._wells.items()):
            x = self._ox_var.get() + ci * self._sx_var.get()
            y = self._oy_var.get() + ri * self._sy_var.get()
            rows.append({
                'plate_row':     string.ascii_uppercase[ri],
                'plate_column':  ci + 1,
                'chemical_name': d.get('chemical_name', ''),
                'class':         d.get('class', ''),
                'x':             round(x, 4),
                'y':             round(y, 4),
                'smiles':        '',
            })
        return rows

    def get_dataframe(self):
        """Return a DataFrame compatible with Screen.initialize()."""
        rows = self._build_rows()
        if not rows:
            raise ValueError("No wells are assigned in the Plate Editor.")
        return pd.DataFrame(rows)

    # ── geometry presets ───────────────────────────────────────────────────────

    def _refresh_geo_cb(self):
        names = list(self._geo_presets)
        self._geo_cb['values'] = names
        if names:
            self._geo_pvar.set(names[0])

    def _load_geo(self):
        n = self._geo_pvar.get()
        if n not in self._geo_presets:
            return
        p = self._geo_presets[n]
        self._rows_var.set(p['rows'])
        self._cols_var.set(p['cols'])
        self._sx_var.set(p['spacing_x'])
        self._sy_var.set(p['spacing_y'])
        self._ox_var.set(p.get('origin_x', 0.0))
        self._oy_var.set(p.get('origin_y', 0.0))
        self._size_var.set('Custom')
        self._rows_entry.configure(state='normal')
        self._cols_entry.configure(state='normal')
        self._apply_config()
        self._log(f"Plate Editor: loaded geometry preset '{n}'")

    def _save_geo(self):
        n = simpledialog.askstring("Save Geometry Preset", "Name:",
                                   parent=self.winfo_toplevel())
        if not n:
            return
        self._geo_presets[n] = {
            'rows': int(self._rows_var.get()), 'cols': int(self._cols_var.get()),
            'spacing_x': self._sx_var.get(),   'spacing_y': self._sy_var.get(),
            'origin_x':  self._ox_var.get(),   'origin_y':  self._oy_var.get(),
        }
        _save_presets(self._geo_presets, self._rxn_presets)
        self._refresh_geo_cb()
        self._geo_pvar.set(n)
        self._log(f"Plate Editor: saved geometry preset '{n}'")

    def _del_geo(self):
        n = self._geo_pvar.get()
        if n and n in self._geo_presets:
            if messagebox.askyesno("Delete", f"Delete geometry preset '{n}'?",
                                   parent=self.winfo_toplevel()):
                del self._geo_presets[n]
                _save_presets(self._geo_presets, self._rxn_presets)
                self._refresh_geo_cb()

    # ── reaction presets ───────────────────────────────────────────────────────

    def _refresh_rxn_cb(self):
        names = list(self._rxn_presets)
        self._rxn_cb['values'] = names
        if names:
            self._rxn_pvar.set(names[0])

    def _load_rxn(self):
        n = self._rxn_pvar.get()
        if n not in self._rxn_presets:
            return
        self._wells = {
            (int(k.split(',')[0]), int(k.split(',')[1])): v
            for k, v in self._rxn_presets[n].get('wells', {}).items()
        }
        self._redraw()
        self._refresh_legend()
        self._log(f"Plate Editor: loaded reaction preset '{n}'")

    def _save_rxn(self):
        n = simpledialog.askstring("Save Reaction Preset", "Name:",
                                   parent=self.winfo_toplevel())
        if not n:
            return
        self._rxn_presets[n] = {
            'wells': {f'{ri},{ci}': d for (ri, ci), d in self._wells.items()}
        }
        _save_presets(self._geo_presets, self._rxn_presets)
        self._refresh_rxn_cb()
        self._rxn_pvar.set(n)
        self._log(f"Plate Editor: saved reaction preset '{n}'")

    def _del_rxn(self):
        n = self._rxn_pvar.get()
        if n and n in self._rxn_presets:
            if messagebox.askyesno("Delete", f"Delete reaction preset '{n}'?",
                                   parent=self.winfo_toplevel()):
                del self._rxn_presets[n]
                _save_presets(self._geo_presets, self._rxn_presets)
                self._refresh_rxn_cb()
