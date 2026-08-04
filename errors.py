import re

class TrackDownloaderError(Exception):
    """ Failure with a message meant to be shown to the user """

class ConfigurationError(TrackDownloaderError):
    """ Something required is missing or invalid in the config """

class PlaylistError(TrackDownloaderError):
    """ A playlist could not be read """

class BackendError(TrackDownloaderError):
    """ A download backend could not be reached or used """

def format_error(error: Exception):
    """ Formats an exception into a single line suitable for a dialog """
    # Backend libraries decorate their messages with terminal color codes
    message = re.sub(r'\x1b\[[0-9;]*m', '', str(error)).strip()

    # Keep the cause only, the remaining lines are command line instructions
    message = message.splitlines()[0].strip() if message else ''

    return message or type(error).__name__
