import argparse
import logging

from config import Config
from pipeline import download_playlist_cli
from gui import download_playlist_gui

def main():
    parser = argparse.ArgumentParser("Playlist Downloader")
    parser.add_argument('--gui', '-g', action='store_true')
    args = parser.parse_args()

    # Backend libraries log through the same handler
    logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

    # Load config
    try:
        config = Config.load()
    except (FileNotFoundError, ValueError) as e:
        logging.error(e)
        return

    if args.gui:
        download_playlist_gui(config, config.downloads.playlist_url)
    else:
        download_playlist_cli(config, config.downloads.playlist_url)

if __name__ == "__main__":
    main()
