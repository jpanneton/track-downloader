import argparse

from api import Config, download_playlist
from gui import download_playlist_gui

from tomlkit.api import parse as parse_toml

def main():
    parser = argparse.ArgumentParser("Playlist Downloader")
    parser.add_argument('--gui', '-g', action='store_true')
    args = parser.parse_args()

    # Load config
    try:
        with open('config.toml') as toml_file:
            toml = parse_toml(toml_file.read())
            config = Config.from_file(toml)

            if args.gui:
                download_playlist_gui(config, config.soundcloud.download_playlist_url)
            else:
                download_playlist(config, config.soundcloud.download_playlist_url)
                
    except FileNotFoundError:
        print("No config file found")

if __name__ == "__main__":
    main()
