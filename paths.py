import os

from pathlib import Path

# Everything shipped with the app is resolved from here rather than the working
# directory, so it can be started from a shortcut or a scheduled task
APP_DIR = Path(__file__).resolve().parent

def app_path(*parts):
    """ Absolute path of a file shipped with the app """
    return APP_DIR.joinpath(*parts)

def resolve_path(path: str):
    """ Makes a configured path absolute, relative ones are relative to the app """
    return os.path.abspath(os.path.join(APP_DIR, path))
