import asyncio
import click
import logging
import os
import re
import requests
import shutil

from dataclasses import dataclass

from eyed3 import load as eyed3_load_mp3
from eyed3.id3 import ID3_V1_1

from pydub import AudioSegment

from rich.console import Console as RichConsole
from rich.logging import RichHandler
from rich.traceback import install as install_rich_traceback

from sclib import (
    SoundcloudAPI,
    Playlist as SoundcloudPlaylist
)

from selenium.webdriver import Chrome as ChromeDriver
from selenium.webdriver.chrome.options import Options as ChromeOptions

from spotipy import Spotify
from spotipy.oauth2 import SpotifyClientCredentials

from streamrip.config import (
    Config as StreamripConfig,
    set_user_defaults as streamrip_set_user_defaults,
    DEFAULT_CONFIG_PATH as STREAMRIP_DEFAULT_CONFIG_PATH
)
from streamrip.rip.main import Main as StreamripMain

from urllib.parse import urlparse

console = RichConsole()

#--------------------------------------------------------------------
# CONFIG
#--------------------------------------------------------------------

@dataclass(slots=True)
class DownloadsConfig:
    root_folder: str
    mp3_folder: str
    wav_folder: str

@dataclass(slots=True)
class MetadataConfig:
    artist_delimiter: str
    tag_single_album: bool

@dataclass(slots=True)
class SoundcloudConfig:
    supported_download_gates: list[str]
    supported_remix_tokens: list[str]
    download_playlist_url: str

@dataclass(slots=True)
class SpotifyConfig:
    client_id: str
    client_secret: str
    redirect_url: str

@dataclass(slots=True)
class StreamripConfig:
    default_source: str
    default_media_type: str
    default_quality: int
    deezer_arl: str

@dataclass(slots=True)
class Config:
    downloads: DownloadsConfig
    metadata: MetadataConfig
    soundcloud: SoundcloudConfig
    spotify: SpotifyConfig
    streamrip: StreamripConfig

    @classmethod
    def from_file(cls, toml_file):
        downloads = DownloadsConfig(**toml_file['downloads'])
        metadata = MetadataConfig(**toml_file['metadata'])
        soundcloud = SoundcloudConfig(**toml_file['soundcloud'])
        spotify = SpotifyConfig(**toml_file['spotify'])
        streamrip = StreamripConfig(**toml_file['streamrip'])

        # Enforce absolute paths
        downloads.root_folder = os.path.abspath(downloads.root_folder)
        downloads.mp3_folder = os.path.abspath(downloads.mp3_folder)
        downloads.wav_folder = os.path.abspath(downloads.wav_folder)

        return cls(
            downloads=downloads,
            metadata=metadata,
            soundcloud=soundcloud,
            spotify=spotify,
            streamrip=streamrip
        )

#--------------------------------------------------------------------
# TYPES
#--------------------------------------------------------------------

class TrackInfo:
    """ Single track info """
    name: str
    title: str
    artists: list[str]
    album: str
    year: str
    number: int
    genre: str
    artwork_url: str
    download_url: str
    category: str

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

def create_or_clear_directory(directory):
    """ Deletes a directory if it already exists and create a new empty one """
    # If the directory exists, delete it
    if os.path.exists(directory):
        shutil.rmtree(directory)

    # Create the directory
    try:
        os.makedirs(directory)
    except Exception as e:
        print(e)

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

#--------------------------------------------------------------------
# STRING HELPERS
#--------------------------------------------------------------------

def extract_website_name(url):
    """ Extracts the name of the website from a URL """
    parsed_url = urlparse(url)
    domain_parts = parsed_url.netloc.split('.')
    if len(domain_parts) >= 2:
        return domain_parts[-2]
    else:
        return None

def is_download_gate(config: Config, url):
    """ Checks if the URL points to a download gate """
    return extract_website_name(url) in config.soundcloud.supported_download_gates

