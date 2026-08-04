from config import Config
from models import PlaylistInfo
from utils import extract_website_name

from sources.soundcloud import extract_soundcloud_playlist_info
from sources.spotify import extract_spotify_playlist_info

def extract_playlist_info(config: Config, playlist_url: str):
    """ Extracts the info of tracks in a playlist """
    website_name = extract_website_name(playlist_url)
    if website_name == 'soundcloud':
        return extract_soundcloud_playlist_info(config, playlist_url)
    elif website_name == 'spotify':
        return extract_spotify_playlist_info(config, playlist_url)
    else:
        print(f"ERROR: Invalid playlist URL")
        return PlaylistInfo()
