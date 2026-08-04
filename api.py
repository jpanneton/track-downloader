import logging
import os
import re
import requests
import shutil

from dataclasses import dataclass, field

from deemix_client import DeemixClient

from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC as MutagenFLAC
from mutagen.mp3 import MP3 as MutagenMP3

from pydub import AudioSegment

from qobuz_dl.core import QobuzDL
from qobuz_dl.exceptions import AuthenticationError

from sclib import (
    SoundcloudAPI,
    Playlist as SoundcloudPlaylist
)

from selenium.webdriver import Chrome as ChromeDriver
from selenium.webdriver.chrome.options import Options as ChromeOptions

from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials

from urllib.parse import urlparse

from config import Config

#--------------------------------------------------------------------
# CONSTANTS
#--------------------------------------------------------------------

SUPPORTED_AUDIO_EXTENSIONS = ('.flac', '.mp3', '.wav')

# Folder where files that failed validation are kept for inspection
REJECTED_FOLDER_NAME = '_rejected'

#--------------------------------------------------------------------
# TYPES
#--------------------------------------------------------------------

@dataclass(slots=True)
class TrackInfo:
    """ Single track info """
    name: str = ''
    title: str = ''
    artists: list[str] = field(default_factory=list)
    album: str = ''
    album_artists: list[str] = field(default_factory=list)
    year: str = ''
    number: int = 1
    genre: str = ''
    artwork_url: str = ''
    download_url: str = ''
    category: str = ''

class PlaylistInfo:
    """ Track info collection """
    def __init__(self):
        self.direct_downloads: list[TrackInfo] = []
        self.gate_downloads: list[TrackInfo] = []
        self.buy_downloads: list[TrackInfo] = []

    def get_flat_list(self):
        """ Returns a flat list containing all the concatenated track infos (gate, direct, buy) """
        track_infos = []
        for track_info in self.gate_downloads:
            track_infos.append(track_info)
        for track_info in self.direct_downloads:
            track_infos.append(track_info)
        for track_info in self.buy_downloads:
            track_infos.append(track_info)
        return track_infos

    @classmethod
    def from_flat_list(cls, track_infos: list[TrackInfo]):
        """ Generates playlist info from concatenated flat list of track infos (gate, direct, buy) """
        result = cls()
        for track_info in track_infos:
            if track_info.category == 'Gate':
                result.gate_downloads.append(track_info)
            elif track_info.category == 'Direct':
                result.direct_downloads.append(track_info)
            elif track_info.category == 'Buy':
                result.buy_downloads.append(track_info)
        return result

#--------------------------------------------------------------------
# FILE HELPERS
#--------------------------------------------------------------------
    
def list_downloaded_files(config: Config, ignored_files=()):
    """ Lists the files sitting in the downloads folder excluding sub-folders """
    root_folder = config.downloads.root_folder
    if not os.path.exists(root_folder):
        return []

    return [
        filename for filename in os.listdir(root_folder)
        if filename not in ignored_files
        and os.path.isfile(os.path.join(root_folder, filename))
    ]

def quarantine_file(config: Config, source_path):
    """ Moves a file that failed validation out of the downloads folder
        Keeping it makes a wrong rejection recoverable and inspectable
    """
    rejected_folder = os.path.join(config.downloads.root_folder, REJECTED_FOLDER_NAME)
    os.makedirs(rejected_folder, exist_ok=True)

    filename = os.path.basename(source_path)
    name, extension = os.path.splitext(filename)

    # Avoid overwriting a previously rejected file
    destination_path = os.path.join(rejected_folder, filename)
    duplicate_index = 1
    while os.path.exists(destination_path):
        destination_path = os.path.join(rejected_folder, f'{name} ({duplicate_index}){extension}')
        duplicate_index += 1

    shutil.move(source_path, destination_path)
    return destination_path

def download_file(url, dest_path):
    """ Downloads a file from a URL """
    response = requests.get(url)
    if response.status_code == 200:
        with open(dest_path, 'wb') as handler:
            handler.write(response.content)
    else:
        print(f"Failed to download {url}")

