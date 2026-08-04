import os
import re
import shutil

from mutagen.easyid3 import EasyID3
from mutagen.flac import FLAC as MutagenFLAC
from mutagen.mp3 import MP3 as MutagenMP3

from pydub import AudioSegment

from config import Config
from models import TrackInfo
from utils import (
    REJECTED_FOLDER_NAME,
    download_file,
    is_file_downloaded,
    quarantine_file
)

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
    # DATE is the standard Vorbis comment, YEAR is kept for players that only read it
    audiofile['date'] = track_info.year
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
