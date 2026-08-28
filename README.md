Python script to download playlists from SoundCloud or Spotify.

## Features

- Optional graphical interface
- SoundCloud playlist download (private and public)
- Spotify playlist download (public only)
- Automatic metadata generator and editor (GUI only)
- Deezer and Qobuz download backends
- Built-in config editor with a credential test button

## Installation

First, ensure [Python](https://www.python.org/downloads/) (3.10 to 3.13) and [pip](https://pip.pypa.io/en/stable/installation/) are installed. Then, open a terminal in this folder and enter:

```bash
pip install -r requirements.txt
```

3.10 to 3.13 is the tested range. Installing under 3.14 fails on dependencies that don't publish a wheel for it yet, so pick an older interpreter if `pip install` cannot build one. On macOS, `python3` is not necessarily the newest version installed, so check what `python3 --version` reports first.

[FFmpeg](https://ffmpeg.org/download.html) must also be on your `PATH` to convert WAV downloads to MP3. On macOS it is installed with `brew install ffmpeg`.

`config/config.toml` and `config/secrets.toml` are created from the `.example` files next to them on first run, and both are ignored by git so your settings and credentials are never committed. When a setting is added to or removed from a template, your file is updated to match on the next run while keeping the values you set.

Fill in `config/secrets.toml` with the credentials of the backend you intend to use. Credentials found in an older `config/config.toml` are moved there automatically.

Credentials can also be edited from the interface with the **Config** button, which explains what every setting does and has a **Test** button to check them.

### Deezer backend

Add your premium Deezer ARL to `deezer_arl`. Deezer is reached through a Spotify search, so a Spotify client ID / secret is required as well.

### Qobuz backend

Add your `user_id` and `token`, **and** the `app_id` / `app_secret` they were issued for. All four are required: a Qobuz auth token is only valid under its own app ID, so the app credentials cannot be discovered automatically and a mismatch is reported as `Invalid credentials`.

### Spotify

To download Spotify playlists, [register a new app](https://developer.spotify.com/documentation/web-api/concepts/apps) and add your client ID / secret in `secrets.toml`.

## Usage

To open up the user interface (recommended), double-click on `launch.bat` (Windows) or `launch.command` (macOS), or type the following in a terminal. The app resolves its files from its own folder, so it can be started from anywhere:

```bash
python download_tracks.py --gui
```

To run the script in command line (experimental):

```bash
python download_tracks.py --url https://...
```

Without `--url`, the `playlist_url` set in the config is used. Note: the command line version doesn't support metadata editing.

## Interface

`theme` in `config.toml` accepts `classic` (the default plain look), `system` to follow the desktop light/dark setting on Windows and macOS, or `light`/`dark` to force one. It is applied when the app starts.


Each track shows its outcome in the **Status** column, with the row tinted to match:

| Status | Meaning |
|---|---|
| Downloaded | tagged and moved to the dated folder |
| Skipped | the backend found nothing matching the track |
| Rejected | downloaded but the tags didn't match, kept in `_rejected/` |
| Failed | the download or the tagging raised an error |

Click a column header to sort the table, which groups outcomes together after a run. **Select by status** picks every track that ended a given way, so retrying just the failures is Select by status → Failed → Download Selected.

Attributes can be set on several tracks at once with the bar under the table: pick an attribute, type a value and click **Apply** to write it to every selected track. It defaults to the genre, prefilled from the config.

Downloads run in the background, so the window stays usable and can be stopped with **Cancel** (the track in progress finishes first). A counter shows the progress and a summary is shown at the end. The log panel below the table shows the messages that otherwise only reach the console and can be hidden with **Hide Log**, and **Open Folder** reveals the exported files. Double-clicking the status of a rejected track opens the folder it was kept in.

## Errors

Missing or invalid settings are reported before anything is downloaded: the GUI shows a dialog naming what is missing, the command line logs it and exits with a non-zero code. A track that fails is logged and skipped, the rest of the playlist still downloads.

## Genre

The genre of a track is taken from the first of these that provides one:

1. `genre_override` in the config, when set it is forced on every track
2. the genre from the playlist (SoundCloud), editable per track in the Genre column
3. the genre the download backend tagged the file with (Qobuz, Deezer)
4. `default_genre` in the config

Qobuz reports genres in the language of the account, so `genre_override` is the way to keep a library consistent.

## Matching

Tracks from a Spotify playlist carry their ISRC, the identifier of the exact recording. The backends match on it rather than searching by name, which avoids downloading a different version of a track: searching Qobuz for "Taylor Swift Love Story" returns *Love Story (Taylor's Version)*, while the ISRC returns the 2008 recording. A Spotify playlist is handed to Deezer directly, without a search at all. SoundCloud tracks have no ISRC, so they still fall back to a name search.

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
