import ast

from dataclasses import fields, is_dataclass
from typing import get_origin, get_type_hints

import tkinter as tk
from tkinter import ttk, font, messagebox

from backends import BACKENDS, create_backend

from config import Config, load_setting_descriptions
from errors import format_error
from gui_utils import set_window_icon, theme_colours

# Width the explanation of a setting wraps at
DESCRIPTION_WRAP = 560

# Generates a Config instance based on the state of the controls
def generate_config_from_dict(cls, widget_dict):
    # Annotations are stored as strings, resolve them to the actual types
    hints = get_type_hints(cls)

    init_kwargs = {}
    for field in fields(cls):
        val = widget_dict[field.name]
        field_type = hints[field.name]

        if isinstance(val, dict):
            # Read section
            init_kwargs[field.name] = generate_config_from_dict(field_type, val)
        else:
            # Read attribute
            raw_val = val.get()

            if field_type is bool:
                parsed_val = bool(raw_val)
            elif field_type is int:
                parsed_val = int(raw_val)
            elif field_type is float:
                parsed_val = float(raw_val)
            elif get_origin(field_type) is list:
                # Lists are edited as their Python literal representation
                try:
                    parsed_val = list(ast.literal_eval(raw_val))
                except (SyntaxError, ValueError):
                    raise ValueError(f"Invalid list value for '{field.name}': {raw_val}")
            else:
                # Anything else is kept verbatim, parsing would alter it
                parsed_val = raw_val

            init_kwargs[field.name] = parsed_val
    return cls(**init_kwargs)

class ConfigEditor:
    def __init__(self, config: Config):
        self.config = config
        self.window = None
        self.dict = {}
        # What each setting does, only the config files explain it
        self.descriptions = load_setting_descriptions()

    def add_config_row(self, parent, label_text, var, description=''):
        # Container for the setting and its explanation
        container = ttk.Frame(parent)
        container.pack(fill='x', pady=(4, 0))

        frame = ttk.Frame(container)
        frame.pack(fill='x')

        # Left label, the TOML key so it maps to the file being edited
        label = ttk.Label(frame, text=label_text, width=25, anchor='w')
        label.pack(side='left')

        # Input field
        if label_text == "backend":
            # Use combobox for backend instead of entry
            combo = ttk.Combobox(frame, textvariable=var, values=list(BACKENDS), state="readonly")
            combo.pack(side='left', fill='x', expand=True, padx=(0, 5))

            def on_test_backend():
                try:
                    backend = create_backend(self.generate_config())
                    backend.connect()
                    messagebox.showinfo("Success", f"Connected to {backend.name.capitalize()}!")
                except Exception as e:
                    # Report the real cause, credentials are only one of them
                    messagebox.showerror("Error", format_error(e))

            # Add test button
            test_button = ttk.Button(frame, text="Test", command=on_test_backend)
            test_button.pack(side='right')
        elif isinstance(var, tk.BooleanVar):
            cb = ttk.Checkbutton(frame, variable=var)
            cb.pack(side='left')
        else:
            entry = ttk.Entry(frame, textvariable=var, width=50)
            entry.pack(side='left')

        # What the setting does, taken from the comment in the config file
        if description:
            hint = ttk.Label(
                container,
                text=description,
                foreground=theme_colours()['muted'],
                wraplength=DESCRIPTION_WRAP,
                justify='left'
            )
            hint.pack(anchor='w', padx=(8, 0))

    def build_form(self, parent, config, section=''):
        # Get default font
        default_font = font.nametofont('TkTextFont').actual()
        font_family = default_font['family']
        font_size = default_font['size']

        # Generate controls
        dict = {}
        for field in fields(config):
            value = getattr(config, field.name)
            if is_dataclass(value):
                # Section header
                label = ttk.Label(parent, text=field.name.capitalize(), font=(font_family, font_size + 1, 'bold'))
                label.pack(anchor='w', pady=(10, 2))

                # Section container
                subframe = ttk.Frame(parent, borderwidth=1, padding=5)
                subframe.pack(fill='x', padx=10, pady=2)

                # Build section, its name is how the settings are documented
                dict[field.name] = self.build_form(subframe, value, field.name)
            else:
                # Add attribute to section
                if isinstance(value, list):
                    var = tk.StringVar(value=repr(value))
                elif type(value) is bool:
                    var = tk.BooleanVar(value=value)
                else:
                    var = tk.StringVar(value=value)

                description = self.descriptions.get(section, {}).get(field.name, '')
                self.add_config_row(parent, field.name, var, description)
                dict[field.name] = var
        return dict

    def generate_config(self):
        return generate_config_from_dict(type(self.config), self.dict)

    def close(self):
        # The wheel binding is global while hovering, it must not outlive us
        self.window.unbind_all('<MouseWheel>')
        self.window.destroy()
        self.window = None
        self.dict = {}

    def open(self, root):
        self.window = tk.Toplevel(root)
        self.window.title("Config Editor")
        self.window.resizable(False, True)
        set_window_icon(self.window)

        # The form is taller than some screens, keep the buttons reachable
        colours = theme_colours()
        canvas = tk.Canvas(self.window, highlightthickness=0,
                           background=colours['background'])
        scrollbar = ttk.Scrollbar(self.window, orient='vertical', command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        form = ttk.Frame(canvas, padding=(10, 0))
        form_window = canvas.create_window((0, 0), window=form, anchor='nw')

        def on_form_resized(*ignore):
            canvas.configure(scrollregion=canvas.bbox('all'))
            # Grow the form to the canvas so the rows fill the width
            canvas.itemconfigure(form_window, width=canvas.winfo_width())

            # Only take the height the form needs, up to what fits on screen
            height = min(form.winfo_reqheight(), int(self.window.winfo_screenheight() * 0.7))
            canvas.configure(width=form.winfo_reqwidth(), height=height)

        form.bind('<Configure>', on_form_resized)
        canvas.bind('<Configure>', on_form_resized)

        def on_mouse_wheel(event):
            canvas.yview_scroll(-event.delta // 120, 'units')

        # Bound only while hovering, a global binding would outlive the window
        canvas.bind('<Enter>', lambda *ignore: canvas.bind_all('<MouseWheel>', on_mouse_wheel))
        canvas.bind('<Leave>', lambda *ignore: canvas.unbind_all('<MouseWheel>'))

        scrollbar.pack(side='right', fill='y')
        canvas.pack(side='top', fill='both', expand=True)

        self.dict = self.build_form(form, self.config)

        def on_cancel():
            self.close()

        def on_save():
            try:
                config = self.generate_config()
            except Exception as e:
                # A malformed value would otherwise discard every other edit
                messagebox.showerror("Invalid Value", format_error(e))
                return

            # Mutate the original config in place
            self.config.downloads = config.downloads
            self.config.metadata = config.metadata
            self.config.soundcloud = config.soundcloud
            self.config.spotify = config.spotify
            self.config.deezer = config.deezer
            self.config.qobuz = config.qobuz

            # Update config file
            try:
                self.config.save()
            except Exception as e:
                messagebox.showerror("Save Config", format_error(e))
                return

            # Close window
            self.close()

        # Button container, anchored at the bottom so scrolling never hides it
        button_frame = ttk.Frame(self.window)
        button_frame.pack(side='bottom', pady=10)

        # Cancel button (left)
        ttk.Button(button_frame, text="Cancel", command=on_cancel).pack(side=tk.LEFT, padx=(0, 5))
        # Save button (right)
        ttk.Button(button_frame, text="Save", command=on_save).pack(side=tk.LEFT)
