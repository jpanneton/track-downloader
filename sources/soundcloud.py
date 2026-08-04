import logging

from sclib import (
    SoundcloudAPI,
    Playlist as SoundcloudPlaylist
)

from config import Config
from models import PlaylistInfo, TrackInfo
from utils import format_track_name, is_download_gate

logger = logging.getLogger(__name__)

def extract_soundcloud_playlist_info(config: Config, playlist_url: str):
    """ Extracts the info of tracks in a SoundCloud playlist """
    logger.info("Extracting SoundCloud playlist info...")

    api = SoundcloudAPI()
    playlist = api.resolve(playlist_url)

    # Make sure the playlist was resolved properly
    assert type(playlist) is SoundcloudPlaylist

    playlist_info = PlaylistInfo()
    for track in playlist.tracks:
        # Fill track info
        track_info = TrackInfo()
        track_info.title = format_track_name(config, track.title, True)
        track_info.artists = [track.artist]
        track_info.name = f"{' & '.join(track_info.artists)} - {track_info.title}"
        track_info.album = track_info.title if config.metadata.tag_single_album else ''
        track_info.album_artists = []
        track_info.year = track.display_date.split('-')[0]
        track_info.number = 1
        track_info.genre = config.metadata.default_genre
        track_info.artwork_url = track.artwork_url.replace('large', 't500x500') if track.artwork_url else ''

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
