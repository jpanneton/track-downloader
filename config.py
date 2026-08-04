import logging
import os
import re

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from pathlib import Path
from tomlkit.api import dumps as dumps_toml, parse as parse_toml

logger = logging.getLogger(__name__)

@dataclass(slots=True)
class DownloadsConfig:
    root_folder: str
    flac_folder: str
    mp3_folder: str
    wav_folder: str
    backend: str
    lossless: bool
    playlist_url: str

@dataclass(slots=True)
class MetadataConfig:
    supported_remix_tokens: list[str]
    artist_delimiter: str
    remove_feat_from_title: bool
    tag_single_album: bool
    default_genre: str

@dataclass(slots=True)
class SoundcloudConfig:
    supported_download_gates: list[str]
    use_web_driver: bool

@dataclass(slots=True)
class SpotifyConfig:
    client_id: str
    client_secret: str
    redirect_url: str

@dataclass(slots=True)
class DeezerConfig:
    deezer_arl: str

@dataclass(slots=True)
class QobuzConfig:
    user_id: str
    token: str
    # A user auth token is only valid under the app it was issued for, so the
    # app credentials must match the ones used to obtain the token
    app_id: str = ''
    app_secret: str = ''

@dataclass(slots=True)
class Config:
    downloads: DownloadsConfig
    metadata: MetadataConfig
    soundcloud: SoundcloudConfig
    spotify: SpotifyConfig
    deezer: DeezerConfig
    qobuz: QobuzConfig

    @classmethod
    def load(cls):
        # Load TOML doc
        toml_path = 'config/config.toml'
        try:
            text = Path(toml_path).read_text(encoding='utf-8')
            doc = parse_toml(text)

            downloads = DownloadsConfig(**doc['downloads'])
            metadata = MetadataConfig(**doc['metadata'])
            soundcloud = SoundcloudConfig(**doc['soundcloud'])
            spotify = SpotifyConfig(**doc['spotify'])
            deezer = DeezerConfig(**doc['deezer'])
            qobuz = QobuzConfig(**doc['qobuz'])

            # Get today's date
            current_date = datetime.now().strftime('%Y-%m-%d')

            # Enforce absolute paths
            downloads.root_folder = os.path.abspath(downloads.root_folder)
            downloads.flac_folder = os.path.join(downloads.root_folder, current_date, downloads.flac_folder)
            downloads.mp3_folder = os.path.join(downloads.root_folder, current_date, downloads.mp3_folder)
            downloads.wav_folder = os.path.join(downloads.root_folder, current_date, downloads.wav_folder)

            return cls(
                downloads=downloads,
                metadata=metadata,
                soundcloud=soundcloud,
                spotify=spotify,
                deezer=deezer,
                qobuz=qobuz
            )
        except FileNotFoundError:
            raise FileNotFoundError(f"Config file not found: {toml_path}")
        except Exception as e:
            raise ValueError(f"Invalid config file {toml_path}: {e}")

    def save(self):
        def dataclass_to_dict(instance):
            if is_dataclass(instance):
                return {
                    key: dataclass_to_dict(value)
                    for key, value in asdict(instance).items()
                }
            elif isinstance(instance, list):
                return [dataclass_to_dict(item) for item in instance]
            return instance

        def update_section(section, updates):
            for key, value in updates.items():
                if isinstance(value, dict):
                    update_section(section[key], value)
                else:
                    section[key] = value

        def extract_leaf_folder(full_path: str, root: str) -> str:
            try:
                relative = os.path.relpath(full_path, root)
                parts = relative.split(os.sep)
                # Strip the dated folder inserted when loading the config
                if len(parts) >= 2 and re.fullmatch(r'\d{4}-\d{2}-\d{2}', parts[0]):
                    return parts[1]
            except Exception:
                pass
            return os.path.basename(full_path)

        try:
            # Load original TOML doc to preserve comments
            toml_path = 'config/config.toml'
            text = Path(toml_path).read_text(encoding='utf-8')
            doc = parse_toml(text)

            # Convert config to dict
            config_dict = dataclass_to_dict(self)

            # Reverse absolute date folder paths
            root_folder = self.downloads.root_folder
            config_dict["downloads"]["root_folder"] = os.path.basename(root_folder)
            config_dict["downloads"]["flac_folder"] = extract_leaf_folder(self.downloads.flac_folder, root_folder)
            config_dict["downloads"]["mp3_folder"] = extract_leaf_folder(self.downloads.mp3_folder, root_folder)
            config_dict["downloads"]["wav_folder"] = extract_leaf_folder(self.downloads.wav_folder, root_folder)

            # Update TOML doc manually from dict
            update_section(doc, config_dict)

            # Save config
            Path(toml_path).write_text(dumps_toml(doc), encoding='utf-8')
        except FileNotFoundError:
            logger.error(f"Config file not found: {toml_path}")
        except Exception as e:
            logger.error(f"Unexpected error saving config: {e}")
