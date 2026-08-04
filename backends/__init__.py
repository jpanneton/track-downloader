from config import Config

from backends.base import DownloadBackend
from backends.deezer import DeezerBackend
from backends.qobuz import QobuzBackend

# Every selectable download backend, the config editor lists these
BACKENDS = {
    backend.name: backend
    for backend in (DeezerBackend, QobuzBackend)
}

def create_backend(config: Config) -> DownloadBackend:
    """ Creates the backend selected in the config """
    backend = BACKENDS.get(config.downloads.backend)
    if not backend:
        raise ValueError(f"Invalid download backend '{config.downloads.backend}'")

    return backend(config)
