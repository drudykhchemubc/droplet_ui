import datetime
import json
import os
import queue
import random
import threading
import time

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext

import pandas as pd
import serial

from dropdown_autocomplete import bind_typeahead
from gcode_generator import Screen
from cnc_hardware import cnc_connect, cnc_send, pump_connect
from plate_editor import PlateEditor
from animated_tab_design import SmoothNotebook
from time_estimate import format_estimate, parse_move, segment_time

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

CONFIG_PATH           = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'microdroplet_config.json')
LOADING_DIR           = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'loading_images_git')
SETTINGS_PRESETS_DIR  = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings_presets')
DEFAULT_GCODE_DIR     = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'gcode_output')
DEFAULT_COMBO_DIR     = os.path.join(DEFAULT_GCODE_DIR, 'combinations')


class MicrodropletApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Microdroplet Screen Controller")
        self.root.state('zoomed')
        self.root.minsize(900, 640)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.screen: Screen | None = None
        self.gcode_lines: list | None = None
        self.cnc: serial.Serial | None = None
        self.pump: serial.Serial | None = None
        self.plate_editor: PlateEditor | None = None
        self._stop_event = threading.Event()
        self._pause_event = threading.Event()
        self._log_queue: queue.Queue = queue.Queue()
        self._gif_frames: list = []
        self._gif_after_id = None
        self._poll_log_job = None

        self._defaults = dict(
            pfd_dwell=3.2, organic_dwell=0.4, pause=0.5, repeats=10, feedrate=2000,
            max_rate_x=2000.0, max_rate_y=500.0, max_rate_z=500.0,
            accel_x=10.0, accel_y=10.0, accel_z=10.0,
        )

        self.pfd_dwell_var = tk.DoubleVar(value=self._defaults['pfd_dwell'])
        self.organic_dwell_var = tk.DoubleVar(value=self._defaults['organic_dwell'])
        self.pause_var = tk.DoubleVar(value=self._defaults['pause'])
        self.repeats_var = tk.IntVar(value=self._defaults['repeats'])
        self.feedrate_var = tk.IntVar(value=self._defaults['feedrate'])
        self.max_rate_x_var = tk.DoubleVar(value=self._defaults['max_rate_x'])
        self.max_rate_y_var = tk.DoubleVar(value=self._defaults['max_rate_y'])
        self.max_rate_z_var = tk.DoubleVar(value=self._defaults['max_rate_z'])
        self.accel_x_var = tk.DoubleVar(value=self._defaults['accel_x'])
        self.accel_y_var = tk.DoubleVar(value=self._defaults['accel_y'])
        self.accel_z_var = tk.DoubleVar(value=self._defaults['accel_z'])
        self.settings_preset_var = tk.StringVar()
        self.preset_dirty_var = tk.StringVar(value='')
        self._preset_dirty = False
        self.csv_path_var = tk.StringVar()
        self.gcode_name_var = tk.StringVar(value='plate_editor')
        self.gcode_folder_var = tk.StringVar(value=DEFAULT_GCODE_DIR)
        self.combo_folder_var = tk.StringVar(value=DEFAULT_COMBO_DIR)
        self.gcode_path_var = tk.StringVar()
        self.combo_path_var = tk.StringVar()
        self.cnc_port_var = tk.StringVar(value="COM5")
        self.pump_port_var = tk.StringVar(value="COM3")
        self.cnc_baud_var = tk.StringVar(value="115200")
        self.pump_baud_var = tk.StringVar(value="9600")
        self.status_var = tk.StringVar(value="Ready")
        self.droplet_count_var = tk.StringVar(value="—")
        self.progress_label_var = tk.StringVar(value="No run in progress.")
        self.progress_var = tk.DoubleVar()
        self.time_estimate_var = tk.StringVar(value="")

        self._load_config()
        self._ensure_default_preset()
        self._bind_preset_dirty_tracking()
        self._build_ui()
        self._poll_log()

    # ── UI construction ────────────────────────────────────────────────────────

    def _setup_style(self):
        C = {
            'bg':      '#F2F2F7',
            'surface': '#FFFFFF',
            'accent':  '#007AFF',
            'success': '#34C759',
            'danger':  '#FF3B30',
            'text':    '#1D1D1F',
            'text2':   '#8E8E93',
            'border':  '#C6C6C8',
            'fill':    '#E5E5EA',
            'fill2':   '#D1D1D6',
            'log_bg':  '#1C1C1E',
            'log_fg':  '#E5E5EA',
        }
        self._C = C
        F = 'Segoe UI'

        s = ttk.Style()
        s.theme_use('clam')

        self.root.configure(bg=C['bg'])

        s.configure('.', background=C['bg'], foreground=C['text'], font=(F, 10))
        s.configure('TFrame', background=C['bg'])
        s.configure('Surface.TFrame', background=C['surface'])

        s.configure('TLabelframe', background=C['surface'],
                    bordercolor=C['border'], relief='flat', borderwidth=1)
        s.configure('TLabelframe.Label', background=C['surface'],
                    foreground=C['text2'], font=(F, 8, 'bold'), padding=(6, 0))

        s.configure('TLabel', background=C['bg'], foreground=C['text'], font=(F, 10))
        s.configure('Card.TLabel', background=C['surface'], foreground=C['text'], font=(F, 10))
        s.configure('Muted.TLabel', background=C['surface'], foreground=C['text2'], font=(F, 9))
        s.configure('Count.TLabel', background=C['surface'], foreground=C['accent'],
                    font=(F, 13, 'bold'))
        s.configure('Dirty.TLabel', background=C['surface'], foreground=C['danger'],
                    font=(F, 13, 'bold'))
        s.configure('Status.TLabel', background=C['bg'], foreground=C['text2'],
                    font=(F, 9))

        s.configure('TEntry', fieldbackground=C['surface'], foreground=C['text'],
                    bordercolor=C['border'], lightcolor=C['border'], darkcolor=C['border'],
                    insertcolor=C['text'], font=(F, 10), padding=(6, 5))
        s.map('TEntry',
              fieldbackground=[('readonly', C['fill']), ('disabled', C['fill'])],
              foreground=[('readonly', C['text2']), ('disabled', C['text2'])])

        s.configure('TButton', background=C['surface'], foreground=C['text'],
                    font=(F, 10), padding=(12, 6), relief='flat',
                    bordercolor=C['border'], lightcolor=C['border'], darkcolor=C['border'],
                    borderwidth=1)
        s.map('TButton',
              background=[('active', C['fill']), ('pressed', C['fill2']),
                          ('disabled', C['fill'])],
              foreground=[('disabled', C['text2'])])

        s.configure('Accent.TButton', background=C['accent'], foreground='#FFFFFF',
                    font=(F, 10, 'bold'), padding=(14, 7), relief='flat',
                    borderwidth=0, bordercolor=C['accent'],
                    lightcolor=C['accent'], darkcolor=C['accent'])
        s.map('Accent.TButton',
              background=[('active', '#0066DD'), ('pressed', '#0051CC'),
                          ('disabled', C['fill2'])],
              foreground=[('disabled', C['text2'])])

        s.configure('Danger.TButton', background=C['danger'], foreground='#FFFFFF',
                    font=(F, 10), padding=(12, 6), relief='flat',
                    borderwidth=0, bordercolor=C['danger'],
                    lightcolor=C['danger'], darkcolor=C['danger'])
        s.map('Danger.TButton',
              background=[('active', '#D93228'), ('pressed', '#BF2B22'),
                          ('disabled', C['fill2'])],
              foreground=[('disabled', C['text2'])])

        s.configure('Ghost.TButton', background=C['bg'], foreground=C['accent'],
                    font=(F, 10), padding=(8, 5), relief='flat', borderwidth=0)
        s.map('Ghost.TButton',
              background=[('active', C['fill']), ('pressed', C['fill2'])])

        s.configure('TProgressbar', background=C['accent'], troughcolor=C['fill'],
                    borderwidth=0, thickness=8, relief='flat',
                    lightcolor=C['accent'], darkcolor=C['accent'])

        s.configure('TSeparator', background=C['border'])

        s.configure('TScrollbar', background=C['fill2'], troughcolor=C['fill'],
                    borderwidth=0, arrowsize=0, relief='flat')
        s.map('TScrollbar', background=[('active', C['text2'])])

    def _make_scrollable(self, parent):
        """Return a scrollable inner frame. Pack all tab content into it."""
        C = self._C
        canvas = tk.Canvas(parent, bg=C['bg'], highlightthickness=0, bd=0)
        sb = ttk.Scrollbar(parent, orient='vertical', command=canvas.yview)
        inner = ttk.Frame(canvas, padding=(16, 12))
        win_id = canvas.create_window((0, 0), window=inner, anchor='nw')

        canvas.configure(yscrollcommand=sb.set)
        inner.bind('<Configure>',
                   lambda _e: canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',
                    lambda e: canvas.itemconfig(win_id, width=e.width))

        def _on_wheel(e):
            canvas.yview_scroll(int(-1 * (e.delta / 120)), 'units')

        canvas.bind('<MouseWheel>', _on_wheel)
        inner.bind('<MouseWheel>', _on_wheel)

        sb.pack(side=tk.RIGHT, fill=tk.Y)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        return inner, canvas

    def _build_ui(self):
        self._setup_style()
        C = self._C

        status_bar = tk.Frame(self.root, bg=C['fill'], height=26)
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)
        status_bar.pack_propagate(False)
        tk.Label(status_bar, textvariable=self.status_var, bg=C['fill'],
                 fg=C['text2'], font=('Segoe UI', 9),
                 anchor='w', padx=12).pack(side=tk.LEFT, fill=tk.Y)

        log_outer = tk.Frame(self.root, bg=C['log_bg'])
        log_outer.pack(fill=tk.X, side=tk.BOTTOM)

        log_header = tk.Frame(log_outer, bg='#2C2C2E', height=28)
        log_header.pack(fill=tk.X)
        log_header.pack_propagate(False)
        tk.Label(log_header, text="LOG", bg='#2C2C2E', fg='#8E8E93',
                 font=('Segoe UI', 8, 'bold'), anchor='w',
                 padx=12).pack(side=tk.LEFT, fill=tk.Y)

        self.log_text = scrolledtext.ScrolledText(
            log_outer, height=8, state='disabled', font=('Consolas', 9),
            wrap=tk.WORD, bg=C['log_bg'], fg=C['log_fg'],
            insertbackground=C['log_fg'], selectbackground='#48484A',
            selectforeground=C['log_fg'], relief='flat', borderwidth=0,
            padx=10, pady=6)
        self.log_text.pack(fill=tk.X)

        nb = SmoothNotebook(self.root, C)
        nb.pack(fill=tk.BOTH, expand=True)

        cfg_host = ttk.Frame(nb._body)
        nb.add(cfg_host, text="Configure")
        self._build_configure_tab(cfg_host)

        run = ttk.Frame(nb._body, padding=(16, 12))
        nb.add(run, text="Run")
        self._build_run_tab(run)

    def _bind_scroll(self, widget, canvas):
        """Recursively bind mousewheel on all children to scroll the canvas."""
        widget.bind('<MouseWheel>',
                    lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), 'units'),
                    add='+')
        for child in widget.winfo_children():
            self._bind_scroll(child, canvas)

    def _build_configure_tab(self, parent):
        """Two-panel Configure tab: scrollable params left, plate editor right."""
        C = self._C
        parent.columnconfigure(0, minsize=420, weight=0)
        parent.columnconfigure(2, weight=1)
        parent.rowconfigure(0, weight=1)

        left_host = tk.Frame(parent, bg=C['bg'])
        left_host.grid(row=0, column=0, sticky='nsew')

        ttk.Separator(parent, orient='vertical').grid(row=0, column=1, sticky='ns')

        right_host = ttk.Frame(parent)
        right_host.grid(row=0, column=2, sticky='nsew')

        left_inner, left_canvas = self._make_scrollable(left_host)
        self._build_left_controls(left_inner, left_canvas)

        self.plate_editor = PlateEditor(right_host, self._C, log_cb=self._log)
        self.plate_editor.pack(fill=tk.BOTH, expand=True)

    def _build_left_controls(self, parent, scroll_canvas=None):
        sp = ttk.LabelFrame(parent, text="SETTINGS PRESETS", padding=(14, 10))
        sp.pack(fill=tk.X, pady=(0, 8))

        preset_row = ttk.Frame(sp, style='Surface.TFrame')
        preset_row.pack(fill=tk.X)
        self.settings_preset_cb = ttk.Combobox(preset_row, textvariable=self.settings_preset_var, width=16)
        self.settings_preset_cb.pack(side=tk.LEFT, padx=(0, 4))
        self.settings_preset_cb.bind('<<ComboboxSelected>>',
                                     lambda _e: self._load_settings_preset())
        bind_typeahead(self.settings_preset_cb)
        ttk.Label(preset_row, textvariable=self.preset_dirty_var, style='Dirty.TLabel',
                  width=1).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(preset_row, text="Save As…", style='Ghost.TButton',
                   command=self._save_settings_preset).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(preset_row, text="Apply", style='Accent.TButton',
                   command=self._load_settings_preset).pack(side=tk.LEFT)
        self._refresh_settings_preset_cb()
        current = self.settings_preset_var.get()
        if not current or current not in self.settings_preset_cb['values']:
            self.settings_preset_var.set('default')
        self._clear_preset_dirty()

        pf = ttk.LabelFrame(parent, text="PARAMETERS", padding=(14, 10))
        pf.pack(fill=tk.X, pady=(0, 8))
        pf.columnconfigure(1, weight=1)
        param_fields = [
            ("PFD Dwell Time (s)", self.pfd_dwell_var),
            ("Organic Dwell Time (s)", self.organic_dwell_var),
            ("Pause After Pump Stop (s)", self.pause_var),
            ("Droplet Multiplicity", self.repeats_var),
            ("Motor Feedrate (mm/min)", self.feedrate_var),
        ]
        for i, (lbl, var) in enumerate(param_fields):
            ttk.Label(pf, text=lbl, style='Card.TLabel').grid(
                row=i, column=0, sticky='e', padx=(0, 10), pady=3)
            ttk.Entry(pf, textvariable=var, width=8).grid(
                row=i, column=1, sticky='ew', pady=3)

        mf = ttk.LabelFrame(parent, text="MACHINE SETTINGS  ($110–$122)", padding=(14, 10))
        mf.pack(fill=tk.X, pady=(0, 8))
        mf.columnconfigure(1, weight=1)
        machine_fields = [
            ("X Max Rate (mm/min)", self.max_rate_x_var),
            ("Y Max Rate (mm/min)", self.max_rate_y_var),
            ("Z Max Rate (mm/min)", self.max_rate_z_var),
            ("X Acceleration (mm/s²)", self.accel_x_var),
            ("Y Acceleration (mm/s²)", self.accel_y_var),
            ("Z Acceleration (mm/s²)", self.accel_z_var),
        ]
        for i, (lbl, var) in enumerate(machine_fields):
            ttk.Label(mf, text=lbl, style='Card.TLabel').grid(
                row=i, column=0, sticky='e', padx=(0, 10), pady=3)
            ttk.Entry(mf, textvariable=var, width=8).grid(
                row=i, column=1, sticky='ew', pady=3)
        ttk.Button(mf, text="Reset to Defaults", style='Ghost.TButton',
                   command=self._reset_params).grid(
            row=len(machine_fields), column=0, columnspan=2, sticky='w', pady=(6, 0))

        of = ttk.LabelFrame(parent, text="OUTPUT LOCATIONS", padding=(14, 10))
        of.pack(fill=tk.X, pady=(0, 10))
        of.columnconfigure(0, weight=1)
        for idx, (lbl, var, cmd) in enumerate([
            ("G-code folder", self.gcode_folder_var, self._browse_gcode_folder),
            ("Combinations CSV folder", self.combo_folder_var, self._browse_combo_folder),
        ]):
            ttk.Label(of, text=lbl, style='Muted.TLabel').grid(
                row=idx * 2, column=0, columnspan=2, sticky='w',
                pady=(8 if idx > 0 else 0, 2))
            ent = ttk.Entry(of, textvariable=var)
            ent.grid(row=idx * 2 + 1, column=0, sticky='ew')
            ttk.Button(of, text="Browse…", style='Ghost.TButton', command=cmd).grid(
                row=idx * 2 + 1, column=1, padx=(6, 0))
            # scroll entry to end so the tail of long paths stays visible
            var.trace_add('write', lambda *_, e=ent: e.after(10, lambda: e.xview_moveto(1)))
            ent.after(10, lambda e=ent: e.xview_moveto(1))

        gf = ttk.LabelFrame(parent, text="G-CODE", padding=(14, 10))
        gf.pack(fill=tk.X)

        ttk.Label(gf, text="File name", style='Muted.TLabel').pack(anchor='w', pady=(0, 2))
        ttk.Entry(gf, textvariable=self.gcode_name_var).pack(fill=tk.X, pady=(0, 8))

        btn_row = ttk.Frame(gf, style='Surface.TFrame')
        btn_row.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(btn_row, text="Generate G-code", style='Accent.TButton',
                   command=self._initialize_from_editor).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(btn_row, text="Load .txt file…", style='Ghost.TButton',
                   command=self._load_gcode_file).pack(side=tk.LEFT)

        count_row = ttk.Frame(gf, style='Surface.TFrame')
        count_row.pack(fill=tk.X, pady=(0, 6))
        ttk.Label(count_row, text="Total droplets:", style='Muted.TLabel').pack(side=tk.LEFT)
        ttk.Label(count_row, textvariable=self.droplet_count_var,
                  style='Count.TLabel').pack(side=tk.LEFT, padx=(8, 0))

        ttk.Label(gf, text="G-code file", style='Muted.TLabel').pack(anchor='w', pady=(0, 2))
        gcode_path_ent = ttk.Entry(gf, textvariable=self.gcode_path_var, state='readonly')
        gcode_path_ent.pack(fill=tk.X)
        ttk.Label(gf, text="Combinations CSV", style='Muted.TLabel').pack(anchor='w', pady=(6, 2))
        combo_path_ent = ttk.Entry(gf, textvariable=self.combo_path_var, state='readonly')
        combo_path_ent.pack(fill=tk.X)
        for var, e in ((self.gcode_path_var, gcode_path_ent), (self.combo_path_var, combo_path_ent)):
            var.trace_add('write', lambda *_, e=e: e.after(10, lambda: e.xview_moveto(1)))

    def _device_section(self, parent, label, port_var, baud_var, connect_cb):
        C = self._C
        frame = ttk.LabelFrame(parent, text=label.upper(), padding=(14, 10))
        frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))
        ttk.Label(frame, text="Port", style='Muted.TLabel').grid(
            row=0, column=0, sticky='e', padx=(0, 8), pady=4)
        ttk.Entry(frame, textvariable=port_var, width=8).grid(
            row=0, column=1, sticky='w', pady=4)
        ttk.Label(frame, text="Baud", style='Muted.TLabel').grid(
            row=1, column=0, sticky='e', padx=(0, 8), pady=4)
        ttk.Entry(frame, textvariable=baud_var, width=10).grid(
            row=1, column=1, sticky='w', pady=4)
        ttk.Button(frame, text="Connect", style='Accent.TButton',
                   command=connect_cb).grid(row=0, column=2, rowspan=2, padx=(14, 0))
        status = tk.Label(frame, text="● Disconnected",
                          bg=C['surface'], fg=C['danger'],
                          font=('Segoe UI', 9))
        status.grid(row=0, column=3, rowspan=2, padx=(12, 0))
        return status

    def _build_run_tab(self, parent):
        ttk.Label(parent, text="HARDWARE", style='Status.TLabel').pack(
            anchor='w', pady=(0, 6))
        devices_row = ttk.Frame(parent)
        devices_row.pack(fill=tk.X, pady=(0, 4))
        self.cnc_status_lbl = self._device_section(
            devices_row, "CNC Controller",
            self.cnc_port_var, self.cnc_baud_var, self._connect_cnc)
        self.pump_status_lbl = self._device_section(
            devices_row, "Pump",
            self.pump_port_var, self.pump_baud_var, self._connect_pump)
        conn_btn_row = ttk.Frame(parent)
        conn_btn_row.pack(anchor='w', pady=(6, 14))
        ttk.Button(conn_btn_row, text="Connect All", style='Accent.TButton',
                   command=self._connect_all).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(conn_btn_row, text="Disconnect All", style='Danger.TButton',
                   command=self._disconnect_all).pack(side=tk.LEFT)

        ttk.Separator(parent, orient='horizontal').pack(fill=tk.X, pady=(0, 14))

        ttk.Label(parent, text="CONTROLS", style='Status.TLabel').pack(
            anchor='w', pady=(0, 6))
        ctrl = ttk.LabelFrame(parent, text="", padding=(14, 10))
        ctrl.pack(fill=tk.X, pady=(0, 14))
        self.zero_btn = ttk.Button(ctrl, text="Zero CNC (G92)", command=self._zero_cnc)
        self.zero_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.start_btn = ttk.Button(ctrl, text="▶  Start", style='Accent.TButton',
                                    command=self._start_run, state='disabled')
        self.start_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.pause_btn = ttk.Button(ctrl, text="⏸  Pause",
                                    command=self._toggle_pause, state='disabled')
        self.pause_btn.pack(side=tk.LEFT, padx=(0, 8))
        self.stop_btn = ttk.Button(ctrl, text="⏹  Stop", style='Danger.TButton',
                                   command=self._stop_run, state='disabled')
        self.stop_btn.pack(side=tk.LEFT)

        ttk.Label(parent, text="PROGRESS", style='Status.TLabel').pack(
            anchor='w', pady=(0, 6))
        prog = ttk.LabelFrame(parent, text="", padding=(14, 12))
        prog.pack(fill=tk.X)
        ttk.Label(prog, textvariable=self.progress_label_var,
                  style='Card.TLabel').pack(anchor='w', pady=(0, 6))
        self.progress_bar = ttk.Progressbar(prog, variable=self.progress_var)
        self.progress_bar.pack(fill=tk.X)
        ttk.Label(prog, textvariable=self.time_estimate_var,
                  style='Muted.TLabel').pack(anchor='w', pady=(6, 0))
        self._gif_label = tk.Label(prog, bg='#FFFFFF', bd=0, highlightthickness=0)
        self._gif_label.pack(pady=(10, 0))

    # ── Configure handlers ─────────────────────────────────────────────────────

    def _reset_params(self):
        self.pfd_dwell_var.set(self._defaults['pfd_dwell'])
        self.organic_dwell_var.set(self._defaults['organic_dwell'])
        self.pause_var.set(self._defaults['pause'])
        self.repeats_var.set(self._defaults['repeats'])
        self.feedrate_var.set(self._defaults['feedrate'])
        self.max_rate_x_var.set(self._defaults['max_rate_x'])
        self.max_rate_y_var.set(self._defaults['max_rate_y'])
        self.max_rate_z_var.set(self._defaults['max_rate_z'])
        self.accel_x_var.set(self._defaults['accel_x'])
        self.accel_y_var.set(self._defaults['accel_y'])
        self.accel_z_var.set(self._defaults['accel_z'])

    def _ensure_default_preset(self):
        """Guarantee a 'default' preset exists so the picker never starts empty."""
        os.makedirs(SETTINGS_PRESETS_DIR, exist_ok=True)
        path = os.path.join(SETTINGS_PRESETS_DIR, 'default.json')
        if not os.path.exists(path):
            with open(path, 'w') as f:
                json.dump(self._defaults, f, indent=2)

    def _preset_field_vars(self):
        return [
            self.pfd_dwell_var, self.organic_dwell_var, self.pause_var,
            self.repeats_var, self.feedrate_var,
            self.max_rate_x_var, self.max_rate_y_var, self.max_rate_z_var,
            self.accel_x_var, self.accel_y_var, self.accel_z_var,
        ]

    def _bind_preset_dirty_tracking(self):
        for var in self._preset_field_vars():
            var.trace_add('write', self._mark_preset_dirty)

    def _mark_preset_dirty(self, *_args):
        if not self._preset_dirty:
            self._preset_dirty = True
            self.preset_dirty_var.set('*')

    def _clear_preset_dirty(self):
        self._preset_dirty = False
        self.preset_dirty_var.set('')

    def _refresh_settings_preset_cb(self):
        os.makedirs(SETTINGS_PRESETS_DIR, exist_ok=True)
        names = sorted(
            os.path.splitext(f)[0] for f in os.listdir(SETTINGS_PRESETS_DIR)
            if f.endswith('.json')
        )
        self.settings_preset_cb['values'] = names

    def _save_settings_preset(self):
        os.makedirs(SETTINGS_PRESETS_DIR, exist_ok=True)
        path = filedialog.asksaveasfilename(
            title="Save Settings Preset", initialdir=SETTINGS_PRESETS_DIR,
            initialfile=self.settings_preset_var.get(),
            defaultextension='.json', filetypes=[('JSON', '*.json')])
        if not path:
            return
        if (os.path.normcase(os.path.dirname(os.path.abspath(path))) == os.path.normcase(SETTINGS_PRESETS_DIR)
                and os.path.splitext(os.path.basename(path))[0].lower() == 'default'):
            messagebox.showerror(
                "Protected Preset",
                "'default' is a protected preset and can't be overwritten. "
                "Please save with a different name.")
            return
        data = {
            'pfd_dwell': self.pfd_dwell_var.get(),
            'organic_dwell': self.organic_dwell_var.get(),
            'pause': self.pause_var.get(),
            'repeats': self.repeats_var.get(),
            'feedrate': self.feedrate_var.get(),
            'max_rate_x': self.max_rate_x_var.get(),
            'max_rate_y': self.max_rate_y_var.get(),
            'max_rate_z': self.max_rate_z_var.get(),
            'accel_x': self.accel_x_var.get(),
            'accel_y': self.accel_y_var.get(),
            'accel_z': self.accel_z_var.get(),
        }
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        name = os.path.splitext(os.path.basename(path))[0]
        self._refresh_settings_preset_cb()
        self.settings_preset_var.set(name)
        self._clear_preset_dirty()
        self._save_config()
        self._log(f"Settings preset saved: {name}")

    def _load_settings_preset(self):
        name = self.settings_preset_var.get()
        path = os.path.join(SETTINGS_PRESETS_DIR, f"{name}.json")
        if not name or not os.path.exists(path):
            messagebox.showerror("Error", f"Preset '{name}' not found.")
            return
        with open(path) as f:
            data = json.load(f)
        self.pfd_dwell_var.set(data.get('pfd_dwell', self._defaults['pfd_dwell']))
        self.organic_dwell_var.set(data.get('organic_dwell', self._defaults['organic_dwell']))
        self.pause_var.set(data.get('pause', self._defaults['pause']))
        self.repeats_var.set(data.get('repeats', self._defaults['repeats']))
        self.feedrate_var.set(data.get('feedrate', self._defaults['feedrate']))
        self.max_rate_x_var.set(data.get('max_rate_x', self._defaults['max_rate_x']))
        self.max_rate_y_var.set(data.get('max_rate_y', self._defaults['max_rate_y']))
        self.max_rate_z_var.set(data.get('max_rate_z', self._defaults['max_rate_z']))
        self.accel_x_var.set(data.get('accel_x', self._defaults['accel_x']))
        self.accel_y_var.set(data.get('accel_y', self._defaults['accel_y']))
        self.accel_z_var.set(data.get('accel_z', self._defaults['accel_z']))
        self.settings_preset_var.set(name)
        self._clear_preset_dirty()
        self._save_config()
        self._log(f"Settings preset loaded: {name}")

    def _browse_gcode_folder(self):
        folder = filedialog.askdirectory(title="Select G-code output folder")
        if folder:
            self.gcode_folder_var.set(folder)
            self._save_config()

    def _browse_combo_folder(self):
        folder = filedialog.askdirectory(title="Select Combinations CSV output folder")
        if folder:
            self.combo_folder_var.set(folder)
            self._save_config()

    def _load_config(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r') as f:
                    cfg = json.load(f)
                self.gcode_folder_var.set(cfg.get('gcode_folder', DEFAULT_GCODE_DIR))
                self.combo_folder_var.set(cfg.get('combo_folder', DEFAULT_COMBO_DIR))
                self.csv_path_var.set(cfg.get('csv_path', ''))
                self.gcode_name_var.set(cfg.get('gcode_name', 'plate_editor'))
                self.settings_preset_var.set(cfg.get('settings_preset', ''))
                self.pfd_dwell_var.set(cfg.get('pfd_dwell', self._defaults['pfd_dwell']))
                self.organic_dwell_var.set(cfg.get('organic_dwell', self._defaults['organic_dwell']))
                self.pause_var.set(cfg.get('pause', self._defaults['pause']))
                self.repeats_var.set(cfg.get('repeats', self._defaults['repeats']))
                self.feedrate_var.set(cfg.get('feedrate', self._defaults['feedrate']))
                self.cnc_port_var.set(cfg.get('cnc_port', 'COM5'))
                self.pump_port_var.set(cfg.get('pump_port', 'COM3'))
                self.cnc_baud_var.set(cfg.get('cnc_baud', '115200'))
                self.pump_baud_var.set(cfg.get('pump_baud', '9600'))
                self.max_rate_x_var.set(cfg.get('max_rate_x', self._defaults['max_rate_x']))
                self.max_rate_y_var.set(cfg.get('max_rate_y', self._defaults['max_rate_y']))
                self.max_rate_z_var.set(cfg.get('max_rate_z', self._defaults['max_rate_z']))
                self.accel_x_var.set(cfg.get('accel_x', self._defaults['accel_x']))
                self.accel_y_var.set(cfg.get('accel_y', self._defaults['accel_y']))
                self.accel_z_var.set(cfg.get('accel_z', self._defaults['accel_z']))
            except Exception:
                pass

    def _save_config(self):
        try:
            existing = {}
            if os.path.exists(CONFIG_PATH):
                try:
                    with open(CONFIG_PATH, 'r') as f:
                        existing = json.load(f)
                except Exception:
                    pass
            existing.update({
                'gcode_folder': self.gcode_folder_var.get(),
                'combo_folder': self.combo_folder_var.get(),
                'csv_path': self.csv_path_var.get(),
                'gcode_name': self.gcode_name_var.get(),
                'settings_preset': self.settings_preset_var.get(),
                'pfd_dwell': self.pfd_dwell_var.get(),
                'organic_dwell': self.organic_dwell_var.get(),
                'pause': self.pause_var.get(),
                'repeats': self.repeats_var.get(),
                'feedrate': self.feedrate_var.get(),
                'cnc_port': self.cnc_port_var.get(),
                'pump_port': self.pump_port_var.get(),
                'cnc_baud': self.cnc_baud_var.get(),
                'pump_baud': self.pump_baud_var.get(),
                'max_rate_x': self.max_rate_x_var.get(),
                'max_rate_y': self.max_rate_y_var.get(),
                'max_rate_z': self.max_rate_z_var.get(),
                'accel_x': self.accel_x_var.get(),
                'accel_y': self.accel_y_var.get(),
                'accel_z': self.accel_z_var.get(),
            })
            with open(CONFIG_PATH, 'w') as f:
                json.dump(existing, f, indent=2)
        except Exception:
            pass

    def _browse_csv(self):
        path = filedialog.askopenfilename(
            title="Select Well Plate CSV", filetypes=[('CSV files', '*.csv')])
        if path:
            self.csv_path_var.set(path)

    def _load_and_initialize(self):
        csv_path = self.csv_path_var.get()
        if not csv_path:
            messagebox.showerror("Error", "Select a CSV file first.")
            return
        try:
            df = pd.read_csv(csv_path)
        except Exception as e:
            messagebox.showerror("CSV Error", str(e))
            return
        self._init_screen(df, csv_path)

    def _initialize_from_editor(self):
        if self.plate_editor is None:
            return
        try:
            df = self.plate_editor.get_dataframe()
        except ValueError as e:
            messagebox.showerror("Plate Editor", str(e))
            return

        raw = self.gcode_name_var.get()
        stripped = raw.strip()
        if not stripped:
            if not messagebox.askyesno(
                    "Empty File Name",
                    "No file name was entered — the G-code will be saved as "
                    "\"plate_editor <date>.txt\".\n\nProceed with that name?"):
                return
            name = 'plate_editor'
        else:
            cleaned = self._sanitize_filename(stripped)
            if cleaned != stripped:
                if not messagebox.askyesno(
                        "Invalid Characters in File Name",
                        f"The name \"{stripped}\" contains characters that aren't "
                        f"allowed in file names.\n\nIt will be saved as "
                        f"\"{cleaned}\" instead.\n\nProceed?"):
                    return
            name = cleaned

        self.gcode_name_var.set(name)
        self._save_config()
        synthetic = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
        self._init_screen(df, synthetic)

    @staticmethod
    def _sanitize_filename(name):
        invalid = '\\/:*?"<>|'
        cleaned = ''.join(c for c in name if c not in invalid).strip()
        return cleaned or 'plate_editor'

    def _init_screen(self, df, csv_path):
        try:
            self.screen = Screen(
                dataframe=df,
                PFD_dwell=self.pfd_dwell_var.get(),
                organic_dwell=self.organic_dwell_var.get(),
                pause_after_pump_stop=self.pause_var.get(),
                repeats=self.repeats_var.get(),
                feedrate=self.feedrate_var.get(),
            )
            total = self.screen.initialize()
            self.droplet_count_var.set(str(total))
            self._log(f"Initialized — {total} droplets from {os.path.basename(csv_path)}")
            if total == 69:
                self._log("69 droplets... Nice.")
        except Exception as e:
            messagebox.showerror("Initialization Error", str(e))
            self._log(f"Init error: {e}")
            return

        try:
            self.gcode_lines = self.screen.generate_gcode()
            self._log(f"G-code generated — {len(self.gcode_lines)} lines")
        except Exception as e:
            messagebox.showerror("G-code Error", str(e))
            self._log(f"G-code error: {e}")
            return

        gcode_saved = self._autosave(
            content='\n'.join(self.gcode_lines),
            folder_var=self.gcode_folder_var,
            csv_path=csv_path,
            suffix='',
            ext='txt',
            prompt_title="Choose folder to save G-code",
        )
        if gcode_saved:
            self.gcode_path_var.set(gcode_saved)
            self._log(f"G-code saved: {gcode_saved}")

        try:
            combo_df = self.screen.get_combinations_df()
            combo_saved = self._autosave(
                content=combo_df.to_csv(),
                folder_var=self.combo_folder_var,
                csv_path=csv_path,
                suffix=' combinations',
                ext='csv',
                prompt_title="Choose folder to save Combinations CSV",
            )
            if combo_saved:
                self.combo_path_var.set(combo_saved)
                self._log(f"Combinations saved: {combo_saved}")
        except Exception as e:
            self._log(f"Combinations CSV error: {e}")

        self.time_estimate_var.set(format_estimate(
            self.gcode_lines, float(self.feedrate_var.get() or 1),
            (self.max_rate_x_var.get(), self.max_rate_y_var.get(), self.max_rate_z_var.get()),
            (self.accel_x_var.get(), self.accel_y_var.get(), self.accel_z_var.get()),
        ))
        self._set_status(f"Ready — {total} droplets")
        self.start_btn.config(state='normal')

    def _autosave(self, content, folder_var, csv_path, suffix, ext, prompt_title):
        folder = folder_var.get()
        if not folder:
            folder = filedialog.askdirectory(title=prompt_title)
            if not folder:
                self._log("  skipped — no output folder chosen")
                return None
            folder_var.set(folder)
            self._save_config()
        os.makedirs(folder, exist_ok=True)
        date = datetime.date.today().strftime('%b-%d-%Y')
        base = os.path.splitext(os.path.basename(csv_path))[0]
        filename = f"{base}{suffix} {date}.{ext}"
        full_path = os.path.join(folder, filename)
        with open(full_path, 'w') as f:
            f.write(content)
        return full_path

    def _load_gcode_file(self):
        path = filedialog.askopenfilename(
            title="Load G-code", filetypes=[('Text files', '*.txt'), ('All files', '*.*')])
        if not path:
            return
        with open(path, 'r') as f:
            self.gcode_lines = [l.strip() for l in f if l.strip()]
        self.gcode_path_var.set(path)
        self._log(f"Loaded: {len(self.gcode_lines)} lines from {os.path.basename(path)}")
        self.time_estimate_var.set(format_estimate(
            self.gcode_lines, float(self.feedrate_var.get() or 1),
            (self.max_rate_x_var.get(), self.max_rate_y_var.get(), self.max_rate_z_var.get()),
            (self.accel_x_var.get(), self.accel_y_var.get(), self.accel_z_var.get()),
        ))
        self._set_status("G-code loaded from file")
        self.start_btn.config(state='normal')

    def _view_plate(self):
        if self.screen is None:
            messagebox.showerror("Error", "Load and initialize a CSV first.")
            return
        self.screen.show_plate(self.root)

    # ── Hardware handlers ──────────────────────────────────────────────────────

    def _connect_all(self):
        self._connect_cnc()
        self._connect_pump()

    def _connect_cnc(self):
        try:
            port = self.cnc_port_var.get()
            baud = int(self.cnc_baud_var.get())
            self.cnc = cnc_connect(port, baudrate=baud, log_cb=self._log)
            self.cnc_status_lbl.config(text=f"● Connected ({port})", foreground='#34C759')
            self._log(f"CNC connected on {port} @ {baud}")
        except Exception as e:
            messagebox.showerror("CNC Connection Error", str(e))
            self._log(f"CNC error: {e}")

    def _connect_pump(self):
        try:
            port = self.pump_port_var.get()
            baud = int(self.pump_baud_var.get())
            self.pump = pump_connect(port, baudrate=baud)
            self.pump.write("pause\r".encode())
            self.pump_status_lbl.config(text=f"● Connected ({port})", foreground='#34C759')
            self._log(f"Pump connected on {port} @ {baud}")
        except Exception as e:
            messagebox.showerror("Pump Connection Error", str(e))
            self._log(f"Pump error: {e}")

    def _disconnect_all(self):
        for dev, lbl in [(self.cnc, 'cnc'), (self.pump, 'pump')]:
            if dev:
                try:
                    dev.close()
                except Exception:
                    pass
        self.cnc = None
        self.pump = None
        self.cnc_status_lbl.config(text="● Disconnected", foreground='#FF3B30')
        self.pump_status_lbl.config(text="● Disconnected", foreground='#FF3B30')
        self._log("Devices disconnected.")

    # ── Run handlers ───────────────────────────────────────────────────────────

    def _zero_cnc(self):
        if self.cnc is None:
            messagebox.showerror("Error", "CNC not connected.")
            return
        cnc_send(self.cnc, "G92 X0 Y0 Z0", self._log)
        self._log("CNC zeroed.")

    def _start_run(self):
        if not self.gcode_lines:
            messagebox.showerror("Error", "No G-code loaded.")
            return
        if self.cnc is None:
            messagebox.showerror("Error", "CNC not connected.")
            return
        if self.pump is None:
            if not messagebox.askyesno(
                "Pump not connected",
                "Pump is not connected. Continue without pump (CNC-only)?",
            ):
                return

        self._stop_event.clear()
        self._pause_event.clear()

        self._organic_dwell = self.organic_dwell_var.get()
        lines = list(self.gcode_lines)
        total = sum(
            1 for i, l in enumerate(lines)
            if l.strip() == 'M4'
            and i + 1 < len(lines)
            and 'G04 P' in lines[i + 1]
            and float(lines[i + 1].split('G04 P', 1)[1]) > self._organic_dwell
        )
        self.progress_bar.config(maximum=max(total, 1))
        self.progress_var.set(0)
        self.progress_label_var.set(f"0 / {total} droplets  (0%)")

        self.start_btn.config(state='disabled')
        self.pause_btn.config(state='normal', text="⏸  Pause")
        self.stop_btn.config(state='normal')

        self._start_gif_animation()

        threading.Thread(
            target=self._run_loop, args=(lines, total), daemon=True
        ).start()

    def _toggle_pause(self):
        if self._pause_event.is_set():
            self._pause_event.clear()
            self.pause_btn.config(text="⏸  Pause")
            self._log("Resumed.")
        else:
            self._pause_event.set()
            self.pause_btn.config(text="▶  Resume")
            self._log("Paused — will hold after current movement.")

    def _stop_run(self):
        self._stop_event.set()
        self._pause_event.clear()
        self._log("Stop requested.")

    def _run_loop(self, lines, total_droplets):
        droplet = 0

        # Position/feed tracking for G01 pacing — assumes the CNC has been
        # zeroed (G92) to (0,0,0) before the run
        cx, cy, cz = 0.0, 0.0, 0.0
        feed = self.feedrate_var.get() / 60.0
        max_rates = (self.max_rate_x_var.get() / 60.0,
                     self.max_rate_y_var.get() / 60.0,
                     self.max_rate_z_var.get() / 60.0)
        accels = (self.accel_x_var.get(), self.accel_y_var.get(), self.accel_z_var.get())

        try:
            for idx, line in enumerate(lines):
                if self._stop_event.is_set():
                    break
                while self._pause_event.is_set():
                    if self._stop_event.is_set():
                        break
                    time.sleep(0.2)
                if self._stop_event.is_set():
                    break

                if 'G01' in line:
                    cnc_send(self.cnc, line, self._log)
                    nx, ny, nz, feed = parse_move(line, cx, cy, cz, feed)
                    move_secs = segment_time(nx - cx, ny - cy, nz - cz, feed, max_rates, accels)
                    cx, cy, cz = nx, ny, nz
                    self._log(f" {line}  [move ~{move_secs:.2f}s]")
                    time.sleep(move_secs)

                elif 'M4' in line:
                    cnc_send(self.cnc, line, self._log)
                    dwell = 0.0
                    if idx + 1 < len(lines) and 'G04 P' in lines[idx + 1]:  # peek ahead for the pump-on dwell
                        dwell = float(lines[idx + 1].split('G04 P', 1)[1])
                    self._log(f" M4  [pump start, dwell={dwell}s]")
                    if self.pump is not None:
                        self.pump.write("start\r".encode())
                    t0 = time.time()
                    time.sleep(dwell)
                    if self.pump is not None:
                        self.pump.write("pause\r".encode())
                    self._log(f"  pump ran {time.time() - t0:.2f}s")
                    if dwell > self._organic_dwell:
                        droplet += 1
                        self.root.after(0, self._update_progress, droplet, total_droplets)

                elif 'M3' in line:
                    cnc_send(self.cnc, line, self._log)
                    if self.pump is not None:
                        self.pump.write("pause\r".encode())
                    pause = 0.0
                    if idx + 1 < len(lines) and 'G04 P' in lines[idx + 1]:  # peek ahead for the post-stop pause
                        pause = float(lines[idx + 1].split('G04 P', 1)[1])
                    self._log(f" M3  [pump off, pause={pause}s]")
                    time.sleep(pause)

                elif 'G04' in line:
                    # always already consumed by the M4/M3 line right before it
                    self._log(f"  dwell: {line}  [applied above]")

        except Exception as e:
            self._log(f"ERROR in run loop: {e}")
        finally:
            self.root.after(0, self._on_run_done)

    def _update_progress(self, droplet, total):
        pct = int(droplet / total * 100) if total > 0 else 0
        self.progress_var.set(droplet)
        self.progress_label_var.set(f"{droplet} / {total} droplets  ({pct}%)")

    def _on_run_done(self):
        self._stop_gif_animation()
        self.start_btn.config(state='normal')
        self.pause_btn.config(state='disabled', text="⏸  Pause")
        self.stop_btn.config(state='disabled')
        stopped = " (stopped early)" if self._stop_event.is_set() else ""
        self._log(f"Run finished{stopped}.")
        self._set_status(f"Run complete{stopped}")

    # ── GIF animation ──────────────────────────────────────────────────────────

    def _start_gif_animation(self):
        gifs = [
            os.path.join(LOADING_DIR, f)
            for f in os.listdir(LOADING_DIR)
            if f.lower().endswith('.gif')
        ]
        if not gifs:
            return
        path = random.choice(gifs)

        if HAS_PIL:
            # Read each frame together with its real per-frame delay (ms) from
            # the GIF itself, so playback speed matches how the GIF was authored.
            frames = []
            img = Image.open(path)
            try:
                i = 0
                while True:
                    img.seek(i)
                    delay = img.info.get('duration', 100) or 100  # some GIFs report 0
                    frames.append((ImageTk.PhotoImage(img.copy().convert('RGBA')), delay))
                    i += 1
            except EOFError:
                pass
        else:
            # Fallback: no delay metadata available, so just flip frames at a
            # fixed rate (may play faster/slower than the GIF was authored for).
            frames = []
            try:
                i = 0
                while True:
                    frames.append((tk.PhotoImage(file=path, format=f'gif -index {i}'), 50))
                    i += 1
            except tk.TclError:
                pass

        if not frames:
            return
        self._gif_frames = frames
        self._gif_frame_idx = 0
        self._gif_label.config(image=frames[0][0])
        self._animate_gif()

    def _animate_gif(self):
        if not self._gif_frames:
            return
        image, delay = self._gif_frames[self._gif_frame_idx]
        self._gif_label.config(image=image)
        self._gif_frame_idx = (self._gif_frame_idx + 1) % len(self._gif_frames)
        self._gif_after_id = self.root.after(delay, self._animate_gif)

    def _stop_gif_animation(self):
        if self._gif_after_id is not None:
            self.root.after_cancel(self._gif_after_id)
            self._gif_after_id = None
        self._gif_frames = []
        self._gif_label.config(image='')

    # ── Utilities ──────────────────────────────────────────────────────────────

    def _log(self, msg):
        ts = datetime.datetime.now().strftime('%H:%M:%S')
        self._log_queue.put(f"[{ts}] {msg}")

    def _poll_log(self):
        while not self._log_queue.empty():
            msg = self._log_queue.get_nowait()
            self.log_text.config(state='normal')
            self.log_text.insert(tk.END, msg + '\n')
            self.log_text.see(tk.END)
            self.log_text.config(state='disabled')
        self._poll_log_job = self.root.after(100, self._poll_log)

    def _set_status(self, msg):
        self.status_var.set(msg)

    def _on_close(self):
        self._save_config()
        self._stop_event.set()
        if self.pump:
            try:
                self.pump.write("pause\r".encode())
            except Exception:
                pass
        self._disconnect_all()
        if self._poll_log_job is not None:
            self.root.after_cancel(self._poll_log_job)
            self._poll_log_job = None
        self.root.destroy()
