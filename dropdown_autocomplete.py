import tkinter as tk

_IGNORED_KEYSYMS = {
    'BackSpace', 'Delete', 'Left', 'Right', 'Up', 'Down',
    'Home', 'End', 'Tab', 'Return', 'KP_Enter', 'Escape',
    'Shift_L', 'Shift_R', 'Control_L', 'Control_R',
    'Alt_L', 'Alt_R', 'Caps_Lock',
}

_RESET_MS = 900


def _match(values, buffer, ch):
    """Try to extend buffer with ch; fall back to a fresh single-char search."""
    candidate = buffer + ch
    match = next((v for v in values if v.lower().startswith(candidate.lower())), None)
    if match is None:
        candidate = ch
        match = next((v for v in values if v.lower().startswith(candidate.lower())), None)
    if match is None:
        return None, None
    return candidate, match


def bind_typeahead(combobox):
    """Make a ttk.Combobox jump to the first value starting with what's typed.
    """
    state = {'buffer': '', 'after_id': None}

    def _reset(_event=None):
        state['buffer'] = ''
        state['after_id'] = None

    def _on_key(event):
        if event.keysym in _IGNORED_KEYSYMS:
            if event.keysym in ('BackSpace', 'Delete'):
                if state['after_id'] is not None:
                    combobox.after_cancel(state['after_id'])
                _reset()
            return None

        ch = event.char
        if not ch or not ch.isprintable():
            return None

        values = combobox['values']
        if not values:
            return None

        if state['after_id'] is not None:
            combobox.after_cancel(state['after_id'])

        new_buffer, match = _match(values, state['buffer'], ch)
        if match is None:
            _reset()
            return None

        state['buffer'] = new_buffer
        combobox.set(match)
        combobox.icursor(tk.END)
        combobox.selection_clear()
        combobox.event_generate('<<ComboboxSelected>>')
        state['after_id'] = combobox.after(_RESET_MS, _reset)
        return 'break'

    combobox.bind('<KeyPress>', _on_key)
    _bind_popdown_listbox(combobox, state, _reset)


def _bind_popdown_listbox(combobox, state, reset):
    """Hook the combobox's native dropdown listbox, which takes keyboard
    focus once it's posted — our Entry-level binding never sees keystrokes
    typed while the list is open, so it needs its own handler."""
    try:
        popdown = combobox.tk.call('ttk::combobox::PopdownWindow', combobox._w)
    except tk.TclError:
        return
    listbox = f'{popdown}.f.l'

    def _on_listbox_key(ch, keysym):
        if keysym in _IGNORED_KEYSYMS:
            if keysym in ('BackSpace', 'Delete'):
                if state['after_id'] is not None:
                    combobox.after_cancel(state['after_id'])
                reset()
            return '0'

        if not ch or not ch.isprintable():
            return '0'

        values = combobox['values']
        if not values:
            return '0'

        if state['after_id'] is not None:
            combobox.after_cancel(state['after_id'])

        new_buffer, match = _match(values, state['buffer'], ch)
        if match is None:
            reset()
            return '0'

        state['buffer'] = new_buffer
        idx = values.index(match)
        combobox.set(match)
        try:
            combobox.tk.call(listbox, 'selection', 'clear', 0, 'end')
            combobox.tk.call(listbox, 'selection', 'set', idx)
            combobox.tk.call(listbox, 'activate', idx)
            combobox.tk.call(listbox, 'see', idx)
        except tk.TclError:
            pass
        state['after_id'] = combobox.after(_RESET_MS, reset)
        return '1'

    try:
        cmd = combobox.register(_on_listbox_key)
        combobox.tk.call('bind', listbox, '<KeyPress>', f'if {{[{cmd} %A %K]}} break')
    except tk.TclError:
        pass
