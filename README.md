Python script to download playlists from SoundCloud or Spotify.

## Features

- Optional graphical interface
- SoundCloud playlist download (private and public)
- Spotify playlist download (public only)
- Automatic metadata generator and editor (GUI only)
- Deezer and Qobuz download backends
- Built-in config editor with a credential test button

## Installation

First, ensure [Python](https://www.python.org/downloads/) (version 3.10 or greater) and [pip](https://pip.pypa.io/en/stable/installation/) are installed. Then, open a terminal in this folder and enter:

```bash
pip install -r requirements.txt
```

[FFmpeg](https://ffmpeg.org/download.html) must also be on your `PATH` to convert WAV downloads to MP3.

Then, copy `config/secrets.toml.example` to `config/secrets.toml` and fill in the credentials of the backend you intend to use. `secrets.toml` is ignored by git so your credentials are never committed. Credentials found in an older `config/config.toml` are moved there automatically on first run.

Credentials can also be edited from the interface with the **Config** button, which has a **Test** button to check them.

### Deezer backend

Add your premium Deezer ARL to `deezer_arl`. Deezer is reached through a Spotify search, so a Spotify client ID / secret is required as well.

### Qobuz backend

Add your `user_id` and `token`, **and** the `app_id` / `app_secret` they were issued for. All four are required: a Qobuz auth token is only valid under its own app ID, so the app credentials cannot be discovered automatically and a mismatch is reported as `Invalid credentials`.

### Spotify

To download Spotify playlists, [register a new app](https://developer.spotify.com/documentation/web-api/concepts/apps) and add your client ID / secret in `secrets.toml`.

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

## Errors

Missing or invalid settings are reported before anything is downloaded: the GUI shows a dialog naming what is missing, the command line logs it and exits with a non-zero code. A track that fails is logged and skipped, the rest of the playlist still downloads.

## Downloads

Tracks are downloaded to `downloads/`, then tagged and moved to `downloads/YYYY-MM-DD/{flac,mp3,wav}`. A file whose tags don't match the expected track is moved to `downloads/_rejected/` instead of being deleted, so it can be inspected.

## Layout

| Path | Role |
|---|---|
| `download_tracks.py` | Entry point (CLI and GUI) |
| `pipeline.py` | Download orchestration |
| `sources/` | Playlist extraction (SoundCloud, Spotify) |
| `backends/` | Download backends (Deezer, Qobuz) |
| `tagging.py` | Validation and tagging of downloaded files |
| `models.py`, `utils.py` | Track models and shared helpers |
| `gui.py`, `config_editor.py` | Tkinter interface |
| `config.py` | Config loading and saving |

To add a backend, subclass `DownloadBackend` in `backends/` and add it to `BACKENDS` in `backends/__init__.py`. It then appears in the config editor automatically.
