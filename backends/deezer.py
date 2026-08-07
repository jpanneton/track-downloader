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

    def find_track_url(self, track_info):
        """ Finds the Spotify track to hand over to Deezer """
        # The playlist already identified the track, searching again for it
        # would only risk landing on a different recording
        if track_info.source_url and 'spotify' in track_info.source_url:
            return track_info.source_url

        # An ISRC identifies the exact recording, a name does not
        if track_info.isrc:
            results = self.search(f'isrc:{track_info.isrc}')
            if results:
                return results[0]['external_urls']['spotify']
            logger.warning(f"No Spotify track with ISRC {track_info.isrc}, falling back to the name")

        query = self.search_query(track_info)
        results = self.search(query)
        if not results:
            logger.warning(f"Track not found in Spotify using '{query}'")
            return None

        # Use first result (best match)
        return results[0]['external_urls']['spotify']

    def search(self, query: str):
        try:
            return self.spotify.search(q=query, type='track', limit=1)['tracks']['items']
        except Exception as e:
            raise BackendError(f"Spotify search failed: {format_error(e)}")

    def download_track(self, track_info):
        # Deezer is reached through a Spotify track URL
        track_url = self.find_track_url(track_info)
        if not track_url:
            return

        self.deemix.download(
            urls=[track_url],
            path=self.config.downloads.root_path,
            flac=self.config.downloads.lossless
        )
