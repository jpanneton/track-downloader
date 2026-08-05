import logging
import os

from selenium.webdriver import Chrome as ChromeDriver
from selenium.webdriver.chrome.options import Options as ChromeOptions

from backends import create_backend

from config import Config
from errors import BackendError, format_error
from models import PlaylistInfo, TrackInfo, TrackStatus
from sources import extract_playlist_info
from tagging import process_file
from utils import download_file, list_downloaded_files

logger = logging.getLogger(__name__)

def download_direct_downloads(config: Config, track_infos: list[TrackInfo]):
    """ Downloads tracks that have a direct download link
        Unused for now because direct downloads require a client ID
    """
    for track_info in track_infos:
        logger.info(f'* {track_info.name}')

        # Download file to downloads folder
        filename = f'{track_info.name}.wav'
        dest_path = os.path.join(config.downloads.root_folder, filename)
        download_file(track_info.download_url, dest_path)

        # Process the file
        process_file(config, track_info, filename)

class DownloadListener:
    """ Follows a download run and decides whether it should keep going
        The console implementation is the default, the GUI overrides it
    """

    def prompt(self, message: str):
        """ Waits for the user to complete a manual download """
        input(f"{message} Press Enter to continue...")

    def track_status(self, track_info: TrackInfo, status: str):
        """ Reports the outcome of a single track """

    def is_cancelled(self):
        """ Whether the user asked to stop before the next track """
        return False

def download_web_downloads(config: Config, track_infos: list[TrackInfo], web_driver, ignored_files=(), listener=None):
    """ Downloads tracks that require user action (direct download, download gate, etc.) """
    listener = listener or DownloadListener()

    for track_info in track_infos:
        if listener.is_cancelled():
            break

        logger.info(f'* {track_info.name}')
        listener.track_status(track_info, TrackStatus.DOWNLOADING)

        try:
            if web_driver:
                # Open a page with the download gate
                web_driver.get(track_info.download_url)

                # Prompt the user to continue after downloading
                listener.prompt(f"Download '{track_info.name}' in the browser.")
            else:
                # Prompt the user to continue after downloading
                listener.prompt(f"Download '{track_info.name}' manually and move it to the downloads folder.")

            # Process the file
            filenames = list_downloaded_files(config, ignored_files)
            if len(filenames) == 1:
                status = process_file(config, track_info, filenames[0])
            elif len(filenames) == 0:
                logger.warning("Track hasn't been downloaded by the user")
                status = TrackStatus.SKIPPED
            else:
                logger.error(f"Found {len(filenames)} files in the downloads folder, expected one")
                status = TrackStatus.FAILED
        except Exception as e:
            # One failing track shouldn't abandon the rest of the playlist
            logger.error(f"FAILED: {track_info.name}: {format_error(e)}")
            status = TrackStatus.FAILED

        listener.track_status(track_info, status)

def download_buy_downloads(config: Config, track_infos: list[TrackInfo], ignored_files=(), listener=None):
    """ Downloads tracks that are available for purchase """
    listener = listener or DownloadListener()

    backend = create_backend(config)
    backend.connect()

    for track_info in track_infos:
        if listener.is_cancelled():
            break

        logger.info(f'* {track_info.name}')
        listener.track_status(track_info, TrackStatus.DOWNLOADING)

        try:
            # Each query is downloaded on its own so the files it produced are known
            query = f'{track_info.artists[0]} {track_info.title}'
            filenames = backend.download(query)

            if not filenames:
                logger.info(f"SKIPPED: {track_info.name}")
                listener.track_status(track_info, TrackStatus.SKIPPED)
                continue

            # Process the files, the status of the last one represents the track
            status = TrackStatus.FAILED
            for filename in filenames:
                status = process_file(config, track_info, filename)
        except Exception as e:
            # One failing track shouldn't abandon the rest of the playlist
            logger.error(f"FAILED: {track_info.name}: {format_error(e)}")
            status = TrackStatus.FAILED

        listener.track_status(track_info, status)

def download_all_tracks(config: Config, playlist_info: PlaylistInfo, web_driver, ignored_files=(), listener=None):
    """ Downloads every tracks """
    if playlist_info.gate_downloads:
        logger.info("Downloading gate downloads...")
        download_web_downloads(config, playlist_info.gate_downloads, web_driver, ignored_files, listener)

    if playlist_info.direct_downloads:
        logger.info("Downloading direct downloads...")
        download_web_downloads(config, playlist_info.direct_downloads, web_driver, ignored_files, listener)

    if playlist_info.buy_downloads:
        logger.info("Downloading buy downloads...")
        download_buy_downloads(config, playlist_info.buy_downloads, ignored_files, listener)

def download_playlist(config: Config, playlist_info: PlaylistInfo, listener=None):
    """ Downloads a playlist
        'listener' follows the run and answers manual download prompts, the
        console implementation is invisible when running from the GUI
    """
    # Create root download folder if necessary
    os.makedirs(config.downloads.root_folder, exist_ok=True)

    # Leave files that were already there alone, they aren't part of this run
    ignored_files = list_downloaded_files(config)
    if ignored_files:
        logger.warning(f"Ignoring {len(ignored_files)} file(s) already in the downloads folder")

    # Create web driver only if needed
    if config.soundcloud.use_web_driver and (playlist_info.gate_downloads or playlist_info.direct_downloads):
        web_driver = None
        try:
            # Setup Chrome options
            chrome_options = ChromeOptions()
            chrome_options.add_argument('--log-level=3')
            chrome_options.add_experimental_option('excludeSwitches', ['enable-automation'])
            chrome_options.add_experimental_option('excludeSwitches', ['enable-logging'])
            chrome_options.add_experimental_option('prefs', {'download.default_directory' : config.downloads.root_folder})

            # Initialize the WebDriver
            web_driver = ChromeDriver(options=chrome_options)
        except Exception as e:
            raise BackendError(f"Could not start the browser: {format_error(e)}")

        try:
            # Process track infos
            download_all_tracks(config, playlist_info, web_driver, ignored_files, listener)
        finally:
            # Close the browser, it may have failed to start
            if web_driver:
                web_driver.quit()
    else:
        # Process track infos
        download_all_tracks(config, playlist_info, None, ignored_files, listener)

def download_playlist_cli(config: Config, playlist_url: str):
    """ Downloads a playlist (console version) """
    # Extract track infos
    playlist_info = extract_playlist_info(config, playlist_url)

    # Download playlist
    download_playlist(config, playlist_info)
