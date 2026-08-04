import logging
import os

from selenium.webdriver import Chrome as ChromeDriver
from selenium.webdriver.chrome.options import Options as ChromeOptions

from backends import create_backend

from config import Config
from models import PlaylistInfo, TrackInfo
from sources import extract_playlist_info
from tagging import process_file
from utils import download_file, list_downloaded_files

logger = logging.getLogger(__name__)

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

def console_prompt(message):
    """ Waits for the user to acknowledge a message in the console """
    input(f"{message} Press Enter to continue...")

def download_web_downloads(config: Config, track_infos: list[TrackInfo], web_driver, ignored_files=(), prompt=console_prompt):
    """ Downloads tracks that require user action (direct download, download gate, etc.) """
    for track_info in track_infos:
        print(f'* {track_info.name}')

        if web_driver:
            # Open a page with the download gate
            web_driver.get(track_info.download_url)

            # Prompt the user to continue after downloading
            prompt(f"Download '{track_info.name}' in the browser.")
        else:
            # Prompt the user to continue after downloading
            prompt(f"Download '{track_info.name}' manually and move it to the downloads folder.")

        # Process the file
        filenames = list_downloaded_files(config, ignored_files)
        if len(filenames) == 1:
            process_file(config, track_info, filenames[0])
        elif len(filenames) == 0:
            logger.warning("Track hasn't been downloaded by the user")
        else:
            logger.error("Found more than one file in downloads folder")
            return

def download_buy_downloads(config: Config, track_infos: list[TrackInfo], ignored_files=()):
    """ Downloads tracks that are available for purchase """
    backend = create_backend(config)
    backend.connect()

    for track_info in track_infos:
        print(f'* {track_info.name}')

        # Each query is downloaded on its own so the files it produced are known
        query = f'{track_info.artists[0]} {track_info.title}'
        filenames = backend.download(query)

        if not filenames:
            logger.info(f"SKIPPED: {track_info.artists[0]} - {track_info.title}")
            continue

        # Process the files
        for filename in filenames:
            process_file(config, track_info, filename)

def download_all_tracks(config: Config, playlist_info: PlaylistInfo, web_driver, ignored_files=(), prompt=console_prompt):
    """ Downloads every tracks """
    if playlist_info.gate_downloads:
        logger.info("Downloading gate downloads...")
        download_web_downloads(config, playlist_info.gate_downloads, web_driver, ignored_files, prompt)

    if playlist_info.direct_downloads:
        logger.info("Downloading direct downloads...")
        download_web_downloads(config, playlist_info.direct_downloads, web_driver, ignored_files, prompt)

    if playlist_info.buy_downloads:
        logger.info("Downloading buy downloads...")
        download_buy_downloads(config, playlist_info.buy_downloads, ignored_files)

def download_playlist(config: Config, playlist_info: PlaylistInfo, prompt=console_prompt):
    """ Downloads a playlist
        'prompt' is how the user is asked to complete a manual download, the
        console prompt is invisible when running from the GUI
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

            # Process track infos
            download_all_tracks(config, playlist_info, web_driver, ignored_files, prompt)

        except Exception as e:
            print(e)

        finally:
            # Close the browser, it may have failed to start
            if web_driver:
                web_driver.quit()
    else:
        try:
            # Process track infos
            download_all_tracks(config, playlist_info, None, ignored_files, prompt)
        except Exception as e:
            print(e)

def download_playlist_cli(config: Config, playlist_url: str):
    """ Downloads a playlist (console version) """
    # Extract track infos
    playlist_info = extract_playlist_info(config, playlist_url)

    # Download playlist
    download_playlist(config, playlist_info)
