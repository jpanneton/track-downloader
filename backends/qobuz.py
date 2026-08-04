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
            directory=self.config.downloads.root_folder,
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

    def download_query(self, query: str):
        try:
            # Returns None when the query is too short or the type is invalid
            found = self.qobuz.lucky_mode(query)
        except Exception as e:
            raise BackendError(f"Qobuz download failed: {format_error(e)}")

        if not found:
            logger.warning(f"Track not found in Qobuz using '{query}'")
