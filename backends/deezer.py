import logging

from backends.base import DownloadBackend
from paths import app_path
from config import require_settings
from deemix_client import DeemixClient
from errors import BackendError, format_error
from sources.spotify import create_spotify_client

logger = logging.getLogger(__name__)

class DeezerBackend(DownloadBackend):
    """ Searches for tracks in Spotify and downloads them from Deezer """
    name = 'deezer'

    def connect(self):
        # Tracks are looked up in Spotify before being fetched from Deezer
        self.spotify = create_spotify_client(self.config)

        require_settings('Deezer', deezer_arl=self.config.deezer.deezer_arl)

        self.deemix = DeemixClient(
            config_folder=str(app_path("config", "deemix")),
            arl=self.config.deezer.deezer_arl,
            client_id=self.config.spotify.client_id,
            client_secret=self.config.spotify.client_secret
        )

    def download_query(self, query: str):
        # Deezer is reached through a Spotify track URL
        try:
            results = self.spotify.search(q=query, type='track', limit=1)['tracks']['items']
        except Exception as e:
            raise BackendError(f"Spotify search failed: {format_error(e)}")

        if not results:
            logger.warning(f"Track not found in Spotify using '{query}'")
            return

        # Use first result (best match)
        track_url = results[0]['external_urls']['spotify']

        self.deemix.download(
            urls=[track_url],
            path=self.config.downloads.root_path,
            flac=self.config.downloads.lossless
        )
