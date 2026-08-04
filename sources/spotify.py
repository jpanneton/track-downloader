from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials

from config import Config
from models import PlaylistInfo, TrackInfo
from utils import extract_spotify_playlist_id, format_track_name

def extract_spotify_playlist_info(config: Config, playlist_url: str):
    """ Extracts the info of tracks in a Spotify playlist """
    print("INFO: Extracting Spotify playlist info...")

    playlist_id = extract_spotify_playlist_id(playlist_url)
    if playlist_id == None:
        print("ERROR: Invalid Spotify playlist")
        return

    # Server-to-server authentication (only works with public playlists)
    spotify = Spotify(client_credentials_manager=SpotifyClientCredentials(
        client_id=config.spotify.client_id,
        client_secret=config.spotify.client_secret
    ))

    # Collect every page, a single response holds 100 tracks at most
    playlist = []
    page = spotify.playlist_tracks(playlist_id)
    while page:
        playlist.extend(page['items'])
        page = spotify.next(page) if page['next'] else None

    playlist_info = PlaylistInfo()
    for track in playlist:
        # Local files and tracks unavailable in the market have no track data
        if not track.get('track') or track['track'].get('is_local'):
            print("WARNING: Skipping unavailable track")
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

        # Add to buy downloads
        playlist_info.buy_downloads.append(track_info)

    return playlist_info

#--------------------------------------------------------------------
# MAIN
#--------------------------------------------------------------------
