Python script to download playlists from SoundCloud or Spotify.

## Features

- Optional graphical interface
- SoundCloud playlist download (private and public)
- Spotify playlist download (public only)
- Automatic metadata generator and editor (GUI only)

## Installation

First, ensure [Python](https://www.python.org/downloads/) (version 3.10 or greater) and [pip](https://pip.pypa.io/en/stable/installing/) are installed. Then, open a terminal in this folder and enter:

```bash
pip install -r requirements.txt
```

Then, edit `config/config.toml` and add your Deezer ARL.

Note: to download Spotify playlists, you must also [register a new app](https://developer.spotify.com/documentation/web-api/concepts/apps) and add your client ID / secret ID in the config.

## Usage

To open up the user interface (recommended), either double-click on launch.bat (Windows only) or type the following in a terminal:

```bash
python download_tracks.py --gui
```

To run the script in command line (experimental):

```bash
python download_tracks.py
```

Note: the command line version doesn't support metadata editing.