def format_track_name(config: Config, name):
    """ Formats the name of a track by performing the following:
        1. Replaces any square brackets with parentheses
        2. Removes trailing parentheses with useless information (e.g. "Free Download")
        3. Removes featuring artists
    """
    matches = []

    # Replace square brackets with parentheses
    name = name.translate(str.maketrans('[]','()'))
    result = name

    # Replace "- ABC Remix" with (ABC Remix)
    result = result.rsplit('-', 1)
    result = result[0] + f"({result[1].strip()})" if len(result) == 2 else result[0]

    # Remove trailing parentheses with useless information (e.g. "Free Download")
    pattern = re.compile(r'\s\((?!.*?\b(?:{}))[^()]*\)'.format('|'.join(map(re.escape, config.soundcloud.supported_remix_tokens))), re.IGNORECASE)
    matches.extend(pattern.findall(result))
    result = re.sub(pattern, '', result).strip()

    # Remove featuring artists
    pattern = re.compile(r'\s(?:ft\.|feat\.)\s.*?(?=\s\(|$)', re.IGNORECASE)
    matches.extend(pattern.findall(result))
    result = re.sub(pattern, '', result).strip()

    # Print changes
    if matches:
        print(f"Removed {matches} from '{name}'")

    return result

def extract_spotify_playlist_id(playlist_url):
    playlist_id = playlist_url.split('playlist/')[-1].split('?')[0]
    # Base-62 identifier of 22 characters
    return playlist_id if len(playlist_id) == 22 else None

#--------------------------------------------------------------------
# STREAMRIP
#--------------------------------------------------------------------

def streamrip_generate_config(config_path, no_db):
    """ Loads the user streamrip config file (%AppData%/streamrip/config.toml) """
    # Setup global logger used by streamrip
    global logger
    logging.basicConfig(
        level="INFO",
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler()],
    )
    logger = logging.getLogger("streamrip")

    # Install a rich traceback handler
    install_rich_traceback(console=console, suppress=[click, asyncio], max_frames=1)
    logger.setLevel(logging.INFO)

    # Make sure config file exists
    if not os.path.isfile(config_path):
        console.print(
            f"No file found at [bold cyan]{config_path}[/bold cyan], creating default config.",
        )
        streamrip_set_user_defaults(config_path)

    # Load config file
    try:
        config = StreamripConfig(config_path)
    except Exception as e:
        console.print(
            f"Error loading config from [bold cyan]{config_path}[/bold cyan]: {e}\n"
            "Try running [bold]rip config reset[/bold]",
        )
        return None

    # Bypass cached downloads if set
    if no_db:
        config.session.database.downloads_enabled = False

    return config

async def streamrip_search(config: Config, queries):
    """ Searches for tracks interactively using a query """    
    # Generate streamrip config
    streamrip_config = streamrip_generate_config(STREAMRIP_DEFAULT_CONFIG_PATH, True)
    streamrip_config.session.downloads.folder = config.downloads.mp3_folder
    streamrip_config.session.deezer.quality = config.streamrip.default_quality
    streamrip_config.session.deezer.arl = config.streamrip.deezer_arl

    async with StreamripMain(streamrip_config) as main:
        for query in queries:
            await main.search_interactive(config.streamrip.default_source, config.streamrip.default_media_type, query)
        await main.resolve()
        await main.rip()

#--------------------------------------------------------------------
# MAIN
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
        track_info.title = format_track_name(config, track.title)
        track_info.artists = [track.artist]
        track_info.name = f"{' & '.join(track_info.artists)} - {track_info.title}"
        track_info.album = track_info.title if config.metadata.tag_single_album else ''
        track_info.year = track.display_date.split('-')[0]
        track_info.number = 1
        track_info.genre = 'Dubstep'
        track_info.artwork_url = track.artwork_url.replace('large', 't500x500')

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

    playlist = spotify.playlist_tracks(playlist_id)['items']
    playlist_info = PlaylistInfo()
    for track in playlist:
        # Checks if the track is part of an album (not in a compilation nor a single)
        is_in_album = (track['track']['album']['album_type'] == 'album' or
            (track['track']['album']['album_type'] == 'single' and
             track['track']['track_number'] != 1))

        # Fill track info
        track_info = TrackInfo()
        track_info.title = format_track_name(config, track['track']['name'])
        track_info.artists = [t['name'] for t in track['track']['artists']]
        track_info.name = f"{' & '.join(track_info.artists)} - {track_info.title}"
        track_info.album = (track['track']['album']['name'] if is_in_album else
            track_info.title if config.metadata.tag_single_album else '')
        track_info.year = track['track']['album']['release_date'].split('-')[0]
        track_info.number = track['track']['track_number']
        track_info.genre = 'Dubstep'
        track_info.artwork_url = ''
        track_info.download_url = ''
        track_info.category = 'Buy'

        # Add to buy downloads
        playlist_info.buy_downloads.append(track_info)

    return playlist_info

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

