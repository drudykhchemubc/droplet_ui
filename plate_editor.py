import colorsys
import hashlib
import json
import os
import re
import string
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog, colorchooser

import pandas as pd

from animated_tab_design import PillToggle
from dropdown_autocomplete import bind_typeahead
from gcode_generator import Screen

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

# Legend grouping: classes that share a color are combined onto one legend line.
_LEGEND_GROUPS = [
    ('PFD / Oil',      ('pfd', 'perfluorodecalin', 'oil')),
    ('Organic',        ('organic',)),
    ('Trace / Mark',   ('trace', 'mark')),
    ('Wash / Rinse',   ('wash', 'rinse')),
]

CONFIG_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'microdroplet_config.json')
GEOMETRY_PRESETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'geometry_presets')
RXN_PRESETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'rxn_presets')


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


def _sanitize_preset_name(name):
    invalid = '\\/:*?"<>|'
    cleaned = ''.join(c for c in name if c not in invalid).strip()
    return cleaned


def _matching_plate_size(rows, cols):
    """Return the PLATE_DEFAULTS key whose well count matches rows*cols,
    regardless of orientation (e.g. 3x2 still counts as a '6' well plate)
    or spacing/origin — or None if no standard size has that many wells."""
    total = rows * cols
    for name, info in PLATE_DEFAULTS.items():
        if info['rows'] * info['cols'] == total:
            return name
    return None


def _list_presets(directory):
    os.makedirs(directory, exist_ok=True)
    return sorted(
        os.path.splitext(f)[0] for f in os.listdir(directory)
        if f.endswith('.json')
    )


def _load_preset(directory, name):
    path = os.path.join(directory, f'{name}.json')
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _save_preset(directory, name, data):
    os.makedirs(directory, exist_ok=True)
    path = os.path.join(directory, f'{name}.json')
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


def _delete_preset(directory, name):
    path = os.path.join(directory, f'{name}.json')
    if os.path.exists(path):
        os.remove(path)


def _migrate_legacy_presets():
    """One-time migration of presets previously stored inline in the config
    file (under 'plate_presets') into their own per-preset JSON files."""
    if not os.path.exists(CONFIG_PATH):
        return
    try:
        with open(CONFIG_PATH) as f:
            cfg = json.load(f)
    except Exception:
        return
    pp = cfg.pop('plate_presets', None)
    if not pp:
        return
    for name, data in pp.get('geometry', {}).items():
        _save_preset(GEOMETRY_PRESETS_DIR, name, data)
    for name, data in pp.get('reactions', {}).items():
        _save_preset(RXN_PRESETS_DIR, name, data)
    try:
        with open(CONFIG_PATH, 'w') as f:
            json.dump(cfg, f, indent=2)
    except Exception:
        pass


_migrate_legacy_presets()


def _is_aux_class(cls_str):
    """True for carrier / marker / wash classes, which Screen leaves out of the combinations."""
    cls = (cls_str or '').lower()
    return any(k in cls for k in Screen._SKIP)


def _is_carrier_class(cls_str):
    cls = (cls_str or '').lower()
    return any(k in cls for k in ('pfd', 'perfluorodecalin', 'oil'))


def _infer_role(wells, cls, exclude=None):
    """'varied' if another well already uses this class, else 'fixed'."""
    others = sum(1 for k, d in wells.items()
                 if k != exclude and (d.get('class') or '').strip() == cls)
    return 'varied' if cls and others else 'fixed'


