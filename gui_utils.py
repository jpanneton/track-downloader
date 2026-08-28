import ctypes
import json
import logging
import os
import re
import subprocess
import sys

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
# 'classic' is missing here, it keeps whatever the platform draws by default
THEME_COLOURS = {
    'light': {'background': '#fafafa', 'foreground': '#1c1c1c', 'muted': '#666666'},
    'dark':  {'background': '#1c1c1c', 'foreground': '#fafafa', 'muted': '#9e9e9e'}
}

# What the theme setting accepts, 'system' resolves to light or dark
THEMES = ('classic', 'system', 'light', 'dark')

# Used until a window exists to read the real defaults off, and if that fails
FALLBACK_COLOURS = {'background': '#ffffff', 'foreground': '#000000', 'muted': '#666666'}

# Theme applied to this window and the colours that came with it
_applied_theme = 'classic'
_applied_colours = FALLBACK_COLOURS

def system_theme():
    """ Light or dark, according to the desktop setting """
    if sys.platform == 'win32':
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

    elif sys.platform == 'darwin':
        # macOS only sets AppleInterfaceStyle while dark mode is on, so the
        # setting being missing is the answer rather than a failure
        try:
            style = subprocess.run(
                ['defaults', 'read', '-g', 'AppleInterfaceStyle'],
                capture_output=True, text=True, timeout=5
            ).stdout.strip()
            return 'dark' if style.lower() == 'dark' else 'light'
        except (OSError, subprocess.SubprocessError):
            logger.debug("Could not read the system theme", exc_info=True)

    return 'light'

def resolve_theme(preference: str):
    """ Turns the configured preference into the theme to actually apply """
    preference = (preference or 'system').strip().lower()
    if preference == 'classic' or preference in THEME_COLOURS:
        return preference

    if preference != 'system':
        logger.warning(f"Unknown theme '{preference}', following the system one")

    return system_theme()

def classic_colours(window):
    """ Colours the plain widgets are drawn with when nothing is themed

        Tk names them differently per platform, 'SystemWindow' only exists on
        Windows, so read them off a real widget instead of hardcoding them
    """
    probe = tk.Text(window)
    try:
        return {
            'background': str(probe.cget('background')),
            'foreground': str(probe.cget('foreground')),
            'muted': FALLBACK_COLOURS['muted']
        }
    except tk.TclError:
        logger.debug("Could not read the default widget colours", exc_info=True)
        return FALLBACK_COLOURS
    finally:
        probe.destroy()

def apply_theme(window, preference: str):
    """ Applies the window theme and returns the one that ended up being used """
    global _applied_theme, _applied_colours

    theme = resolve_theme(preference)

    # 'classic' is the plain ttk look the window had before it was themed
    if theme != 'classic':
        try:
            sv_ttk.set_theme(theme)
        except Exception as e:
            logger.warning(f"Could not apply the {theme} theme: {format_error(e)}")
            theme = 'classic'

    _applied_theme = theme
    _applied_colours = THEME_COLOURS.get(theme) or classic_colours(window)
    return theme

def theme_colours():
    """ Colours of the theme in use, for widgets ttk leaves alone """
    return _applied_colours

def open_in_file_manager(path):
    """ Reveals a folder in the desktop's file manager """
    if sys.platform == 'win32':
        os.startfile(path)
    elif sys.platform == 'darwin':
        subprocess.run(['open', path], check=True)
    else:
        subprocess.run(['xdg-open', path], check=True)

def enable_dpi_awareness():
    """ Makes Windows report real pixels instead of stretching the window

        A DPI unaware window is drawn at 96 DPI and scaled up by Windows, which
        is what makes it blurry on a high resolution display. Must be called
        before the first window exists.
    """
    if sys.platform != 'win32':
        return

    try:
        # Per monitor v2, so moving between displays rescales correctly
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError) as e:
        logger.debug(f"Per monitor DPI awareness unavailable: {e}")

    try:
        # Older Windows only knows about the primary display
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError) as e:
        logger.debug(f"Could not enable DPI awareness: {e}")

def apply_dpi_scaling(window):
    """ Sizes Tk's fonts and widgets for the real DPI of the display
        Without this the window is crisp but everything in it is tiny
    """
    try:
        dpi = window.winfo_fpixels('1i')
    except tk.TclError:
        return

    # Tk measures in points, and a hostile value would make the window unusable
    scaling = min(max(dpi / 72, 1.0), 4.0)
    window.tk.call('tk', 'scaling', scaling)
    logger.debug(f"Display reports {dpi:.0f} DPI, Tk scaling set to {scaling:.2f}")

def window_dpi(window):
    """ Pixels per inch of the display the window is on, 0 when unknown """
    try:
        return round(window.winfo_fpixels('1i'), 1)
    except tk.TclError:
        return 0.0

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

    # A size in pixels only means the same window at the same DPI, rescale it
    # when the display or its scaling changed since it was saved
    saved_dpi = layout.get('dpi') or 0
    current_dpi = window_dpi(window)

    if saved_dpi and current_dpi and abs(current_dpi - saved_dpi) > 0.5:
        ratio = min(max(current_dpi / saved_dpi, 0.25), 4.0)
        logger.debug(f"Display went from {saved_dpi} to {current_dpi} DPI, scaling the window by {ratio:.2f}")
        width, height = round(width * ratio), round(height * ratio)
        x, y = round(x * ratio), round(y * ratio)

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
    """ Remembers the size and position of the window
        The DPI is saved with it, the same pixel size is a different window on
        a display that scales differently
    """
    try:
        LAYOUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        LAYOUT_PATH.write_text(
            json.dumps({'geometry': window.geometry(), 'dpi': window_dpi(window)}),
            encoding='utf-8'
        )
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