def is_file_downloaded(config: Config, filename):
    """ Checks if a file has been properly downloaded in the downloads folder """
    return os.path.isfile(os.path.join(config.downloads.root_folder, filename))

def flatten_folder(folder_path):
    """ Moves every audio file from sub-folders up to the root folder
        Backends such as Qobuz group tracks in a release sub-folder along with
        extra files (cover art, booklet, playlist) that must not be processed
    """
    if not os.path.exists(folder_path):
        return

    for root, _, filenames in os.walk(folder_path, topdown=False):
        if root == folder_path:
            continue

        for filename in filenames:
            source_path = os.path.join(root, filename)

            # Discard anything that isn't an audio file
            if not filename.lower().endswith(SUPPORTED_AUDIO_EXTENSIONS):
                os.remove(source_path)
                continue

            # Avoid overwriting a file that was already moved up
            name, extension = os.path.splitext(filename)
            destination_path = os.path.join(folder_path, filename)
            duplicate_index = 1
            while os.path.exists(destination_path):
                destination_path = os.path.join(folder_path, f'{name} ({duplicate_index}){extension}')
                duplicate_index += 1

            shutil.move(source_path, destination_path)

        # Remove the sub-folder now that it has been emptied
        os.rmdir(root)

#--------------------------------------------------------------------
# STRING HELPERS
#--------------------------------------------------------------------

def extract_website_name(url: str):
    """ Extracts the name of the website from a URL """
    parsed_url = urlparse(url)
    domain_parts = parsed_url.netloc.split('.')
    if len(domain_parts) >= 2:
        return domain_parts[-2]
    else:
        return None

def is_download_gate(config: Config, url: str):
    """ Checks if the URL points to a download gate """
    return extract_website_name(url) in config.soundcloud.supported_download_gates

def format_track_name(config: Config, name: str, remove_noise: bool):
    """ Formats the name of a track by performing the following:
        1. Replaces any square brackets with parentheses
        2. Removes trailing parentheses with useless information (e.g. "Free Download") if remove_noise = True
        3. Removes featuring artists if set in config
    """
    matches = []

    # Replace square brackets with parentheses
    name = name.translate(str.maketrans('[]','()'))
    result = name

    # Replace "- ABC Remix" with (ABC Remix) -> Spotify specific
    result = result.rsplit(' - ', 1)
    result = result[0] + f" ({result[1].strip()})" if len(result) == 2 else result[0]

    # Remove trailing parentheses with useless information (e.g. "Free Download")
    if remove_noise:
        pattern = re.compile(r'\s\((?!.*?\b(?:{}))[^()]*\)'.format('|'.join(map(re.escape, config.metadata.supported_remix_tokens))), re.IGNORECASE)
        matches.extend(pattern.findall(result))
        result = re.sub(pattern, '', result).strip()

    # Remove featuring artists
    if config.metadata.remove_feat_from_title:
        pattern = re.compile(r'\s*\((?:feat|ft)\..*?\)', re.IGNORECASE)
        matches.extend(pattern.findall(result))
        result = re.sub(pattern, '', result).strip()

    # Print changes
    if matches:
        print(f"Removed {matches} from '{name}'")

    return result

def extract_spotify_playlist_id(playlist_url):
    """ Extracts the ID from a Spotify playlist URL """
    playlist_id = playlist_url.split('playlist/')[-1].split('?')[0]
    # Base-62 identifier of 22 characters
    return playlist_id if len(playlist_id) == 22 else None

#--------------------------------------------------------------------
# DEEZER
#--------------------------------------------------------------------

