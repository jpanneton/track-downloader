from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials

from backends.base import DownloadBackend
from deemix_client import DeemixClient

class DeezerBackend(DownloadBackend):
    """ Searches for tracks in Spotify and downloads them from Deezer """
    name = 'deezer'

    def connect(self):
        # Server-to-server authentication (only works with public playlists)
        self.spotify = Spotify(client_credentials_manager=SpotifyClientCredentials(
            client_id=self.config.spotify.client_id,
            client_secret=self.config.spotify.client_secret
        ))

        self.deemix = DeemixClient(
            config_folder="./config/deemix",
            arl=self.config.deezer.deezer_arl,
            client_id=self.config.spotify.client_id,
            client_secret=self.config.spotify.client_secret
        )

    def download_query(self, query: str):
        # Deezer is reached through a Spotify track URL
        results = self.spotify.search(q=query, type='track', limit=1)['tracks']['items']
        if not results:
            print(f"WARNING: Track not found in Spotify using '{query}'")
            return

        # Use first result (best match)
        track_url = results[0]['external_urls']['spotify']

        self.deemix.download(
            urls=[track_url],
            path=self.config.downloads.root_folder,
            flac=self.config.downloads.lossless
        )
