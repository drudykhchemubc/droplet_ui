# Microdroplet Screen Controller

A desktop app for automating microdroplet chemistry screens on a well
plate, generating the G-code to run them on a CNC + syringe pump rig, and
monitoring the run live.

---

## Features

**Reaction prep**
- You can easily view the settings (dwell time, CNC settings) and play around with them. You can save your settings in the `settings_presets` folder which can be linked to the quality of the results and easily uploaded to virtual laboratory notebooks, etc.
- Similarly, you can save reaction presets for similar reactions you run often, or wellplate geometry presets for a custom wellplate.
- Variety of different ways to import/export data. You can set up reactions in a variety of ways: 1. Uploading G-Code directly, 2. Uploading a .csv file, or 3. Generating G-Code through the wellplate UI in the application.
- Colors: each 'class' is generally grouped in the same color, but you can also set your own color with a hex code or by using the color wheel (for instance, if you have a very brightly colored solution). To do this, you just need to RIGHT click on the well plate that you want to change the color of.
- The default folder location for the G-Code output is `microdropletapp/gcode_output`, but you can also select a different folder if it is more convenient. The program remembers these settings (via the JSON file).

**Running reactions / CNC Connection**
- The code tells you which droplet # it is currently in the process of making & provides a time estimate to completion (useful for longer runs)
- The time estimate is based on the dwell time & CNC speed settings
- New progress bar (with % progress)
- You can also upload your own 'loading image' by uploading them into the `loading_images_git` folder. The code randomly picks one if there are multiple images in this folder. Currently there is only one (Creative Commons) image in there. Feel free to remove it if it bothers you too. 

## 1. Quick start (experienced coders)

**Requirements:** Python 3.10+ (tested on 3.12), Windows (uses `ctypes.windll`
for DPI awareness and defaults to `COM` ports; the plate editor / G-code
generation itself is platform-agnostic).

```bash
pip install -r requirements.txt   # pandas, pyserial, matplotlib, Pillow
python main.py
```

