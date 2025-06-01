import ast

from dataclasses import fields, is_dataclass

import tkinter as tk
from tkinter import ttk, font

def add_config_row(parent, label_text, var):
    # Container
    frame = ttk.Frame(parent)
    frame.pack(fill='x', pady=2)

    # Left label
    label = ttk.Label(frame, text=label_text, width=25, anchor='w')
    label.pack(side='left')

    # Input field
    if isinstance(var, tk.BooleanVar):
        cb = ttk.Checkbutton(frame, variable=var)
        cb.pack(side='left')
    else:
        entry = ttk.Entry(frame, textvariable=var, width=50)
        entry.pack(side='left')

def build_config_form(parent, config):
    # Get default font
    default_font = font.nametofont('TkTextFont').actual()
    font_family = default_font['family']
    font_size = default_font['size']

    # Generate controls
    widgets = {}
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
            widgets[field.name] = build_config_form(subframe, value)
        else:
            # Add attribute to section
            if isinstance(value, list):
                var = tk.StringVar(value=repr(value))
            elif type(value) is bool:
                var = tk.BooleanVar(value=value)
            else:
                var = tk.StringVar(value=value)
            add_config_row(parent, field.name, var)
            widgets[field.name] = var
    return widgets

def generate_config(cls, widget_dict):
    init_kwargs = {}
    for field in fields(cls):
        val = widget_dict[field.name]
        if isinstance(val, dict):
            # Read section
            init_kwargs[field.name] = generate_config(field.type, val)
        else:
            # Read attribute
            raw_val = val.get()

            # Try to parse list
            try:
                parsed_val = ast.literal_eval(raw_val)
            except:
                if field.type == bool:
                    parsed_val = bool(raw_val)
                elif field.type == int:
                    parsed_val = int(raw_val)
                elif field.type == float:
                    parsed_val = float(raw_val)
                else:
                    parsed_val = raw_val

            init_kwargs[field.name] = parsed_val
    return cls(**init_kwargs)

def open_config_editor(root, config):
    window = tk.Toplevel(root)
    window.title("Config Editor")
    window.resizable(False, False)
    window.iconbitmap("icon.ico")

    form_widgets = build_config_form(window, config)

    def on_cancel():
        window.destroy()

    def on_save():
        new_config = generate_config(type(config), form_widgets)
        new_config.save()
        window.destroy()

    # Button container
    button_frame = ttk.Frame(window)
    button_frame.pack(pady=10)

    # Cancel button (left)
    ttk.Button(button_frame, text="Cancel", command=on_cancel).pack(side=tk.LEFT, padx=(0, 5))
    # Save button (right)
    ttk.Button(button_frame, text="Save", command=on_save).pack(side=tk.LEFT)
