import logging

from sclib import (
    SoundcloudAPI,
    Playlist as SoundcloudPlaylist
)

from config import Config
from errors import PlaylistError, format_error
from models import PlaylistInfo, TrackInfo
from utils import format_track_name, is_download_gate

logger = logging.getLogger(__name__)

def extract_soundcloud_playlist_info(config: Config, playlist_url: str):
    """ Extracts the info of tracks in a SoundCloud playlist """
    logger.info("Extracting SoundCloud playlist info...")

    try:
        api = SoundcloudAPI()
        playlist = api.resolve(playlist_url)
    except Exception:
        # The library fails with an internal error on anything unexpected,
        # keep the details for debugging and report something actionable
        logger.debug(f"SoundCloud resolve failed for {playlist_url}", exc_info=True)
        raise PlaylistError(
            f"Could not read the SoundCloud playlist: {playlist_url}. "
            "Make sure the URL points to an existing playlist or album."
        )

    # A single track or a user profile resolves to another type
    if not isinstance(playlist, SoundcloudPlaylist):
        raise PlaylistError(
            f"SoundCloud URL is not a playlist: {playlist_url}. "
            "Use the URL of a playlist or an album."
        )

    playlist_info = PlaylistInfo()
    for track in playlist.tracks:
        # Fill track info
        track_info = TrackInfo()
        try:
            track_info.title = format_track_name(config, track.title, True)
            track_info.artists = [track.artist]
            track_info.name = f"{' & '.join(track_info.artists)} - {track_info.title}"
            track_info.album = track_info.title if config.metadata.tag_single_album else ''
            track_info.album_artists = []
            track_info.year = track.display_date.split('-')[0] if track.display_date else ''
            track_info.number = 1
            track_info.genre = config.metadata.default_genre
            track_info.artwork_url = track.artwork_url.replace('large', 't500x500') if track.artwork_url else ''
        except Exception as e:
            # One unusable track shouldn't discard the whole playlist
            logger.warning(f"Skipping track '{getattr(track, 'title', '?')}': {format_error(e)}")
            continue

        # Handle download category
        if track.downloadable:
            track_info.download_url = track.permalink_url # download_url requires client ID
            track_info.category = 'Direct'
            playlist_info.direct_downloads.append(track_info)
        elif track.purchase_url and is_download_gate(config, track.purchase_url):
            track_info.download_url = track.purchase_url
            track_info.category = 'Gate'
            playlist_info.gate_downloads.append(track_info)
        else:
            track_info.download_url = ''
            track_info.category = 'Buy'
            playlist_info.buy_downloads.append(track_info)

    return playlist_info
