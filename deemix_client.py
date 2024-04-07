import os
import shutil

from deemix import generateDownloadObject
from deemix.settings import load as loadSettings
from deemix.utils import formatListener
from deemix.downloader import Downloader
from deemix.itemgen import GenerationError
from deemix.plugins.spotify import Spotify

from deezer import Deezer
from deezer import TrackFormats

class DeemixClient:
    class LogListener:
        @classmethod
        def send(cls, key, value=None):
            logString = formatListener(key, value)
            if logString:
                print(logString)

    def __init__(self, config_folder: str, arl: str, client_id: str, client_secret: str):
        self.deezer = Deezer()
        success = self.deezer.login_via_arl(arl.strip())
        assert(success)

        self.config_folder = config_folder
        self.settings = loadSettings(config_folder)
        self.listener = self.LogListener()

        # Setup Spotify plugin
        self.plugins = {
            "spotify": Spotify(configFolder=config_folder)
        }
        self.plugins["spotify"].setup()
        self.plugins["spotify"].setCredentials(
            clientId=client_id,
            clientSecret=client_secret
        )

    def __del__(self):
        # Delete Spotify config folder when done
        spotify_config_folder = os.path.join(self.config_folder, 'spotify')
        if os.path.exists(spotify_config_folder):
            shutil.rmtree(spotify_config_folder)

    def download(self, urls: list[str], path: str, flac=False):
        """ Downloads a list of Spotify track URLs """
        self.settings['downloadLocation'] = path
        bitrate = TrackFormats.FLAC if flac else TrackFormats.MP3_320

        download_objects = []

        for url in urls:
            try:
                download_object = generateDownloadObject(self.deezer, url, bitrate, self.plugins, self.listener)
            except GenerationError as e:
                print(f"{e.link}: {e.message}")
                continue
            if isinstance(download_object, list):
                download_objects += download_object
            else:
                download_objects.append(download_object)

        for obj in download_objects:
            if obj.__type__ == "Convertable":
                obj = self.plugins[obj.plugin].convert(self.deezer, obj, self.settings, self.listener)
            Downloader(self.deezer, obj, self.settings, self.listener).start()
