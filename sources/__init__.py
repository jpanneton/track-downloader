import logging

from config import Config
from errors import PlaylistError
from utils import extract_website_name

from sources.soundcloud import extract_soundcloud_playlist_info
from sources.spotify import extract_spotify_playlist_info

logger = logging.getLogger(__name__)

# Every website a playlist can be read from
SOURCES = {
    'soundcloud': extract_soundcloud_playlist_info,
    'spotify': extract_spotify_playlist_info
}

def extract_playlist_info(config: Config, playlist_url: str):
    """ Extracts the info of tracks in a playlist """
    if not playlist_url.strip():
        raise PlaylistError("No playlist URL given.")

    extract = SOURCES.get(extract_website_name(playlist_url))
    if not extract:
        raise PlaylistError(
            f"Unsupported playlist URL: {playlist_url}. "
            f"Supported websites: {', '.join(SOURCES)}."
        )

    return extract(config, playlist_url)
