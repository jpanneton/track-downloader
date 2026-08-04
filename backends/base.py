import os

from abc import ABC, abstractmethod

from config import Config
from utils import SUPPORTED_AUDIO_EXTENSIONS, flatten_folder

def list_audio_files(folder_path):
    """ Lists the audio files sitting directly in a folder """
    if not os.path.exists(folder_path):
        return []

    return [
        filename for filename in os.listdir(folder_path)
        if filename.lower().endswith(SUPPORTED_AUDIO_EXTENSIONS)
        and os.path.isfile(os.path.join(folder_path, filename))
    ]

class DownloadBackend(ABC):
    """ Downloads tracks matching a search query """
    name = ''

    def __init__(self, config: Config):
        self.config = config

    @abstractmethod
    def connect(self):
        """ Authenticates with the service
            Raises an exception describing the cause when it fails
        """

    @abstractmethod
    def download_query(self, query: str):
        """ Downloads the best match for a query in the downloads folder """

    def download(self, query: str):
        """ Downloads a query and returns the audio files it produced
            The folder is compared before and after so a track is never paired
            with a file that another query downloaded
        """
        root_folder = self.config.downloads.root_folder
        before = set(list_audio_files(root_folder))

        self.download_query(query)

        # Backends may group a track in a release sub-folder
        flatten_folder(root_folder)

        return sorted(set(list_audio_files(root_folder)) - before)
