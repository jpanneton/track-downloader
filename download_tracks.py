import argparse
import logging
import sys

from config import Config
from errors import TrackDownloaderError
from pipeline import download_playlist_cli
from gui import download_playlist_gui

def main():
    parser = argparse.ArgumentParser("Playlist Downloader")
    parser.add_argument('--gui', '-g', action='store_true')
    parser.add_argument('--url', '-u', help="playlist to download, defaults to the configured one")
    args = parser.parse_args()

    # Backend libraries log through the same handler
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    # Load config
    try:
        config = Config.load()
    except (FileNotFoundError, ValueError) as e:
        logging.error(e)
        return 1

    playlist_url = args.url or config.downloads.playlist_url

    try:
        if args.gui:
            download_playlist_gui(config, playlist_url)
        else:
            download_playlist_cli(config, playlist_url)
    except TrackDownloaderError as e:
        # Expected failure, the message is meant for the user
        logging.error(e)
        return 1
    except KeyboardInterrupt:
        logging.warning("Interrupted")
        return 1
    except Exception:
        # Unexpected failure, the traceback is the useful part
        logging.exception("Unexpected error")
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
