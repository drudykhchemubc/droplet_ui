import itertools

import pandas as pd
import tkinter as tk
from tkinter import messagebox

try:
    import matplotlib
    matplotlib.use('TkAgg')
    import matplotlib.pyplot as plt
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
    HAS_MATPLOTLIB = True
except ImportError:
    HAS_MATPLOTLIB = False


class Screen:
    _SKIP = ['trace', 'wash', 'mark', 'rinse', 'pfd', 'perfluorodecalin', 'oil']

    def __init__(self, dataframe, PFD_dwell, organic_dwell,
                 pause_after_pump_stop, repeats, feedrate):
        self.dataframe = dataframe
        self.PFD_dwell = PFD_dwell
        self.PFD_dwell_space = PFD_dwell * 5
        self.organic_dwell = organic_dwell
        self.pause_after_pump_stop = pause_after_pump_stop
        self.repeats = repeats
        self.feedrate = feedrate
        self.PFD_well_coordinates = None
        self.tracer_well_coordinates = None
        self.combinations = None
        self.combinations_names = None
        self.clas = None

    def initialize(self):
        """Process the CSV and build combination lists. Returns total droplet count."""
        df = self.dataframe.copy()
        df['coordinates'] = list(zip(df.x, df.y))
        df = df.dropna().reset_index(drop=True)

        columns = list(map(str, df.plate_column.tolist()))
        rows = df.plate_row.tolist()
        coordinates = df.coordinates.tolist()
        wells_coords = [(r + c, coord) for r, c, coord in zip(rows, columns, coordinates)]
        names = df.chemical_name.tolist()

        skip_pattern = '|'.join(self._SKIP)
        mask = df['class'].str.lower().str.contains(skip_pattern)
        skip_classes = set(df.loc[mask, 'class'].str.lower().tolist())
        self.clas = [x for x in df['class'].unique() if x.lower() not in skip_classes]

        components_coords = [
            [w for w in wells_coords if df.loc[wells_coords.index(w), 'class'] == c]
            for c in self.clas
        ]
        self.combinations = list(itertools.product(*components_coords))

        wells_names = [(r + c, name) for r, c, name in zip(rows, columns, names)]
        components_names = [
            [w for w in wells_names if df.loc[wells_names.index(w), 'class'] == c]
            for c in self.clas
        ]
        self.combinations_names = list(itertools.product(*components_names))

        tracer = df.loc[df['class'].str.lower().str.contains('trace|mark')]
        if not tracer.empty:
            self.tracer_well_coordinates = tuple(tracer[['x', 'y']].values[0])

        pfd = df.loc[df['class'].str.lower().str.contains('pfd|perfluorodecalin|oil')]
        if not pfd.empty:
            self.PFD_well_coordinates = tuple(pfd[['x', 'y']].values[0])

        return len(self.combinations) * self.repeats

    def generate_gcode(self):
        """Return list of G-code command strings."""
        if self.PFD_well_coordinates is None:
            raise ValueError(
                "No PFD/carrier fluid well found in CSV.\n"
                "A well with class containing 'pfd', 'perfluorodecalin', or 'oil' is required."
            )

        lines = []

        def sample_well(x, y, dwell, pause, feed):
            lines.append(f'G01 X{x} Y{y} Z0.0 F{feed}')
            lines.append(f'G01 X{x} Y{y} Z-8.0 F{feed}')
            lines.append('M4')
            lines.append(f'G04 P{dwell}') # G04 P = ms, G04 S = seconds. 
            lines.append('M3')
            lines.append(f'G04 P{pause}')
            lines.append(f'G01 X{x} Y{y} Z0.0 F{feed}')

        px, py = self.PFD_well_coordinates
        for i, combo in enumerate(self.combinations):
            for j in range(self.repeats):
                pfd_dwell = self.PFD_dwell_space if (i % 6 == 0 and j == 0) else self.PFD_dwell
                sample_well(px, py, pfd_dwell, self.pause_after_pump_stop, self.feedrate)
                for well_entry in combo:
                    cx, cy = well_entry[1]
                    sample_well(cx, cy, self.organic_dwell, self.pause_after_pump_stop, self.feedrate)
        return lines

    def get_combinations_df(self):
        df = pd.DataFrame(self.combinations_names, columns=self.clas)
        df = df.loc[df.index.repeat(self.repeats)].reset_index(drop=True)
        df.index += 1
        df[df.columns] = df.apply(lambda x: tuple(v[1] for v in x))
        rxn_num = [a + 1 for a in range(len(self.combinations)) for _ in range(self.repeats)]
        df.insert(0, 'reaction #', rxn_num)
        df.insert(0, 'droplet #', range(1, len(df) + 1))
        return df

    def show_plate(self, parent_root):
        if not HAS_MATPLOTLIB:
            messagebox.showwarning(
                "Missing package",
                "Install matplotlib to use this feature:\n  pip install matplotlib",
                parent=parent_root)
            return

        df = self.dataframe
        unique_rows = sorted(df['plate_row'].unique())
        unique_cols = sorted(df['plate_column'].unique())
        row_map = {r: i for i, r in enumerate(unique_rows)}

        classes = list(df['class'].unique())
        cmap = plt.cm.get_cmap('tab10', max(len(classes), 1))
        class_colors = {c: cmap(i) for i, c in enumerate(classes)}

        w = max(6, len(unique_cols) * 0.95)
        h = max(4, len(unique_rows) * 0.85)
        fig, ax = plt.subplots(figsize=(w, h))
        fig.patch.set_facecolor('#f5f5f5')
        ax.set_facecolor('#fafafa')

        for cls in classes:
            sub = df[df['class'] == cls]
            ax.scatter(
                sub['plate_column'],
                [row_map[r] for r in sub['plate_row']],
                c=[class_colors[cls]],
                s=320, label=cls,
                edgecolors='#333333', linewidths=0.8, zorder=3,
            )

        ax.set_xticks(unique_cols)
        ax.set_yticks(range(len(unique_rows)))
        ax.set_yticklabels(unique_rows)
        ax.invert_yaxis()
        ax.grid(True, linestyle='--', alpha=0.35, zorder=0)
        ax.legend(loc='upper left', bbox_to_anchor=(1.01, 1), framealpha=0.9, fontsize=8)
        ax.set_title('Well Plate Layout', fontsize=11, pad=10)
        ax.set_xlabel('Column')
        ax.set_ylabel('Row')
        fig.tight_layout()

        annot = ax.annotate(
            "", xy=(0, 0), xytext=(14, 14), textcoords="offset points",
            bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#888888",
                      alpha=0.95, linewidth=0.8),
            fontsize=8, zorder=10,
        )
        annot.set_visible(False)

        points = [
            {'x': row['plate_column'], 'y': row_map[row['plate_row']],
             'name': row['chemical_name'], 'cls': row['class'],
             'smiles': row.get('smiles', '')}
            for _, row in df.iterrows()
        ]

        def on_motion(event):
            if event.inaxes != ax or event.xdata is None:
                if annot.get_visible():
                    annot.set_visible(False)
                    fig.canvas.draw_idle()
                return
            for p in points:
                if abs(event.xdata - p['x']) < 0.4 and abs(event.ydata - p['y']) < 0.4:
                    text = f"{p['name']}\nClass: {p['cls']}"
                    if p['smiles']:
                        text += f"\nSMILES: {p['smiles']}"
                    annot.set_text(text)
                    annot.xy = (p['x'], p['y'])
                    annot.set_visible(True)
                    fig.canvas.draw_idle()
                    return
            if annot.get_visible():
                annot.set_visible(False)
                fig.canvas.draw_idle()

        fig.canvas.mpl_connect('motion_notify_event', on_motion)

        win = tk.Toplevel(parent_root)
        win.title("Well Plate Layout")
        win.geometry("820x560")

        toolbar_frame = tk.Frame(win)
        toolbar_frame.pack(fill=tk.X, side=tk.BOTTOM)

        canvas = FigureCanvasTkAgg(fig, master=win)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

        NavigationToolbar2Tk(canvas, toolbar_frame).update()

        win.protocol("WM_DELETE_WINDOW", lambda: (plt.close(fig), win.destroy()))