class _WellDialog(tk.Toplevel):
    """Modal dialog to assign or clear a single well."""

    def __init__(self, parent, style_colors, well_name, data, used_classes=(), role='fixed'):
        super().__init__(parent)
        self.result = None  # None=cancelled, {}=cleared, dict=saved
        self.title(f"Well {well_name}")
        self.resizable(False, False)
        self.grab_set()
        self.transient(parent)

        f = ttk.Frame(self, padding=(20, 14))
        f.pack()

        ttk.Label(f, text="Chemical name:").grid(row=0, column=0, sticky='e', padx=(0, 8), pady=5)
        self._name_var = tk.StringVar(value=data.get('chemical_name', ''))
        ttk.Entry(f, textvariable=self._name_var, width=22).grid(row=0, column=1, sticky='w')

        ttk.Label(f, text="Class:").grid(row=1, column=0, sticky='e', padx=(0, 8), pady=5)
        self._cls = tk.StringVar(value=data.get('class', ''))
        # Each distinct class is one reagent slot in Screen's combination product,
        # so offer the classes already on the plate. No typeahead here: it would
        # overwrite custom class names (e.g. "photocatalyst" -> "PFD / Oil").
        presets = [label for label, _keys in _LEGEND_GROUPS]
        extra = sorted({c for c in used_classes if c and c not in presets}, key=str.lower)
        cls_cb = ttk.Combobox(f, textvariable=self._cls, width=20, values=presets + extra)
        cls_cb.grid(row=1, column=1, sticky='w')

        ttk.Label(f, text="Role:").grid(row=2, column=0, sticky='e', padx=(0, 8), pady=5)
        self._role = tk.StringVar(value=role)
        self._role_toggle = PillToggle(f, style_colors,
                                       [("Fixed", 'fixed'), ("Varied", 'varied')], self._role)
        self._role_toggle.grid(row=2, column=1, sticky='w', pady=5)

        # A fixed well's class follows its name until the class is edited separately.
        name, cls = self._name_var.get().strip(), self._cls.get().strip()
        self._cls_linked = cls in ('', name)
        self._name_var.trace_add('write', lambda *_: self._on_name_change())
        self._cls.trace_add('write', lambda *_: self._on_class_change())
        self._update_role_state()

        bf = ttk.Frame(f)
        bf.grid(row=3, column=0, columnspan=2, pady=(12, 0))
        ttk.Button(bf, text="Clear",  command=self._clear).pack(side='left', padx=(0, 6))
        ttk.Button(bf, text="Cancel", command=self.destroy).pack(side='left', padx=(0, 6))
        ttk.Button(bf, text="Save", style='Accent.TButton',
                   command=self._save).pack(side='left')

        self.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width()  - self.winfo_width())  // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f'+{px}+{py}')
        self.wait_window()

    def _on_name_change(self):
        if self._cls_linked and self._role.get() == 'fixed':
            self._cls.set(self._name_var.get().strip())

    def _on_class_change(self):
        cls = self._cls.get().strip()
        self._cls_linked = cls in ('', self._name_var.get().strip())
        self._update_role_state()

    def _update_role_state(self):
        # carrier / marker / wash wells aren't part of the reactions
        self._role_toggle.set_enabled(not _is_aux_class(self._cls.get()))

    def _save(self):
        name = self._name_var.get().strip()
        if name:
            cls = self._cls.get().strip()
            result = {'chemical_name': name, 'class': cls}
            if not _is_aux_class(cls):
                role = self._role.get()
                if role == 'varied' and not cls:
                    messagebox.showwarning(
                        "Class Needed",
                        "Give a varied reagent a Class (e.g. \"photocatalyst\").\n\n",
                        parent=self)
                    return
                if role == 'fixed' and not cls:
                    result['class'] = name
                result['role'] = role
            self.result = result
        self.destroy()

    def _clear(self):
        self.result = {}
        self.destroy()