def deezer_download(config: Config, queries):
    """ Searches for tracks in Spotify using a query and downloads them from Deezer """
    # Server-to-server authentication (only works with public playlists)
    spotify = Spotify(client_credentials_manager=SpotifyClientCredentials(
        client_id=config.spotify.client_id,
        client_secret=config.spotify.client_secret
    ))

    # Search for tracks
    track_urls = []
    query_indices = [] # Maps each URL back to the query it came from
    skipped_tracks = []

    for idx, query in enumerate(queries):
        results = spotify.search(q=query, type='track', limit=1)['tracks']['items']

        if results:
            # Use first result (best match)
            track_urls.append(results[0]['external_urls']['spotify'])
            query_indices.append(idx)
        else:
            print(f"WARNING: Track not found in Spotify using '{query}'")
            skipped_tracks.append(idx)

    # Init Deezer client
    deemix = DeemixClient(
        config_folder = "./config/deemix",
        arl=config.deezer.deezer_arl,
        client_id=config.spotify.client_id,
        client_secret=config.spotify.client_secret
    )

    # Download tracks
    skipped_urls = deemix.download(
        urls=track_urls,
        path=config.downloads.root_folder,
        flac=config.downloads.lossless
    )

    # Report skipped URLs as the queries they came from
    skipped_tracks.extend(query_indices[idx] for idx in skipped_urls)

    return sorted(skipped_tracks)

#--------------------------------------------------------------------
# QOBUZ
#--------------------------------------------------------------------

def qobuz_download(config: Config, queries):
    """ Searches for tracks in Qobuz using a query and downloads them """
    logger = logging.getLogger('qobuz_dl')
    logger.setLevel(logging.WARNING)

    # Init Qobuz client
    qobuz = QobuzDL(
        directory=config.downloads.root_folder,
        quality=6 if config.downloads.lossless else 5,
        embed_art=True,
        lucky_type="track"
    )
    # A user auth token is only accepted by the app it was issued for, so the
    # scraped app credentials can't be used to log in with a configured token
    if config.qobuz.app_id and config.qobuz.app_secret:
        app_id = str(config.qobuz.app_id)
        secrets = [str(config.qobuz.app_secret)]
    elif config.qobuz.user_id and config.qobuz.token:
        raise ValueError(
            "Missing Qobuz app ID and secret. A user auth token is only valid under "
            "the app ID it was issued for, so scraped app credentials are rejected."
        )
    else:
        qobuz.get_tokens() # Get 'app_id' and 'secrets' attributes
        app_id = str(qobuz.app_id)
        secrets = qobuz.secrets

    try:
        qobuz.initialize_client(
            str(config.qobuz.user_id),
            str(config.qobuz.token),
            app_id,
            secrets # Must stay a list, each secret is probed individually
        )
    except AuthenticationError:
        # Qobuz rejects a valid token the same way as an invalid one when it
        # was issued for another app, so point at both possible causes
        raise AuthenticationError(
            f"Invalid credentials. Make sure the token was issued for app ID {app_id}."
        )

    # Download tracks
    skipped_tracks = []
    for idx, query in enumerate(queries):
        try:
            # Returns None when the query is too short or the type is invalid
            if not qobuz.lucky_mode(query):
                skipped_tracks.append(idx)
        except Exception as e:
            print(f"WARNING: {e}")
            skipped_tracks.append(idx)
            continue

    # Qobuz groups each track in a release sub-folder
    flatten_folder(config.downloads.root_folder)

    return skipped_tracks

#--------------------------------------------------------------------
# SOUNDCLOUD
#--------------------------------------------------------------------

def extract_soundcloud_playlist_info(config: Config, playlist_url: str):
    """ Extracts the info of tracks in a SoundCloud playlist """
    print("INFO: Extracting SoundCloud playlist info...")

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

#--------------------------------------------------------------------
# SPOTIFY
#--------------------------------------------------------------------

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

