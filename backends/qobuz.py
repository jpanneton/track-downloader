import logging

from qobuz_dl.core import QobuzDL
from qobuz_dl.exceptions import AuthenticationError

from backends.base import DownloadBackend
from config import require_settings
from errors import BackendError, format_error

logger = logging.getLogger(__name__)

class QobuzBackend(DownloadBackend):
    """ Searches for tracks in Qobuz and downloads them """
    name = 'qobuz'

    def connect(self):
        logging.getLogger('qobuz_dl').setLevel(logging.WARNING)

        require_settings(
            'Qobuz',
            user_id=self.config.qobuz.user_id,
            token=self.config.qobuz.token,
            app_id=self.config.qobuz.app_id,
            app_secret=self.config.qobuz.app_secret
        )

        self.qobuz = QobuzDL(
            directory=self.config.downloads.root_path,
            quality=6 if self.config.downloads.lossless else 5,
            embed_art=True,
            lucky_type="track"
        )

        # The app credentials always come from the config, a user auth token is
        # only accepted by the app it was issued for so the ones advertised by
        # the Qobuz website would be rejected
        app_id = str(self.config.qobuz.app_id)

        try:
            self.qobuz.initialize_client(
                str(self.config.qobuz.user_id),
                str(self.config.qobuz.token),
                app_id,
                # Must stay a list, each secret is probed individually
                [str(self.config.qobuz.app_secret)]
            )
        except AuthenticationError:
            # Qobuz rejects a valid token the same way as an invalid one when it
            # was issued for another app, so point at both possible causes
            raise BackendError(
                f"Qobuz rejected the credentials. Make sure the token was issued for app ID {app_id}."
            )
        except Exception as e:
            raise BackendError(f"Could not connect to Qobuz: {format_error(e)}")

    def find_track_id(self, track_info):
        """ Finds the Qobuz track id of a recording from its ISRC
            Qobuz reports the ISRC of its results, so the match can be checked
            instead of trusting whichever track the search ranked first
        """
        if not track_info.isrc:
            return None

        try:
            results = self.qobuz.client.search_tracks(track_info.isrc, 10)['tracks']['items']
        except Exception as e:
            logger.warning(f"Qobuz search by ISRC failed: {format_error(e)}")
            return None

        for item in results:
            if item.get('isrc') == track_info.isrc:
                return item['id']

        logger.warning(f"No Qobuz track with ISRC {track_info.isrc}, falling back to the name")
        return None

    def download_track(self, track_info):
        track_id = self.find_track_id(track_info)

        try:
            if track_id:
                self.qobuz.download_from_id(str(track_id), album=False)
                return

            # Nothing identifies the track, its name is all there is
            query = self.search_query(track_info)

            # Returns None when the query is too short or the type is invalid
            if not self.qobuz.lucky_mode(query):
                logger.warning(f"Track not found in Qobuz using '{query}'")
        except Exception as e:
            raise BackendError(f"Qobuz download failed: {format_error(e)}")