class _ColorPickerDialog(tk.Toplevel):
    """Modal dialog to pick a well's color via hex code, RGB, HSV, or a color wheel."""

    def __init__(self, parent, well_name, current_hex):
        super().__init__(parent)
        self.result = None  # None=cancelled, ''=reset to class color, '#rrggbb'=chosen
        self.title(f"Well {well_name} — Color")
        self.resizable(False, False)
        self.grab_set()
        self.transient(parent)

        self._updating = False
        start = self._normalize_hex(current_hex) or '#4a90d9'

        f = ttk.Frame(self, padding=(20, 14))
        f.pack()

        self._swatch = tk.Label(f, width=16, height=2, bg=start, relief='solid', borderwidth=1)
        self._swatch.grid(row=0, column=0, columnspan=4, pady=(0, 12))

        ttk.Label(f, text="Hex:").grid(row=1, column=0, sticky='e', padx=(0, 8), pady=4)
        self._hex_var = tk.StringVar(value=start)
        hex_entry = ttk.Entry(f, textvariable=self._hex_var, width=10)
        hex_entry.grid(row=1, column=1, sticky='w', pady=4)
        hex_entry.bind('<Return>', lambda _e: self._apply_hex())
        hex_entry.bind('<FocusOut>', lambda _e: self._apply_hex())
        ttk.Button(f, text="Color Wheel…", command=self._open_wheel).grid(
            row=1, column=2, columnspan=2, sticky='w', padx=(14, 0))

        self._r_var = tk.IntVar()
        self._g_var = tk.IntVar()
        self._b_var = tk.IntVar()
        ttk.Label(f, text="RGB:").grid(row=2, column=0, sticky='e', padx=(0, 8), pady=4)
        rgb_row = ttk.Frame(f)
        rgb_row.grid(row=2, column=1, columnspan=3, sticky='w', pady=4)
        for lbl, var in (('R', self._r_var), ('G', self._g_var), ('B', self._b_var)):
            ttk.Label(rgb_row, text=lbl, style='Muted.TLabel').pack(side='left', padx=(0, 3))
            tk.Spinbox(rgb_row, from_=0, to=255, width=4, textvariable=var).pack(
                side='left', padx=(0, 10))
            var.trace_add('write', self._on_rgb_change)

        self._h_var = tk.IntVar()
        self._s_var = tk.IntVar()
        self._v_var = tk.IntVar()
        ttk.Label(f, text="HSV:").grid(row=3, column=0, sticky='e', padx=(0, 8), pady=4)
        hsv_row = ttk.Frame(f)
        hsv_row.grid(row=3, column=1, columnspan=3, sticky='w', pady=4)
        for lbl, var, hi in (('H', self._h_var, 360), ('S', self._s_var, 100), ('V', self._v_var, 100)):
            ttk.Label(hsv_row, text=lbl, style='Muted.TLabel').pack(side='left', padx=(0, 3))
            tk.Spinbox(hsv_row, from_=0, to=hi, width=4, textvariable=var).pack(
                side='left', padx=(0, 10))
            var.trace_add('write', self._on_hsv_change)

        bf = ttk.Frame(f)
        bf.grid(row=4, column=0, columnspan=4, pady=(14, 0))
        ttk.Button(bf, text="Use Class Color", command=self._reset).pack(side='left', padx=(0, 6))
        ttk.Button(bf, text="Cancel", command=self.destroy).pack(side='left', padx=(0, 6))
        ttk.Button(bf, text="Apply", style='Accent.TButton', command=self._apply).pack(side='left')

        self._set_from_hex(start)

        self.update_idletasks()
        px = parent.winfo_rootx() + (parent.winfo_width()  - self.winfo_width())  // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - self.winfo_height()) // 2
        self.geometry(f'+{px}+{py}')
        self.wait_window()

    @staticmethod
    def _normalize_hex(h):
        if not h:
            return None
        h = h.strip()
        if not h.startswith('#'):
            h = '#' + h
        if re.match(r'^#[0-9A-Fa-f]{6}$', h):
            return h.lower()
        return None

    def _current_hex(self):
        return self._hex_var.get()

    def _apply_hex(self):
        norm = self._normalize_hex(self._hex_var.get())
        if norm is None:
            messagebox.showerror("Invalid Hex Code",
                                 "Enter a hex color like #4A90D9.", parent=self)
            return
        self._set_from_hex(norm)

    def _set_from_hex(self, hexstr):
        self._updating = True
        try:
            r, g, b = int(hexstr[1:3], 16), int(hexstr[3:5], 16), int(hexstr[5:7], 16)
            self._r_var.set(r)
            self._g_var.set(g)
            self._b_var.set(b)
            h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
            self._h_var.set(round(h * 360))
            self._s_var.set(round(s * 100))
            self._v_var.set(round(v * 100))
            self._hex_var.set(hexstr)
            self._swatch.config(bg=hexstr)
        finally:
            self._updating = False

    def _on_rgb_change(self, *_a):
        if self._updating:
            return
        try:
            r = max(0, min(255, int(self._r_var.get())))
            g = max(0, min(255, int(self._g_var.get())))
            b = max(0, min(255, int(self._b_var.get())))
        except (tk.TclError, ValueError):
            return
        self._set_from_hex(f'#{r:02x}{g:02x}{b:02x}')

    def _on_hsv_change(self, *_a):
        if self._updating:
            return
        try:
            h = max(0, min(360, int(self._h_var.get()))) / 360
            s = max(0, min(100, int(self._s_var.get()))) / 100
            v = max(0, min(100, int(self._v_var.get()))) / 100
        except (tk.TclError, ValueError):
            return
        r, g, b = (round(c * 255) for c in colorsys.hsv_to_rgb(h, s, v))
        self._set_from_hex(f'#{r:02x}{g:02x}{b:02x}')

    def _open_wheel(self):
        _rgb, hexstr = colorchooser.askcolor(color=self._current_hex(),
                                             title="Pick a Color", parent=self)
        if hexstr:
            norm = self._normalize_hex(hexstr)
            if norm:
                self._set_from_hex(norm)

    def _reset(self):
        self.result = ''
        self.destroy()

    def _apply(self):
        self.result = self._current_hex()
        self.destroy()


