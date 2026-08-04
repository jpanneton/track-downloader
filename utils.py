import logging
import os
import re
import requests
import shutil

from urllib.parse import urlparse

from config import Config

logger = logging.getLogger(__name__)

SUPPORTED_AUDIO_EXTENSIONS = ('.flac', '.mp3', '.wav')

# Folder where files that failed validation are kept for inspection
REJECTED_FOLDER_NAME = '_rejected'

#--------------------------------------------------------------------
# FILE HELPERS
#--------------------------------------------------------------------

def resolve_collision(folder_path, filename):
    """ Returns a path in a folder that doesn't overwrite an existing file """
    name, extension = os.path.splitext(filename)

    destination_path = os.path.join(folder_path, filename)
    duplicate_index = 1
    while os.path.exists(destination_path):
        destination_path = os.path.join(folder_path, f'{name} ({duplicate_index}){extension}')
        duplicate_index += 1

    return destination_path

def list_downloaded_files(config: Config, ignored_files=()):
    """ Lists the files sitting in the downloads folder excluding sub-folders """
    root_folder = config.downloads.root_folder
    if not os.path.exists(root_folder):
        return []

    return [
        filename for filename in os.listdir(root_folder)
        if filename not in ignored_files
        and os.path.isfile(os.path.join(root_folder, filename))
    ]

def quarantine_file(config: Config, source_path):
    """ Moves a file that failed validation out of the downloads folder
        Keeping it makes a wrong rejection recoverable and inspectable
    """
    rejected_folder = os.path.join(config.downloads.root_folder, REJECTED_FOLDER_NAME)
    os.makedirs(rejected_folder, exist_ok=True)

    destination_path = resolve_collision(rejected_folder, os.path.basename(source_path))
    shutil.move(source_path, destination_path)
    return destination_path

def download_file(url, dest_path):
    """ Downloads a file from a URL """
    response = requests.get(url)
    if response.status_code == 200:
        with open(dest_path, 'wb') as handler:
            handler.write(response.content)
    else:
        logger.info(f"Failed to download {url}")

def is_file_downloaded(config: Config, filename):
    """ Checks if a file has been properly downloaded in the downloads folder """
    return os.path.isfile(os.path.join(config.downloads.root_folder, filename))

def list_subfolders(folder_path):
    """ Lists the sub-folders sitting directly in a folder """
    if not os.path.exists(folder_path):
        return []

    return [
        name for name in os.listdir(folder_path)
        if os.path.isdir(os.path.join(folder_path, name))
    ]

def flatten_subfolders(folder_path, subfolder_names):
    """ Moves every audio file from the given sub-folders up to the root folder
        Backends such as Qobuz group tracks in a release sub-folder along with
        extra files (cover art, booklet, playlist) that must not be processed

        Only the given sub-folders are touched, the exported flac/mp3/wav
        folders live in the same root and must be left alone
    """
    for subfolder_name in subfolder_names:
        subfolder_path = os.path.join(folder_path, subfolder_name)
        if not os.path.isdir(subfolder_path):
            continue

        for root, _, filenames in os.walk(subfolder_path, topdown=False):
            for filename in filenames:
                source_path = os.path.join(root, filename)

                # Discard anything that isn't an audio file
                if not filename.lower().endswith(SUPPORTED_AUDIO_EXTENSIONS):
                    os.remove(source_path)
                    continue

                shutil.move(source_path, resolve_collision(folder_path, filename))

            # Remove the sub-folder now that it has been emptied
            os.rmdir(root)

#--------------------------------------------------------------------
# STRING HELPERS
#--------------------------------------------------------------------

def extract_website_name(url: str):
    """ Extracts the name of the website from a URL """
    parsed_url = urlparse(url)
    domain_parts = parsed_url.netloc.split('.')
    if len(domain_parts) >= 2:
        return domain_parts[-2]
    else:
        return None

def is_download_gate(config: Config, url: str):
    """ Checks if the URL points to a download gate """
    return extract_website_name(url) in config.soundcloud.supported_download_gates

def format_track_name(config: Config, name: str, remove_noise: bool):
    """ Formats the name of a track by performing the following:
        1. Replaces any square brackets with parentheses
        2. Removes trailing parentheses with useless information (e.g. "Free Download") if remove_noise = True
        3. Removes featuring artists if set in config
    """
    matches = []

    # Replace square brackets with parentheses
    name = name.translate(str.maketrans('[]','()'))
    result = name

    # Replace "- ABC Remix" with (ABC Remix) -> Spotify specific
    result = result.rsplit(' - ', 1)
    result = result[0] + f" ({result[1].strip()})" if len(result) == 2 else result[0]

    # Remove trailing parentheses with useless information (e.g. "Free Download")
    if remove_noise:
        pattern = re.compile(r'\s\((?!.*?\b(?:{}))[^()]*\)'.format('|'.join(map(re.escape, config.metadata.supported_remix_tokens))), re.IGNORECASE)
        matches.extend(pattern.findall(result))
        result = re.sub(pattern, '', result).strip()

    # Remove featuring artists
    if config.metadata.remove_feat_from_title:
        pattern = re.compile(r'\s*\((?:feat|ft)\..*?\)', re.IGNORECASE)
        matches.extend(pattern.findall(result))
        result = re.sub(pattern, '', result).strip()

    # Print changes
    if matches:
        logger.info(f"Removed {matches} from '{name}'")

    return result

def extract_spotify_playlist_id(playlist_url):
    """ Extracts the ID from a Spotify playlist URL """
    playlist_id = playlist_url.split('playlist/')[-1].split('?')[0]
    # Base-62 identifier of 22 characters
    return playlist_id if len(playlist_id) == 22 else None
