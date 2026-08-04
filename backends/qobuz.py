import logging

from qobuz_dl.core import QobuzDL
from qobuz_dl.exceptions import AuthenticationError

from backends.base import DownloadBackend

class QobuzBackend(DownloadBackend):
    """ Searches for tracks in Qobuz and downloads them """
    name = 'qobuz'

    def connect(self):
        logging.getLogger('qobuz_dl').setLevel(logging.WARNING)

        self.qobuz = QobuzDL(
            directory=self.config.downloads.root_folder,
            quality=6 if self.config.downloads.lossless else 5,
            embed_art=True,
            lucky_type="track"
        )

        app_id, secrets = self._resolve_app_credentials()

        try:
            self.qobuz.initialize_client(
                str(self.config.qobuz.user_id),
                str(self.config.qobuz.token),
                app_id,
                secrets # Must stay a list, each secret is probed individually
            )
        except AuthenticationError:
            # Qobuz rejects a valid token the same way as an invalid one when it
            # was issued for another app, so point at both possible causes
            raise AuthenticationError(
                f"Invalid credentials. Make sure the token was issued for app ID {app_id}."
            )

    def _resolve_app_credentials(self):
        """ Returns the app ID and secrets to authenticate with
            A user auth token is only accepted by the app it was issued for, so
            the scraped app credentials can't be used with a configured token
        """
        if self.config.qobuz.app_id and self.config.qobuz.app_secret:
            return str(self.config.qobuz.app_id), [str(self.config.qobuz.app_secret)]

        if self.config.qobuz.user_id and self.config.qobuz.token:
            raise ValueError(
                "Missing Qobuz app ID and secret. A user auth token is only valid under "
                "the app ID it was issued for, so scraped app credentials are rejected."
            )

        self.qobuz.get_tokens() # Get 'app_id' and 'secrets' attributes
        return str(self.qobuz.app_id), self.qobuz.secrets

    def download_query(self, query: str):
        # Returns None when the query is too short or the type is invalid
        if not self.qobuz.lucky_mode(query):
            print(f"WARNING: Track not found in Qobuz using '{query}'")