class PlateEditor(ttk.Frame):
    """Interactive well-plate editor embedded in the main notebook."""

    # header dimensions (pixels)
    _HDR_L  = 40   # width of row-letter column
    _HDR_T  = 36   # height of column-number row
    _MARGIN = 1    # outer padding around the well grid (canvas coords)
    _GAP    = 1    # white gap between adjacent cells (pixels)

    def __init__(self, parent, style_colors, log_cb=None, repeats_var=None):
        super().__init__(parent)
        self._C   = style_colors
        self._log = log_cb or (lambda _: None)
        self._repeats_var = repeats_var

        self._rows = 16
        self._cols = 24
        self._wells: dict = {}   # (ri, ci) → {'chemical_name', 'class', 'role'}
        self._zoom = 1.0
        self._resize_job = None
        self._cv_w = 0
        self._cv_h = 0
        self._hover_ri = None
        self._hover_ci = None

        self._build_controls()
        self._build_canvas()
        if repeats_var is not None:
            repeats_var.trace_add('write', lambda *_: self._refresh_summary())
        self._refresh_summary()

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
        bind_typeahead(size_cb)

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
            cb.bind('<<ComboboxSelected>>', lambda _e, fn=load_fn: fn())
            bind_typeahead(cb)
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
        C = self._C

        # packed first (bottom) so the expanding plate area can't squeeze it out
        summ = ttk.LabelFrame(self, text="SCREEN SUMMARY", padding=(10, 6))
        summ.pack(side='bottom', fill='x', padx=8, pady=(0, 8))
        self._summary_body = tk.Frame(summ, bg=C['surface'])
        self._summary_body.pack(fill='x')
        self._summary_body.columnconfigure(1, weight=1)
        self._summary_body.bind('<Configure>', self._rewrap_summary)
        self._wrap_labels = []

        body = ttk.Frame(self)
        body.pack(fill='both', expand=True, padx=8, pady=(0, 8))

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
        self._cv.bind('<Button-3>',           self._on_right_click)
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
            return
        self._apply_config()

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
        varied = self._screen_summary()['varied_wells']
        for ri in range(rows):
            for ci in range(cols):
                x0 = M + ci * cell
                y0 = M + ri * cell
                x1 = x0 + cell - gap
                y1 = y0 + cell - gap
                color = self._well_color(ri, ci)
                cv.create_rectangle(x0, y0, x1, y1,
                                    fill=color, outline='',
                                    tags=(f'w{ri}_{ci}',))
                if (ri, ci) in varied:
                    # dark inset border marks wells that change between reactions
                    bw = max(1.5, cell * 0.08)
                    cv.create_rectangle(x0 + bw / 2, y0 + bw / 2, x1 - bw / 2, y1 - bw / 2,
                                        outline='#1D1D1F', width=bw)

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

    def _well_color(self, ri, ci):
        """Resolve a well's fill color: manual override if set, else class-derived."""
        d = self._wells.get((ri, ci), {})
        return d.get('color') or _class_color(d.get('class', '')) or '#E5E5EA'

    def _set_cell_color(self, ri, ci, hover=False):
        """Update a single cell's fill without redrawing the whole plate."""
        color = self._well_color(ri, ci)
        if hover:
            color = _darken(color, 0.12)
        self._cv.itemconfig(f'w{ri}_{ci}', fill=color)

    def _on_click(self, e):
        ri, ci = self._hit(e.x, e.y)
        if ri is None:
            return
        name = string.ascii_uppercase[ri] + str(ci + 1)
        used = {(d.get('class') or '').strip() for d in self._wells.values()}
        data = self._wells.get((ri, ci), {})
        role = data.get('role') or _infer_role(
            self._wells, (data.get('class') or '').strip(), exclude=(ri, ci))
        dlg  = _WellDialog(self.winfo_toplevel(), self._C, name, data, used, role)
        if dlg.result is None:
            return
        if dlg.result:
            entry = dict(dlg.result)
            existing_color = self._wells.get((ri, ci), {}).get('color')
            if existing_color:
                entry['color'] = existing_color
            self._wells[(ri, ci)] = entry
        else:
            self._wells.pop((ri, ci), None)
        self._redraw()
        self._refresh_legend()

    def _on_right_click(self, e):
        ri, ci = self._hit(e.x, e.y)
        if ri is None:
            return
        name = string.ascii_uppercase[ri] + str(ci + 1)
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="Rename…", command=lambda: self._rename_well(ri, ci, name))
        menu.add_command(label="Change Color…", command=lambda: self._change_well_color(ri, ci, name))
        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()

    def _rename_well(self, ri, ci, well_name):
        current = self._wells.get((ri, ci), {}).get('chemical_name', '')
        new_name = simpledialog.askstring(
            "Rename Well", f"New name for well {well_name}:",
            initialvalue=current, parent=self.winfo_toplevel())
        if new_name is None:
            return
        new_name = new_name.strip()
        if not new_name:
            messagebox.showwarning("Empty Name", "Well name cannot be empty.",
                                   parent=self.winfo_toplevel())
            return
        entry = self._wells.setdefault((ri, ci), {'class': ''})
        # a fixed well whose class is just its name keeps the two in sync
        if (entry.get('role') != 'varied' and not _is_aux_class(entry.get('class'))
                and (entry.get('class') or '').strip() in ('', current.strip())):
            entry['class'] = new_name
        entry['chemical_name'] = new_name
        self._redraw()
        self._refresh_legend()
        self._log(f"Plate Editor: renamed well {well_name} to '{new_name}'")

    def _change_well_color(self, ri, ci, well_name):
        current = self._well_color(ri, ci)
        dlg = _ColorPickerDialog(self.winfo_toplevel(), well_name, current)
        if dlg.result is None:
            return
        if dlg.result == '':
            entry = self._wells.get((ri, ci))
            if entry is not None:
                entry.pop('color', None)
                if not entry.get('chemical_name') and not entry.get('class'):
                    self._wells.pop((ri, ci), None)
            self._log(f"Plate Editor: reset well {well_name} to class color")
        else:
            entry = self._wells.setdefault((ri, ci), {'class': ''})
            entry['color'] = dlg.result
            self._log(f"Plate Editor: set well {well_name} color to {dlg.result}")
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
            self._hover_info.config(
                text=f"{name}  {d.get('chemical_name', '')}\n[{d.get('class', '')}]")
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

        used = {(d.get('class') or '').strip().lower() for d in self._wells.values()}
        used.discard('')

        entries = []  # (label, color)
        matched = set()
        for label, keys in _LEGEND_GROUPS:
            group_hits = {cls for cls in used if any(k in cls for k in keys)}
            if group_hits:
                entries.append((label, _class_color(keys[0])))
                matched |= group_hits

        # anything not covered by the known groups keeps its own line
        leftover = {}
        for d in self._wells.values():
            cls = (d.get('class') or '').strip()
            if cls and cls.lower() not in matched and cls.lower() not in leftover:
                leftover[cls.lower()] = cls
        for cls in leftover.values():
            entries.append((cls, _class_color(cls) or '#888888'))

        for label, col in entries:
            row = tk.Frame(self._legend_items, bg=self._C['surface'])
            row.pack(anchor='w', pady=2, fill='x')
            tk.Label(row, bg=col, width=2, height=1).pack(side='left', padx=(0, 6))
            tk.Label(row, text=label, bg=self._C['surface'],
                     font=('Segoe UI', 9)).pack(side='left')

        self._refresh_summary()

    # ── screen summary ─────────────────────────────────────────────────────────

    def _screen_summary(self):
        """Mirror Screen.initialize(): one reaction per pick of one well from each
        reagent class. Classes with one well are fixed, classes with more are varied."""
        groups = {}     # exact class string → [(key, well)] (Screen groups case-sensitively)
        carriers = []
        for key, d in sorted(self._wells.items()):
            cls = (d.get('class') or '').strip()
            if _is_aux_class(cls):
                if _is_carrier_class(cls):
                    carriers.append(d.get('chemical_name', ''))
                continue
            groups.setdefault(cls, []).append((key, d))

        fixed  = {c: m for c, m in groups.items() if len(m) == 1}
        varied = {c: m for c, m in groups.items() if len(m) > 1}
        reactions = 1
        for members in groups.values():
            reactions *= len(members)

        # errors stop Screen.generate_gcode(); warnings only flag a likely setup mistake
        errors, warnings = [], []
        if self._wells and not carriers:
            errors.append(
                "No carrier well is assigned. Assign at least one well to the "
                "class \"PFD / Oil\".")
        for cls, members in fixed.items():
            d = members[0][1]
            if d.get('role') == 'varied':
                warnings.append(
                    f"\"{d.get('chemical_name', '')}\" is set to Varied, but it is the only "
                    f"well in the class \"{cls}\", so it will be included in every reaction. "
                    f"Assign the same class to each alternative reagent, or set this well "
                    f"to Fixed.")
        for cls, members in varied.items():
            n = len(members)
            marked_fixed = [d.get('chemical_name', '') for _k, d in members
                            if d.get('role') == 'fixed']
            if marked_fixed:
                quoted = ', '.join(f'"{m}"' for m in marked_fixed)
                warnings.append(
                    f"The class \"{cls}\" contains {n} wells, so each will be used in a "
                    f"separate reaction ({n} reactions). However, {quoted} "
                    f"{'is' if len(marked_fixed) == 1 else 'are'} set to Fixed. To include "
                    f"a reagent in every reaction, assign it a class of its own.")
            names = [d.get('chemical_name', '') for _k, d in members]
            for dup in sorted({nm for nm in names if names.count(nm) > 1}):
                warnings.append(
                    f"The name \"{dup}\" is used for {names.count(dup)} wells in the class "
                    f"\"{cls}\". These reactions will be listed identically in the "
                    f"combinations CSV. Give each well a distinct name "
                    f"(e.g. \"{dup}1\", \"{dup}2\").")
        by_lower = {}
        for cls in groups:
            by_lower.setdefault(cls.lower(), []).append(cls)
        for spellings in by_lower.values():
            if len(spellings) > 1:
                quoted = ' and '.join(f'"{sp}"' for sp in spellings)
                warnings.append(
                    f"The classes {quoted} differ only in capitalization and will be "
                    f"treated as separate classes.")

        return {
            'carriers': carriers, 'fixed': fixed, 'varied': varied,
            'reactions': reactions if groups else 0,
            'varied_wells': {k for m in varied.values() for k, _d in m},
            'errors': errors, 'warnings': warnings,
        }

    def _refresh_summary(self):
        body = getattr(self, '_summary_body', None)
        if body is None:
            return
        for w in body.winfo_children():
            w.destroy()
        self._wrap_labels = []

        C = self._C
        F = 'Segoe UI'
        if not self._wells:
            tk.Label(body, text="Click a well to assign a chemical.", bg=C['surface'],
                     fg=C['text2'], font=(F, 9)).grid(row=0, column=0, sticky='w')
            return

        s = self._screen_summary()

        def well_label(d, cls):
            name = d.get('chemical_name', '')
            return name if cls == name else f"{name} ({cls})"

        lines = [("Carrier", ', '.join(s['carriers']) or "none")]
        lines.append(("Fixed", '  ·  '.join(
            well_label(m[0][1], c) for c, m in s['fixed'].items()) or "none"))
        if s['varied']:
            for i, (cls, members) in enumerate(s['varied'].items()):
                names = ', '.join(d.get('chemical_name', '') for _k, d in members)
                lines.append(("Varied" if i == 0 else "",
                              f"{cls}:  {names}   (×{len(members)})"))
        else:
            lines.append(("Varied", "none — every droplet is the same reaction"))

        r = 0
        for label, text in lines:
            tk.Label(body, text=label, bg=C['surface'], fg=C['text2'],
                     font=(F, 9, 'bold')).grid(row=r, column=0, sticky='nw', padx=(0, 12))
            tk.Label(body, text=text, bg=C['surface'], fg=C['text'], font=(F, 9),
                     justify='left', wraplength=700).grid(row=r, column=1, sticky='w')
            r += 1

        try:
            repeats = int(self._repeats_var.get()) if self._repeats_var is not None else None
        except (tk.TclError, ValueError):
            repeats = None
        n = s['reactions']
        sizes = [len(m) for m in s['varied'].values()]
        total = f"{' × '.join(map(str, sizes))} = " if len(sizes) > 1 else ""
        total += f"{n} reaction{'' if n == 1 else 's'}"
        if repeats is not None:
            total += f"  ×  {repeats} repeats  =  {n * repeats} droplets"
        ttk.Separator(body, orient='horizontal').grid(
            row=r, column=0, columnspan=2, sticky='ew', pady=4)
        tk.Label(body, text=total, bg=C['surface'], fg=C['accent'],
                 font=(F, 10, 'bold')).grid(row=r + 1, column=0, columnspan=2, sticky='w')
        r += 2

        banners = [
            (s['errors'], "G-code cannot be generated until the following is resolved:",
             '#FDECEA', '#B3261E'),
            (s['warnings'], "Please review. G-code can still be generated:",
             '#FFF4CE', '#7A5A00'),
        ]
        for msgs, title, bg, fg in banners:
            if not msgs:
                continue
            box = tk.Frame(body, bg=bg, padx=10, pady=6)
            box.grid(row=r, column=0, columnspan=2, sticky='ew', pady=(6, 0))
            tk.Label(box, text=f"⚠  {title}", bg=bg, fg=fg, font=(F, 9, 'bold'),
                     anchor='w').pack(fill='x')
            for msg in msgs:
                lbl = tk.Label(box, text=f"•  {msg}", bg=bg, fg=fg, font=(F, 9),
                               justify='left', anchor='w')
                lbl.pack(fill='x', padx=(14, 0), pady=(2, 0))
                self._wrap_labels.append(lbl)
            r += 1
        self._rewrap_summary()

    def _rewrap_summary(self, _e=None):
        """Wrap warning text to the summary panel's current width."""
        width = self._summary_body.winfo_width()
        if width < 50:
            return
        for lbl in self._wrap_labels:
            if lbl.winfo_exists():
                lbl.configure(wraplength=width - 50)

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
                    entry = {
                        'chemical_name': str(row['chemical_name']),
                        'class':         str(row['class']),
                    }
                    color = row.get('color')
                    norm = _ColorPickerDialog._normalize_hex(
                        str(color)) if pd.notna(color) else None
                    if norm:
                        entry['color'] = norm
                    role = str(row.get('role', '')).strip().lower()
                    if role in ('fixed', 'varied'):
                        entry['role'] = role
                    self._wells[(ri, ci)] = entry
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
        varied = self._screen_summary()['varied_wells']
        for (ri, ci), d in sorted(self._wells.items()):
            x = self._ox_var.get() + ci * self._sx_var.get()
            y = self._oy_var.get() + ri * self._sy_var.get()
            if _is_aux_class(d.get('class', '')):
                role = 'carrier' if _is_carrier_class(d.get('class', '')) else 'other'
            else:
                role = 'varied' if (ri, ci) in varied else 'fixed'
            rows.append({
                'plate_row':     string.ascii_uppercase[ri],
                'plate_column':  ci + 1,
                'chemical_name': d.get('chemical_name', ''),
                'class':         d.get('class', ''),
                'role':          role,
                'color':         d.get('color', ''),
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
        names = _list_presets(GEOMETRY_PRESETS_DIR)
        self._geo_cb['values'] = names
        if names and self._geo_pvar.get() not in names:
            self._geo_pvar.set(names[0])

    def _load_geo(self):
        n = self._geo_pvar.get()
        p = _load_preset(GEOMETRY_PRESETS_DIR, n)
        if p is None:
            messagebox.showerror("Error", f"Geometry preset '{n}' not found.",
                                 parent=self.winfo_toplevel())
            return
        rows, cols = p['rows'], p['cols']
        self._rows_var.set(rows)
        self._cols_var.set(cols)
        self._sx_var.set(p['spacing_x'])
        self._sy_var.set(p['spacing_y'])
        self._ox_var.set(p.get('origin_x', 0.0))
        self._oy_var.set(p.get('origin_y', 0.0))
        matched = _matching_plate_size(rows, cols)
        if matched:
            self._size_var.set(matched)
            self._rows_entry.configure(state='disabled')
            self._cols_entry.configure(state='disabled')
        else:
            self._size_var.set('Custom')
            self._rows_entry.configure(state='normal')
            self._cols_entry.configure(state='normal')
        self._apply_config()
        self._log(f"Plate Editor: loaded geometry preset '{n}'")

    def _save_geo(self):
        os.makedirs(GEOMETRY_PRESETS_DIR, exist_ok=True)
        path = filedialog.asksaveasfilename(
            title="Save Geometry Preset", initialdir=GEOMETRY_PRESETS_DIR,
            initialfile=self._geo_pvar.get(),
            defaultextension='.json', filetypes=[('JSON', '*.json')],
            parent=self.winfo_toplevel())
        if not path:
            return
        data = {
            'rows': int(self._rows_var.get()), 'cols': int(self._cols_var.get()),
            'spacing_x': self._sx_var.get(),   'spacing_y': self._sy_var.get(),
            'origin_x':  self._ox_var.get(),   'origin_y':  self._oy_var.get(),
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        n = os.path.splitext(os.path.basename(path))[0]
        self._refresh_geo_cb()
        self._geo_pvar.set(n)
        self._log(f"Plate Editor: saved geometry preset '{n}'")

    def _del_geo(self):
        n = self._geo_pvar.get()
        if n and n in _list_presets(GEOMETRY_PRESETS_DIR):
            if messagebox.askyesno("Delete", f"Delete geometry preset '{n}'?",
                                   parent=self.winfo_toplevel()):
                _delete_preset(GEOMETRY_PRESETS_DIR, n)
                self._geo_pvar.set('')
                self._refresh_geo_cb()
                self._log(f"Plate Editor: deleted geometry preset '{n}'")

    # ── reaction presets ───────────────────────────────────────────────────────

    def _refresh_rxn_cb(self):
        names = _list_presets(RXN_PRESETS_DIR)
        self._rxn_cb['values'] = names
        if names and self._rxn_pvar.get() not in names:
            self._rxn_pvar.set(names[0])

    def _load_rxn(self):
        n = self._rxn_pvar.get()
        p = _load_preset(RXN_PRESETS_DIR, n)
        if p is None:
            messagebox.showerror("Error", f"Reaction preset '{n}' not found.",
                                 parent=self.winfo_toplevel())
            return
        self._wells = {
            (int(k.split(',')[0]), int(k.split(',')[1])): v
            for k, v in p.get('wells', {}).items()
        }
        self._redraw()
        self._refresh_legend()
        self._log(f"Plate Editor: loaded reaction preset '{n}'")

    def _save_rxn(self):
        os.makedirs(RXN_PRESETS_DIR, exist_ok=True)
        path = filedialog.asksaveasfilename(
            title="Save Reaction Preset", initialdir=RXN_PRESETS_DIR,
            initialfile=self._rxn_pvar.get(),
            defaultextension='.json', filetypes=[('JSON', '*.json')],
            parent=self.winfo_toplevel())
        if not path:
            return
        data = {
            'wells': {f'{ri},{ci}': d for (ri, ci), d in self._wells.items()}
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        n = os.path.splitext(os.path.basename(path))[0]
        self._refresh_rxn_cb()
        self._rxn_pvar.set(n)
        self._log(f"Plate Editor: saved reaction preset '{n}'")

    def _del_rxn(self):
        n = self._rxn_pvar.get()
        if n and n in _list_presets(RXN_PRESETS_DIR):
            if messagebox.askyesno("Delete", f"Delete reaction preset '{n}'?",
                                   parent=self.winfo_toplevel()):
                _delete_preset(RXN_PRESETS_DIR, n)
                self._rxn_pvar.set('')
                self._refresh_rxn_cb()
                self._log(f"Plate Editor: deleted reaction preset '{n}'")
