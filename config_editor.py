import ast
import re

from dataclasses import fields, is_dataclass
from typing import get_origin, get_type_hints

import tkinter as tk
from tkinter import ttk, font, messagebox

from backends import BACKENDS, create_backend

from config import Config

# Formats an exception into a message suitable for a dialog
def format_error(error: Exception):
    # Backend libraries decorate their messages with terminal color codes
    message = re.sub(r'\x1b\[[0-9;]*m', '', str(error)).strip()

    # Keep the cause only, the remaining lines are command line instructions
    message = message.splitlines()[0].strip() if message else ''

    return message or type(error).__name__

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

    def add_config_row(self, parent, label_text, var):
        # Container
        frame = ttk.Frame(parent)
        frame.pack(fill='x', pady=2)

        # Left label
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

    def build_form(self, parent, config):
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

                # Build section
                dict[field.name] = self.build_form(subframe, value)
            else:
                # Add attribute to section
                if isinstance(value, list):
                    var = tk.StringVar(value=repr(value))
                elif type(value) is bool:
                    var = tk.BooleanVar(value=value)
                else:
                    var = tk.StringVar(value=value)
                self.add_config_row(parent, field.name, var)
                dict[field.name] = var
        return dict

    def generate_config(self):
        return generate_config_from_dict(type(self.config), self.dict)

    def close(self):
        self.window.destroy()
        self.window = None
        self.dict = {}

    def open(self, root):
        self.window = tk.Toplevel(root)
        self.window.title("Config Editor")
        self.window.resizable(False, False)
        self.window.iconbitmap("icon.ico")

        self.dict = self.build_form(self.window, self.config)

        def on_cancel():
            self.close()

        def on_save():
            config = self.generate_config()

            # Mutate the original config in place
            self.config.downloads = config.downloads
            self.config.metadata = config.metadata
            self.config.soundcloud = config.soundcloud
            self.config.spotify = config.spotify
            self.config.deezer = config.deezer
            self.config.qobuz = config.qobuz

            # Update config file
            self.config.save()

            # Close window
            self.close()

        # Button container
        button_frame = ttk.Frame(self.window)
        button_frame.pack(pady=10)

        # Cancel button (left)
        ttk.Button(button_frame, text="Cancel", command=on_cancel).pack(side=tk.LEFT, padx=(0, 5))
        # Save button (right)
        ttk.Button(button_frame, text="Save", command=on_save).pack(side=tk.LEFT)
