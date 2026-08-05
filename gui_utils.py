import logging

import tkinter as tk
from tkinter import messagebox

from errors import TrackDownloaderError, format_error

logger = logging.getLogger(__name__)

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
        window.iconbitmap("icon.ico")
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