def validate_file(config: Config, track_info: TrackInfo, track_metadata, filename):
    def extract_before_delimiter(s: str):
        return re.split(r'[\[\{\(\-\&\,]', s, maxsplit=1)[0].strip()

    def has_matching_or_no_tokens(str1: str, str2: str, tokens):
        tokens_in_str1 = { token for token in tokens if token in str1.lower() }
        tokens_in_str2 = { token for token in tokens if token in str2.lower() }

        if not tokens_in_str1 and not tokens_in_str2:
            return True  # No token in either string
        return bool(tokens_in_str1 & tokens_in_str2) # At least one shared token

    # Get the expected track info
    expected_title = track_info.title.lower()
    expected_artists = [
        artist.lower()
        for artist_list in (track_info.artists, track_info.album_artists)
        for artist in artist_list
    ]

    # Simplify the expectations 
    simplified_title = extract_before_delimiter(expected_title)
    simplified_artists = [extract_before_delimiter(artist) for artist in expected_artists]

    # Get the actual track info
    filename = filename.lower()
    actual_title = " ".join(track_metadata.get('title', [])).lower()
    actual_artists = " ".join(track_metadata.get('artist', []) + track_metadata.get('albumartist', [])).lower()

    # Title must match
    if simplified_title in actual_title or simplified_title in filename:
        # Artists must match (at least one)
        if any(artist in actual_artists or artist in filename for artist in simplified_artists):
            # Remix token must match (if any)
            remix_tokens = config.metadata.supported_remix_tokens
            if has_matching_or_no_tokens(expected_title, filename + actual_title, remix_tokens):
                return True
    return False

def process_flac(config: Config, track_info: TrackInfo, filename):
    """ Generates a properly tagged FLAC """
    # Make sure the destination FLAC folder exists
    os.makedirs(config.downloads.flac_folder, exist_ok=True)

    # Source path as downloaded in the downloads folder
    source_path = os.path.join(config.downloads.root_folder, filename)

    # Destination path with properly formatted file name
    destination_path = os.path.join(config.downloads.flac_folder, f'{track_info.name}.flac')

    # Update tags
    audiofile = MutagenFLAC(source_path)
    if not validate_file(config, track_info, audiofile, filename):
        quarantine_file(config, source_path)
        print(f"WARNING: {track_info.name} did not match, moved to '{REJECTED_FOLDER_NAME}'")
        return

    audiofile['title'] = track_info.title
    audiofile['artist'] = config.metadata.artist_delimiter.join(track_info.artists)
    audiofile['album'] = track_info.album
    audiofile['albumartist'] = config.metadata.artist_delimiter.join(track_info.album_artists)
    audiofile['year'] = track_info.year
    audiofile['genre'] = track_info.genre
    audiofile['tracknumber'] = str(track_info.number)
    audiofile.save()

    # Check if the file has expected quality
    bitrate = audiofile.info.bitrate // 1000

    if track_info.category == 'Buy' and not config.downloads.lossless:
        print(f"WARNING: {filename} is in flac format (expected mp3)")
    if bitrate <= 320:
        print(f"WARNING: {filename} has a bitrate of {bitrate} kbps (expected > 320)")

    # Move FLAC from downloads folder
    shutil.move(source_path, destination_path)

def process_mp3(config: Config, track_info: TrackInfo, filename):
    """ Generates a properly tagged MP3 """
    # Make sure the destination MP3 folder exists
    os.makedirs(config.downloads.mp3_folder, exist_ok=True)

    # Source path as downloaded in the downloads folder
    source_path = os.path.join(config.downloads.root_folder, filename)

    # Destination path with properly formatted file name
    destination_path = os.path.join(config.downloads.mp3_folder, f'{track_info.name}.mp3')

    # Update tags
    audiofile = MutagenMP3(source_path, ID3=EasyID3)
    if not validate_file(config, track_info, audiofile, filename):
        quarantine_file(config, source_path)
        print(f"WARNING: {track_info.name} did not match, moved to '{REJECTED_FOLDER_NAME}'")
        return

    audiofile['title'] = track_info.title
    audiofile['artist'] = config.metadata.artist_delimiter.join(track_info.artists)
    audiofile['album'] = track_info.album
    audiofile['albumartist'] = config.metadata.artist_delimiter.join(track_info.album_artists)
    audiofile['date'] = track_info.year
    audiofile['genre'] = track_info.genre
    audiofile['tracknumber'] = str(track_info.number)
    audiofile.save(v1=1, v2_version=3)

    # Check if the file has expected quality
    bitrate = audiofile.info.bitrate // 1000

    if track_info.category == 'Buy' and config.downloads.lossless:
        print(f"WARNING: {filename} is in mp3 format (expected flac)")
    if bitrate != 320:
        print(f"WARNING: {filename} has a bitrate of {bitrate} kbps (expected 320)")

    # Move MP3 from downloads folder
    shutil.move(source_path, destination_path)