`tkinter` ships with the standard CPython Windows installer, so it doesn't
need to be pip-installed. If `import tkinter` fails, reinstall Python from
python.org with the default options (don't use a "no tcl/tk" custom build).

**Entry point:** [main.py](main.py) -> `MicrodropletApp` in
[app_gui.py](app_gui.py).

The application runs through `main.py`.

**Key modules:**

| File | Responsibility |
|---|---|
| [app_gui.py](app_gui.py) | Main window: Configure/Run tabs, settings presets, run loop, hardware connect/serial control |
| [plate_editor.py](plate_editor.py) | Embedded well-plate grid editor: geometry, well classes/colors, geometry & reaction presets, CSV import/export |
| [gcode_generator.py](gcode_generator.py) | `Screen` class - turns a wells dataframe into droplet combinations + G-code |
| [cnc_hardware.py](cnc_hardware.py) | Thin serial wrappers for the CNC controller (grbl-style) and the pump |
| [time_estimate.py](time_estimate.py) | Move-time estimation for the progress bar, using feedrate/accel/max-rate |
| [dropdown_autocomplete.py](dropdown_autocomplete.py) | Typeahead behavior bound onto `ttk.Combobox` widgets |
| [animated_tab_design.py](animated_tab_design.py) | Custom animated `ttk.Notebook` used for the top-level tabs |

**Config & persistence** (all plain JSON, auto-created, gitignore-able).

These save your settings with each new startup of the app and allow you to create presets.

- [microdroplet_config.json](microdroplet_config.json) - last-used folders, ports, machine params, active settings preset.
- `settings_presets/` - one `<name>.json` per saved parameter set (dwell times, feedrate, machine limits). `default.json` is protected from being overwritten.
- `geometry_presets/` - one `<name>.json` per saved plate geometry (rows, cols, spacing_x/y, origin_x/y). You can use this if you are using a non-traditional plate geometry, but the application already comes with common presets (e.g. a 384-well plate) so that you will likely not need this.
- `rxn_presets/` - one `<name>.json` per saved well-assignment layout (`{"wells": {"ri,ci": {...}}}`).
- `gcode_output/` - generated G-code `.txt` files; `gcode_output/combinations/` holds the matching combinations CSVs. This G-code is what is used to run the CNC machine.

Presets in all three `*_presets/` folders are listed by scanning the folder
for `*.json` files, so dropping a hand-written or shared JSON file straight
into the folder makes it show up in the app's picker - no import step needed.

See [General setup](#general-setup) below for connecting the CNC & pump hardware.

---

## 2. Complete beginner's guide (never coded before)

This section assumes you're starting from zero - no Python, no editor,
nothing installed. Follow it top to bottom on Windows.

### Step 1 - Install Python

1. Go to **[python.org/downloads](https://www.python.org/downloads/)** and
   click the big "Download Python" button.
2. Run the installer. **Important:** on the first screen, check the box at
   the bottom that says **"Add python.exe to PATH"** before clicking
   Install. This lets you type `python` in a terminal from anywhere.
3. Once it finishes, confirm it worked: open **Command Prompt** (press the
   Windows key, type `cmd`, hit Enter) and type:

   ```
   python --version
   ```

   You should see something like `Python 3.12.1`. If instead you see
   `'python' is not recognized...`, Python either isn't installed or the
   PATH box wasn't checked - reinstall and make sure to check it.

### Step 2 - Install a code editor

You only need one of these. There are a lot of options on the market, but these are the ones I like. You can technically even use this without an editor (just run Python in Command Prompt), but I would not recommend this if you are a beginner.

**Option A: VS Code** (Free!)

1. Go to **[code.visualstudio.com](https://code.visualstudio.com/)** and
   download/install it (default options are fine).
2. Open VS Code.
3. Go to the Extensions icon on the left sidebar (looks like
   four squares), search for **"Python"** (by Microsoft), and click Install.

**Option B: PyCharm** (paid, but free with an educational license)

1. Go to **[jetbrains.com/pycharm/download](https://www.jetbrains.com/pycharm/download/)**
2. Install it with the default options.

### Step 3 - Download the code from GitHub

1. Go to the repository's page on GitHub.
2. Click the green **Code** button, then **Download ZIP**.
3. Find the downloaded `.zip` (usually in your Downloads folder), right-click
   it -> **Extract All...**, and pick a location (e.g. your Desktop).
4. Open the extracted folder - it should contain `main.py`, `app_gui.py`,
   etc. That's your `microdroplet_app` folder for every step below.

(If you already know Git, `git clone <repo-url>` works too, and makes it
easier to pull future updates without re-downloading everything.)

### Step 4 - Open a terminal inside the project folder

- **In VS Code:** File -> Open Folder... -> select `microdroplet_app` (the entire folder, not a specific file). Then open the built-in terminal with `` Ctrl+` `` (backtick) or via Terminal -> New Terminal. It should already start inside the project folder.
- **In PyCharm:** File -> Open... -> select `microdroplet_app` (the entire folder, not a specific file). Then open the terminal via the "Terminal" tab at the bottom of the window.
- **Without an editor:** open Command Prompt/PowerShell (Windows) or Terminal (macOS). Make sure to run it as Administrator. Then type `cd ` (with a trailing space) and drag-and-drop the `microdroplet_app` folder onto the window. This will paste the full path location of the folder and move you into that folder, so that you can now run it.

If you can't find your terminal in the code editor, the "Without an editor" step above always works regardless of what you're editing code in. The terminal doesn't have to belong to the same program as your editor.

Rule of thumb: if the prompt looks like `>>>` or `In [1]:`, or there's no
blinking cursor to type into at all, it's not a terminal.

### Step 5 (recommended, optional) - Create a virtual environment

A Python virtual environment keeps the project's Python packages separate from everything else on your machine, so nothing conflicts. It's optional but recommended.

1. In your terminal (Step 4), make sure you're inside the `microdroplet_app` folder.
2. Run `python -m venv venv` to create the environment (this makes a new one-time `venv` folder).
3. Run `venv\Scripts\activate` to turn it on.
4. The beginning of your terminal line should now start with `(venv)` - that means it worked.
5. Repeat step 3 every time you open a fresh terminal for this project (skip steps 1-2, the `venv` folder is already made).

**Using PyCharm?** You can skip all of the above - PyCharm does this for you.

When you first open the project, go to **File -> Settings -> Project:
microdroplet_app -> Python Interpreter**, click **Add Interpreter ->
Add Local Interpreter**, choose **Virtualenv Environment -> New**, and click
**OK**. PyCharm creates the `venv` and auto-activates it in its built-in
terminal from then on, so you'll never need to type `activate` yourself.

### Step 6 - Install the required packages

With your terminal still inside `microdroplet_app`, run:

```
pip install -r requirements.txt
```

This installs `pandas`, `pyserial`, `matplotlib`, and `Pillow` - the
libraries the app depends on beyond what Python already includes. If this doesn't work, you can also try installing them each separately.

### Step 7 - Run the app (still in terminal)

```
python main.py
```

You can also click the "Play"/"Run" button at the top right of the `main.py` file in your editor.

A window titled "Microdroplet Screen Controller" should open! Yay!

See [General setup](#general-setup) below for connecting the CNC & pump hardware.

## General setup (CNC & more)

**Connecting the CNC & pump** (Run tab -> HARDWARE): there is NO auto-detect!!!

You type in the Port and Baud for each device yourself.

1. Plug in the device, open **Device Manager** (right-click the Start
   button -> Device Manager) and expand **Ports (COM & LPT)** - e.g.
   `USB-SERIAL CH340 (COM3)`. The number in parentheses is the port.
2. Not sure which entry is which device? Unplug one, click
   **Action -> Scan for hardware changes**, and see which entry disappears.
3. Enter that Port + Baud and click **Connect** (or **Connect All** for
   both). CNC baud is typically `115200` for GRBL controllers; pump baud
   depends on the pump model - check its manual. Whatever you enter is
   saved to `microdroplet_config.json` automatically.
4. Or list ports from Python directly (with the hardware plugged in):

   ```python
   from serial.tools import list_ports

   for p in list_ports.comports():
       print(f"{p.device:<8} {p.description}")
   ```

5. Still stuck? Try **[Universal Gcode Sender (UGS)](https://winder.github.io/ugs_website/)**
   to connect to the CNC's COM port independently of this app - if UGS can
   connect and jog it, the problem is on this app's side (wrong port/baud
   entered, or the port already in use); if UGS also fails, the issue is
   with the CNC/cabling/drivers themselves.

Before hitting **Start**, manually jog the gantry to your physical
reference/home position, then click **Zero CNC (G92)** - this tells the
controller "this is (0, 0, 0)" without physically homing, so it needs to be
redone each session. A "Connection Error" almost always means either the
wrong COM number or the port already being held open elsewhere (Arduino
IDE's Serial Monitor, another instance of this app, etc.) - close whatever
else has it open and retry.

### Wellplate UI directions

1. Select the wellplate size that you are interested in (e.g. a 384-well plate). Sometimes, if I am running only a small number of samples (even in a larger wellplate), it may be easier to select the smaller size for easier visualization. Customize it based on your needs.
2. Left-click the well plate that you would like to modify. You can type in a chemical name (for your own reference), but the class is what mostly matters for the generation of the G-Code.
3. Continue doing this until you have finished adding all your desired chemicals.
4. Click "Generate G-Code" on the left corner and make sure that the log records it (a new file should be created in `gcode_output`).

**Importing pre-made .csv files**

You can skip steps 1-3 if you have already made your own .csv file (in a format that the program accepts).

1. Under "CSV", click "Import". This should generate a well-plate visual.
2. Click "Generate G-Code" on the left corner and make sure that the log records it (a new file should be created in `gcode_output`).

**General notes**

- When you generate G-Code, a .csv file is created automatically with it in `gcode_output\combinations`. However, you can also export a .csv file of the combinations you have created from the well plate UI by clicking "Export" under "CSV" and saving it in your desired destination.
- If you are running a similar reaction often, you can also save it as a reaction preset. This might be more accessible in the application than importing a .csv, since it is available in the dropdown menu (no need to open any files). Each reaction preset is saved as a .json file in the `rxn_presets` folder. Once you have already completed making your well-plate (step #3 in the directions above), you can click "Save As..." below "REACTION PRESETS", which will display your new preset in the dropdown from then on.
- Colors: each 'class' is generally grouped in the same color. If you would like to change the color, right-click on that well plate and there will be a pop-up where you can change the hex code or use a color wheel to change the color. This will not change the color of the entire class, but rather just that one well plate.

### Troubleshooting

| Problem | Fix |
|---|---|
| `'python' is not recognized as an internal or external command` | Python isn't on PATH. Reinstall from python.org and check "Add python.exe to PATH". |
| `ModuleNotFoundError: No module named 'pandas'` (or `serial`, `matplotlib`, `PIL`) | You haven't run `pip install -r requirements.txt` in this terminal (or your venv isn't activated). |
| `ModuleNotFoundError: No module named 'tkinter'` | Rare on Windows - reinstall Python using the official installer with default options. |
| CNC/pump "Connection Error" in the Run tab | Check that the COM port number in Windows Device Manager ("Ports (COM & LPT)") and the baud rate match your hardware, and that no other program (e.g. Arduino IDE's Serial Monitor) has that port open. |
| Nothing happens when you double-click `main.py` | Double-clicking a `.py` file doesn't open a terminal to see errors in. Always run it via `python main.py` from a terminal, or the Run button in your editor, at least the first few times. |

### Terminology (Settings & Plate Configuration panels)

- **PFD Dwell Time (s)** - How long the needle sits in the PFD/carrier fluid well before withdrawing. Every 6th reaction it's automatically stretched to 5× this value to make a bigger spacer droplet.
- **Organic Dwell Time (s)** - How long the needle sits in each reagent well while withdrawing that component.
- **Pause After Pump Stop (s)** - Extra wait after the pump stops, before the needle lifts and moves.
- **Droplet Multiplicity** - How many replicate droplets to make per unique reaction combination. Called `repeats` in the code.
- **Motor Feedrate (mm/min)** - Travel speed used for every move between wells during a run.
- **X/Y/Z Max Rate (mm/min)** - Hardware speed ceiling per axis, sent to the GRBL controller as `$110`-`$112`.
- **X/Y/Z Acceleration (mm/s²)** - How fast each axis can speed up/slow down, sent to GRBL as `$120`-`$122`; also drives the progress-bar time estimate.
- **Size** - A named preset (e.g. `384`, `96`) that fills in Rows/Cols/Spacing for you; pick `Custom` to set your own.
- **Rows / Cols** - Number of well rows and columns in the plate grid.
- **Spacing X/Y (mm)** - Center-to-center distance between adjacent wells along each axis.
- **Origin X/Y (mm)** - The CNC coordinate where well A1 sits; every other well is `origin + index * spacing` from there.

### Credits

Loading image:  
"+ i'm so mad! +"

Artwork by MellowKun  
Source: [Original artwork on DeviantArt](https://www.deviantart.com/mellowkun/art/i-m-so-mad-722516278)  
License: Creative Commons Attribution 3.0 (CC BY 3.0)