def process_mp3(config: Config, track_info: TrackInfo, filename):
    source_path = os.path.join(config.downloads.root_folder, filename)
    destination_path = os.path.join(config.downloads.mp3_folder, filename)
    shutil.move(source_path, destination_path)

def process_wav(config: Config, track_info: TrackInfo, filename):
    """ Converts a WAV to a properly tagged MP3 """
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
        'album': track_info.title,
        'year': track_info.year,
        'genre': track_info.genre,
        'track': 1
    }

    # Download the artwork from the URL and save it to a temporary file
    artwork_path = os.path.join(config.downloads.root_folder, 'Artwork.jpg')
    download_file(track_info.artwork_url, artwork_path)

    # Export the audio as an MP3 file with the specified bitrate and metadata
    audio.export(dest_path_mp3, format="mp3", bitrate="320k", id3v2_version="3", tags=metadata, cover=artwork_path)

    # Set ID3v1 tags
    audiofile = eyed3_load_mp3(dest_path_mp3)
    audiofile.tag.release_date = track_info.year
    audiofile.tag.save(version=ID3_V1_1)

    # Delete temporary artwork file
    if os.path.exists(artwork_path):
        os.remove(artwork_path)

    # Move WAV from downloads folder
    shutil.move(source_path, dest_path_wav)

def process_file(config: Config, track_info: TrackInfo, filename):
    """ Processes a downloaded audio file (MP3 or WAV) """
    # Make sure the file exists in the downloads folder
    if is_file_downloaded(config, filename):
        # Dispatch the processing to the corrresponding procedure
        if filename.endswith('.mp3'):
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

def download_web_downloads(config: Config, track_infos: list[TrackInfo], web_driver):
    """ Downloads tracks that require user action (direct download, download gate, etc.) """
    for track_info in track_infos:
        print(f'* {track_info.name}')

        # Open a page with the download gate
        web_driver.get(track_info.download_url)

        # Prompt the user to continue after downloading
        input("Download track then press Enter to continue...")

        # Process the file
        files = [f for f in os.listdir(config.downloads.root_folder) if is_file_downloaded(config, f)]
        if len(files) == 1:
            process_file(config, track_info, files[0])
        elif len(files) == 0:
            print("SKIPPED: Track hasn't been downloaded by the user")
        else:
            print("ERROR: Found more than one file in downloads folder")
            return

def download_buy_downloads(config: Config, track_infos: list[TrackInfo]):
    """ Downloads tracks that are available for purchase """
    # Generates queries
    queries = []
    for track_info in track_infos:
        queries.append(f'{track_info.artists[0]} {track_info.title}')

    # Execute streamrip
    asyncio.run(streamrip_search(config, queries))

def download_all_tracks(config: Config, playlist_info: PlaylistInfo, web_driver):
    """ Downloads every tracks """
    if playlist_info.gate_downloads:
        print("INFO: Downloading gate downloads...")
        download_web_downloads(config, playlist_info.gate_downloads, web_driver)

    if playlist_info.direct_downloads:
        print("INFO: Downloading direct downloads...")
        download_web_downloads(config, playlist_info.direct_downloads, web_driver)

    if playlist_info.buy_downloads:
        print("INFO: Downloading buy downloads...")
        download_buy_downloads(config, playlist_info.buy_downloads)

def download_playlist(config: Config, playlist_info: PlaylistInfo):
    """ Downloads a playlist """
    # Create or clear folders
    create_or_clear_directory(config.downloads.root_folder)
    os.makedirs(config.downloads.mp3_folder, exist_ok=True)
    os.makedirs(config.downloads.wav_folder, exist_ok=True)

    # Create web driver only if needed
    if playlist_info.gate_downloads or playlist_info.direct_downloads:
        try:
            # Setup Chrome options
            chrome_options = ChromeOptions()
            chrome_options.add_argument('--log-level=3')
            chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
            chrome_options.add_experimental_option('prefs', {'download.default_directory' : config.downloads.root_folder})

            # Initialize the WebDriver
            web_driver = ChromeDriver(options=chrome_options)

            # Process track infos
            download_all_tracks(config, playlist_info, web_driver)

        except Exception as e:
            print(e)

        finally:
            # Close the browser
            web_driver.quit()
    else:
        # Process track infos
        download_all_tracks(config, playlist_info, None)

def download_playlist_cli(config: Config, playlist_url: str):
    """ Downloads a playlist (console version) """
    # Extract track infos
    playlist_info = extract_playlist_info(config, playlist_url)

    # Download playlist
    download_playlist(config, playlist_info)