def process_wav(config: Config, track_info: TrackInfo, filename):
    """ Converts a WAV to a properly tagged MP3 """
    # Make sure the destination MP3 and WAV folders exist
    os.makedirs(config.downloads.mp3_folder, exist_ok=True)
    os.makedirs(config.downloads.wav_folder, exist_ok=True)

    # Source path as downloaded in the downloads folder
    source_path = os.path.join(config.downloads.root_folder, filename)

    # Destination paths with properly formatted file names
    dest_path_mp3 = os.path.join(config.downloads.mp3_folder, f'{track_info.name}.mp3')
    dest_path_wav = os.path.join(config.downloads.wav_folder, f'{track_info.name}.wav')

    # Load the WAV file
    audio = AudioSegment.from_wav(source_path)

    # Set metadata for the MP3 file
    metadata = {
        'title': track_info.title,
        'artist': config.metadata.artist_delimiter.join(track_info.artists),
        'album': track_info.album,
        'albumartist': config.metadata.artist_delimiter.join(track_info.album_artists),
        'date': track_info.year,
        'genre': track_info.genre,
        'track': track_info.number
    }

    # Download the artwork from the URL and save it to a temporary file
    artwork_path = None
    if track_info.artwork_url:
        artwork_path = os.path.join(config.downloads.root_folder, 'Artwork.jpg')
        download_file(track_info.artwork_url, artwork_path)

    # Export the audio as an MP3 file with the specified bitrate and metadata
    audio.export(dest_path_mp3, format="mp3", bitrate="320k", id3v2_version="3", tags=metadata, cover=artwork_path)

    # Set ID3v1 tags
    audiofile = EasyID3(dest_path_mp3)
    audiofile['date'] = track_info.year
    audiofile.save(v1=1, v2_version=3)

    # Delete temporary artwork file
    if artwork_path and os.path.exists(artwork_path):
        os.remove(artwork_path)

    # Move WAV from downloads folder
    shutil.move(source_path, dest_path_wav)

def process_file(config: Config, track_info: TrackInfo, filename):
    """ Processes a downloaded audio file (MP3 or WAV) """
    # Make sure the file exists in the downloads folder
    if is_file_downloaded(config, filename):
        # Dispatch the processing to the corrresponding procedure
        if filename.endswith('.flac'):
            process_flac(config, track_info, filename)
        elif filename.endswith('.mp3'):
            process_mp3(config, track_info, filename)
        elif filename.endswith('.wav'):
            process_wav(config, track_info, filename)
    else:
        print(f"Missing file {filename}")

def download_direct_downloads(config: Config, track_infos: list[TrackInfo]):
    """ Downloads tracks that have a direct download link
        Unused for now because direct downloads require a client ID
    """
    for track_info in track_infos:
        print(f'* {track_info.name}')

        # Download file to downloads folder
        filename = f'{track_info.name}.wav'
        dest_path = os.path.join(config.downloads.root_folder, filename)
        download_file(track_info.download_url, dest_path)

        # Process the file
        process_file(config, track_info, filename)

def download_web_downloads(config: Config, track_infos: list[TrackInfo], web_driver, ignored_files=()):
    """ Downloads tracks that require user action (direct download, download gate, etc.) """
    for track_info in track_infos:
        print(f'* {track_info.name}')

        if web_driver:
            # Open a page with the download gate
            web_driver.get(track_info.download_url)

            # Prompt the user to continue after downloading
            input("Download track then press Enter to continue...")
        else:
            # Prompt the user to continue after downloading
            input("Download track manually, move it to 'downloads' folder then press Enter to continue...")

        # Process the file
        filenames = list_downloaded_files(config, ignored_files)
        if len(filenames) == 1:
            process_file(config, track_info, filenames[0])
        elif len(filenames) == 0:
            print("SKIPPED: Track hasn't been downloaded by the user")
        else:
            print("ERROR: Found more than one file in downloads folder")
            return

