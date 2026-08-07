import json
import logging
import re

from pathlib import Path

import sv_ttk

import tkinter as tk
from tkinter import messagebox

from errors import TrackDownloaderError, format_error
from paths import app_path

logger = logging.getLogger(__name__)

# Window state is per machine, it doesn't belong in the shared config
LAYOUT_PATH = app_path('config', 'layout.json')

# Colours for the widgets ttk doesn't style, taken from the theme itself
# 'classic' keeps the widget defaults, which is how the window used to look
THEME_COLOURS = {
    'classic': {'background': 'SystemWindow', 'foreground': 'SystemWindowText', 'muted': '#666666'},
    'light':   {'background': '#fafafa', 'foreground': '#1c1c1c', 'muted': '#666666'},
    'dark':    {'background': '#1c1c1c', 'foreground': '#fafafa', 'muted': '#9e9e9e'}
}

# What the theme setting accepts, 'system' resolves to light or dark
THEMES = ('classic', 'system', 'light', 'dark')

# Theme applied to this window, the colours above are picked from it
_applied_theme = 'classic'

def resolve_theme(preference: str):
    """ Turns the configured preference into the theme to actually apply """
    preference = (preference or 'system').strip().lower()
    if preference in THEME_COLOURS:
        return preference

    if preference != 'system':
        logger.warning(f"Unknown theme '{preference}', following the system one")

    # Windows only exposes whether apps should use the light theme
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'
        )
        with key:
            uses_light, _ = winreg.QueryValueEx(key, 'AppsUseLightTheme')
        return 'light' if uses_light else 'dark'
    except Exception:
        logger.debug("Could not read the system theme", exc_info=True)
        return 'light'

def apply_theme(preference: str):
    """ Applies the window theme and returns the one that ended up being used """
    global _applied_theme

    theme = resolve_theme(preference)

    # 'classic' is the plain ttk look the window had before it was themed
    if theme != 'classic':
        try:
            sv_ttk.set_theme(theme)
        except Exception as e:
            logger.warning(f"Could not apply the {theme} theme: {format_error(e)}")
            theme = 'classic'

    _applied_theme = theme
    return theme

def theme_colours():
    """ Colours of the theme in use, for widgets ttk leaves alone """
    return THEME_COLOURS.get(_applied_theme, THEME_COLOURS['classic'])

def fit_to_screen(window, width=None, height=None):
    """ Sizes the window to fit the display it opens on

        A window larger than the screen has its bottom cut off by the window
        manager, which is where the download buttons live
    """
    window.update_idletasks()

    available_width = int(window.winfo_screenwidth() * 0.9)
    available_height = int(window.winfo_screenheight() * 0.9)

    width = min(width or window.winfo_reqwidth(), available_width)
    height = min(height or window.winfo_reqheight(), available_height)

    window.geometry(f"{width}x{height}")
    return width, height

def restore_window_layout(window):
    """ Restores the size and position the window was last closed with
        Returns whether a usable layout was applied
    """
    try:
        layout = json.loads(LAYOUT_PATH.read_text(encoding='utf-8'))
        geometry = layout.get('geometry')
    except (OSError, ValueError):
        return False

    match = re.fullmatch(r'(\d+)x(\d+)([+-]\d+)([+-]\d+)', str(geometry or ''))
    if not match:
        logger.debug(f"Ignoring unusable saved geometry {geometry!r}")
        return False

    width, height, x, y = int(match[1]), int(match[2]), int(match[3]), int(match[4])

    # The saved size can come from a larger monitor than the one in use now
    width, height = fit_to_screen(window, width, height)

    # Keep the window on screen, a saved position can point at a gone display
    x = max(0, min(x, window.winfo_screenwidth() - width))
    y = max(0, min(y, window.winfo_screenheight() - height))

    try:
        window.geometry(f"{width}x{height}+{x}+{y}")
    except tk.TclError:
        logger.debug(f"Ignoring invalid saved geometry {geometry!r}")
        return False

    return True

def save_window_layout(window):
    """ Remembers the size and position of the window """
    try:
        LAYOUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        LAYOUT_PATH.write_text(json.dumps({'geometry': window.geometry()}), encoding='utf-8')
    except OSError as e:
        logger.debug(f"Could not save the window layout: {e}")

class QueueLogHandler(logging.Handler):
    """ Forwards log records to the window through a queue
        Records come from the worker thread, widgets can't be touched there
    """
    def __init__(self, events, level=logging.INFO):
        super().__init__(level)
        self.events = events
        self.setFormatter(logging.Formatter('%(levelname)s  %(message)s'))

    def emit(self, record):
        try:
            self.events.put(('log', self.format(record)))
        except Exception:
            self.handleError(record)

def set_window_icon(window):
    """ Sets the window icon, it is missing when running from another folder """
    try:
        window.iconbitmap(app_path("icon.ico"))
    except tk.TclError:
        logger.debug("Could not load icon.ico", exc_info=True)

def show_error(title, error: Exception):
    """ Shows a failure in a dialog and logs what is useful to debug it """
    if isinstance(error, TrackDownloaderError):
        # Expected failure, the message is meant for the user
        logger.error(format_error(error))
        messagebox.showerror(title, str(error))
    else:
        # Unexpected failure, keep the traceback in the console
        logger.error(f"{title} failed", exc_info=error)
        messagebox.showerror(title, f"Unexpected error: {format_error(error)}")

def report_errors(title):
    """ Reports a failed action in a dialog instead of crashing the callback
        Tkinter otherwise only prints a traceback the user never sees
    """
    def decorator(action):
        def wrapper(*args, **kwargs):
            try:
                return action(*args, **kwargs)
            except Exception as e:
                show_error(title, e)
        return wrapper
    return decorator
