import os

from abc import ABC, abstractmethod

from config import Config
from utils import SUPPORTED_AUDIO_EXTENSIONS, flatten_subfolders, list_subfolders

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
    def download_track(self, track_info):
        """ Downloads the best match for a track in the downloads folder
            The whole track is passed so a backend can match on an identifier
            rather than on its name, which is what causes wrong downloads
        """

    def search_query(self, track_info):
        """ Name query to fall back on when no identifier is usable """
        return f'{track_info.artists[0]} {track_info.title}' if track_info.artists else track_info.title

    def download(self, track_info):
        """ Downloads a track and returns the audio files it produced
            The folder is compared before and after so a track is never paired
            with a file that another download produced
        """
        root_folder = self.config.downloads.root_path
        previous_files = set(list_audio_files(root_folder))
        previous_subfolders = set(list_subfolders(root_folder))

        self.download_track(track_info)

        # Backends may group a track in a release sub-folder, only the ones
        # created by this download are flattened
        new_subfolders = set(list_subfolders(root_folder)) - previous_subfolders
        flatten_subfolders(root_folder, new_subfolders)

        return sorted(set(list_audio_files(root_folder)) - previous_files)
