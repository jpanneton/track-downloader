import logging

from spotipy import Spotify
from spotipy.cache_handler import CacheFileHandler
from spotipy.exceptions import SpotifyException
from spotipy.oauth2 import SpotifyClientCredentials, SpotifyOAuth, SpotifyOauthError

from config import Config, require_settings
from errors import ConfigurationError, PlaylistError, format_error
from models import PlaylistInfo, TrackInfo
from paths import app_path
from utils import extract_spotify_playlist_id, format_track_name

logger = logging.getLogger(__name__)

# Every playlist is private as far as the API is concerned, a public one
# included, so reading the account's own playlists needs both of these
USER_SCOPES = 'playlist-read-private playlist-read-collaborative'

# Where the login is remembered, so the browser only opens the first time
TOKEN_CACHE_PATH = app_path('config', 'spotify_token.json')

def create_spotify_client(config: Config):
    """ Creates an authenticated Spotify client """
    require_settings(
        'Spotify',
        client_id=config.spotify.client_id,
        client_secret=config.spotify.client_secret
    )

    if config.spotify.user_login:
        return create_user_client(config)

    try:
        # Server-to-server authentication, no user is signed in. Only an app in
        # Extended Quota Mode may still read a playlist this way.
        return Spotify(client_credentials_manager=SpotifyClientCredentials(
            client_id=config.spotify.client_id,
            client_secret=config.spotify.client_secret
        ))
    except SpotifyOauthError as e:
        raise ConfigurationError(f"Could not authenticate with Spotify: {format_error(e)}")

def create_user_client(config: Config):
    """ Creates a client acting for a signed-in Spotify account

        An app in Development Mode is no longer allowed to read a playlist as
        itself, so the account that owns the playlists has to authorise it once
    """
    require_settings('Spotify', redirect_uri=config.spotify.redirect_uri)

    auth = SpotifyOAuth(
        client_id=config.spotify.client_id,
        client_secret=config.spotify.client_secret,
        redirect_uri=config.spotify.redirect_uri,
        scope=USER_SCOPES,
        cache_handler=CacheFileHandler(cache_path=str(TOKEN_CACHE_PATH)),
        open_browser=True
    )

    try:
        # The window has nothing to show while the browser is open, so say what
        # is happening before it blocks. Only the first login needs it, the
        # cached token is refreshed without asking again.
        if not auth.cache_handler.get_cached_token():
            logger.info("Waiting for the Spotify login to finish in the browser...")

        # Sign in now rather than on the first request, so a failure is reported
        # before a download starts and the browser never opens halfway through
        auth.get_access_token(as_dict=False)
    except SpotifyOauthError as e:
        raise ConfigurationError(f"Could not sign in to Spotify: {format_error(e)}")

    return Spotify(auth_manager=auth)

def extract_spotify_playlist_info(config: Config, playlist_url: str):
    """ Extracts the info of tracks in a Spotify playlist """
    logger.info("Extracting Spotify playlist info...")

    playlist_id = extract_spotify_playlist_id(playlist_url)
    if playlist_id is None:
        raise PlaylistError(f"Not a valid Spotify playlist URL: {playlist_url}")

    spotify = create_spotify_client(config)

    # Collect every page, a single response holds 100 tracks at most
    playlist = []
    try:
        # /playlists/{id}/tracks was removed in February 2026, an app created
        # after that only reaches a playlist through /items
        page = spotify.playlist_items(playlist_id)
        while page:
            playlist.extend(page['items'])
            page = spotify.next(page) if page['next'] else None
    except SpotifyOauthError as e:
        raise ConfigurationError(f"Spotify rejected the credentials: {format_error(e)}")
    except SpotifyException as e:
        if e.http_status == 401:
            # /items is scoped to a signed-in user, and these credentials
            # authenticate the app itself. Extended Quota Mode is exempt from
            # that, Development Mode is not, so the same call works elsewhere.
            raise PlaylistError(
                "Spotify wants a signed-in user for this playlist (HTTP 401). The app "
                "authenticates as itself, which an app in Development Mode may no longer do "
                "to read a playlist. Use the credentials of an app in Extended Quota Mode."
            )

        if e.http_status == 403:
            # Since February 2026 an app in Development Mode only reaches the
            # playlists of the account it is registered under, public or not
            raise PlaylistError(
                "Spotify refused the playlist (HTTP 403). An app in Development Mode may only "
                "read playlists owned by the account it is registered under, so being public "
                "does not help. Use a playlist from that account, or the credentials of an "
                "app in Extended Quota Mode."
            )

        if e.http_status == 404:
            # Spotify answers 404 for a playlist it won't show to these
            # credentials, so a missing one and a private one look the same
            raise PlaylistError(
                "No Spotify playlist at that URL (HTTP 404). "
                "Make sure the link points at a playlist and that it is public."
            )

        raise PlaylistError(
            f"Could not read the Spotify playlist (HTTP {e.http_status}): {format_error(e)}"
        )

    playlist_info = PlaylistInfo()
    for track in playlist:
        # Local files and tracks unavailable in the market have no track data
        if not track.get('track') or track['track'].get('is_local'):
            logger.warning("Skipping unavailable track")
            continue

        # Check if the track is part of an album (not in a compilation nor a single)
        is_in_album = (track['track']['album']['album_type'] == 'album' or
            (track['track']['album']['album_type'] == 'single' and
             track['track']['track_number'] != 1))

        # Check if the track is a remix
        is_remix = any(track['track']['name'].lower().endswith(token) for token in config.metadata.supported_remix_tokens)

        # Get album artists
        album_artists = [t['name'] for t in track['track']['album']['artists']]
        if len(album_artists) > 1 and is_remix:
            album_artists.pop() # Remove last artist (usually the remix artist)

        # Fill track info
        track_info = TrackInfo()
        track_info.title = format_track_name(config, track['track']['name'], False)
        track_info.artists = [t['name'] for t in track['track']['artists']]
        track_info.name = f"{' & '.join(album_artists)} - {track_info.title}"
        track_info.album = (track['track']['album']['name'] if is_in_album else
            track_info.title if config.metadata.tag_single_album else '')
        track_info.album_artists = album_artists if track_info.album else []
        track_info.year = track['track']['album']['release_date'].split('-')[0]
        track_info.number = track['track']['track_number']
        track_info.genre = config.metadata.default_genre
        track_info.artwork_url = ''
        track_info.download_url = ''
        track_info.category = 'Buy'

        # Identifiers a backend can match on instead of searching by name
        track_info.isrc = track['track'].get('external_ids', {}).get('isrc', '')
        track_info.source_url = track['track'].get('external_urls', {}).get('spotify', '')

        # Add to buy downloads
        playlist_info.buy_downloads.append(track_info)

    return playlist_info

#--------------------------------------------------------------------
# MAIN
#--------------------------------------------------------------------