def download_buy_downloads(config: Config, track_infos: list[TrackInfo], ignored_files=()):
    """ Downloads tracks that are available for purchase """
    track_infos = track_infos.copy()

    # Generates queries
    queries = []
    for track_info in track_infos:
        queries.append(f'{track_info.artists[0]} {track_info.title}')

    # Execute download backend
    if config.downloads.backend == 'deezer':
        skipped_tracks = deezer_download(config, queries)
    elif config.downloads.backend == 'qobuz':
        skipped_tracks = qobuz_download(config, queries)
    else:
        print(f"ERROR: Invalid download backend '{config.downloads.backend}'")
        return

    # Remove skipped tracks from track infos
    for track_index in sorted(skipped_tracks, reverse=True):
        track_info = track_infos[track_index]
        print(f"SKIPPED: {track_info.artists[0]} - {track_info.title}")
        del track_infos[track_index]

    filenames = list_downloaded_files(config, ignored_files)
    if len(filenames) == len(track_infos):
        # Create a list of tuples containing filename and creation time
        filenames = [(f, os.path.getctime(os.path.join(config.downloads.root_folder, f))) for f in filenames]

        # Sort the list of tuples based on creation time (same order as track_infos)
        filenames = sorted(filenames, key=lambda x: x[1])

        # Extract filenames back from the sorted list of tuples
        filenames = [filename for filename, _ in filenames]

        # Process the files
        for i, filename in enumerate(filenames):
            process_file(config, track_infos[i], filename)
    else:
        print("ERROR: File count mismatch in downloads folder")
        return

def download_all_tracks(config: Config, playlist_info: PlaylistInfo, web_driver, ignored_files=()):
    """ Downloads every tracks """
    if playlist_info.gate_downloads:
        print("INFO: Downloading gate downloads...")
        download_web_downloads(config, playlist_info.gate_downloads, web_driver, ignored_files)

    if playlist_info.direct_downloads:
        print("INFO: Downloading direct downloads...")
        download_web_downloads(config, playlist_info.direct_downloads, web_driver, ignored_files)

    if playlist_info.buy_downloads:
        print("INFO: Downloading buy downloads...")
        download_buy_downloads(config, playlist_info.buy_downloads, ignored_files)

def download_playlist(config: Config, playlist_info: PlaylistInfo):
    """ Downloads a playlist """
    # Create root download folder if necessary
    os.makedirs(config.downloads.root_folder, exist_ok=True)

    # Leave files that were already there alone, they aren't part of this run
    ignored_files = list_downloaded_files(config)
    if ignored_files:
        print(f"WARNING: Ignoring {len(ignored_files)} file(s) already in the downloads folder")

    # Create web driver only if needed
    if config.soundcloud.use_web_driver and (playlist_info.gate_downloads or playlist_info.direct_downloads):
        try:
            # Setup Chrome options
            chrome_options = ChromeOptions()
            chrome_options.add_argument('--log-level=3')
            chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
            chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
            chrome_options.add_experimental_option('prefs', {'download.default_directory' : config.downloads.root_folder})

            # Initialize the WebDriver
            web_driver = ChromeDriver(options=chrome_options)

            # Process track infos
            download_all_tracks(config, playlist_info, web_driver, ignored_files)

        except Exception as e:
            print(e)

        finally:
            # Close the browser
            web_driver.quit()
    else:
        try:
            # Process track infos
            download_all_tracks(config, playlist_info, None, ignored_files)
        except Exception as e:
            print(e)

def download_playlist_cli(config: Config, playlist_url: str):
    """ Downloads a playlist (console version) """
    # Extract track infos
    playlist_info = extract_playlist_info(config, playlist_url)

    # Download playlist
    download_playlist(config, playlist_info)
