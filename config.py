import logging
import os
import re

from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from pathlib import Path
from tomlkit.api import dumps as dumps_toml, parse as parse_toml, table as toml_table

from errors import ConfigurationError

logger = logging.getLogger(__name__)

CONFIG_PATH = 'config/config.toml'

def require_settings(section: str, **settings):
    """ Makes sure the given settings are filled in, raises otherwise
        Reporting every missing setting at once avoids fixing them one by one
    """
    missing = [name for name, value in settings.items() if not str(value).strip()]
    if missing:
        is_single = len(missing) == 1
        raise ConfigurationError(
            f"Missing {section} {'setting' if is_single else 'settings'}: {', '.join(missing)}. "
            f"Set {'it' if is_single else 'them'} in {SECRETS_PATH} or with the Config button."
        )

# Credentials live in their own file so the shared config can stay in git
SECRETS_PATH = 'config/secrets.toml'
SECRET_SECTIONS = ('spotify', 'deezer', 'qobuz')

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
    # Applied when nothing else provides a genre
    default_genre: str = ''
    # Forced on every track, wins over the playlist and the backend
    genre_override: str = ''

@dataclass(slots=True)
class SoundcloudConfig:
    supported_download_gates: list[str]
    use_web_driver: bool

@dataclass(slots=True)
class SpotifyConfig:
    client_id: str = ''
    client_secret: str = ''
    redirect_url: str = ''

@dataclass(slots=True)
class DeezerConfig:
    deezer_arl: str = ''

@dataclass(slots=True)
class QobuzConfig:
    user_id: str = ''
    token: str = ''
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
    def _migrate_secrets(cls, text):
        """ Moves the credentials of an older config into the secrets file
            Leaving them in the tracked config risks committing them
        """
        try:
            secrets_doc = parse_toml('')
            config_doc = parse_toml(text)

            for section in SECRET_SECTIONS:
                if section in config_doc:
                    secrets_doc[section] = config_doc.pop(section)

            Path(SECRETS_PATH).write_text(dumps_toml(secrets_doc), encoding='utf-8')
            Path(CONFIG_PATH).write_text(dumps_toml(config_doc), encoding='utf-8')
            logger.info(f"Moved credentials from {CONFIG_PATH} to {SECRETS_PATH}")
        except Exception as e:
            # The credentials were still read from the config, keep going
            logger.warning(f"Could not move credentials to {SECRETS_PATH}: {e}")

    @classmethod
    def load(cls):
        # Load TOML doc
        toml_path = CONFIG_PATH
        try:
            text = Path(toml_path).read_text(encoding='utf-8')
            # Unwrap to plain values, tomlkit containers can't be copied back out
            doc = parse_toml(text).unwrap()

            # Credentials override the ones left in the shared config
            secrets_path = Path(SECRETS_PATH)
            if secrets_path.exists():
                secrets_doc = parse_toml(secrets_path.read_text(encoding='utf-8')).unwrap()
                for section in SECRET_SECTIONS:
                    if section in secrets_doc:
                        doc[section] = secrets_doc[section]
            elif any(section in doc for section in SECRET_SECTIONS):
                # Config predating the split, move the credentials out of it
                cls._migrate_secrets(text)

            downloads = DownloadsConfig(**doc['downloads'])
            metadata = MetadataConfig(**doc['metadata'])
            soundcloud = SoundcloudConfig(**doc['soundcloud'])
            # Credential sections only live in the secrets file on a fresh clone
            spotify = SpotifyConfig(**doc.get('spotify', {}))
            deezer = DeezerConfig(**doc.get('deezer', {}))
            qobuz = QobuzConfig(**doc.get('qobuz', {}))

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
                    # The section is missing when writing a fresh secrets file
                    if key not in section:
                        section[key] = toml_table()
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
            toml_path = CONFIG_PATH
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

            # Split the credentials out of the shared config
            secrets_dict = {
                section: config_dict.pop(section)
                for section in SECRET_SECTIONS
                if section in config_dict
            }

            # Update TOML docs manually from dicts
            update_section(doc, config_dict)

            # Drop credentials left over from an older config file
            for section in SECRET_SECTIONS:
                doc.pop(section, None)

            secrets_path = Path(SECRETS_PATH)
            secrets_doc = parse_toml(secrets_path.read_text(encoding='utf-8')) if secrets_path.exists() else parse_toml('')
            update_section(secrets_doc, secrets_dict)

            # Save config
            Path(toml_path).write_text(dumps_toml(doc), encoding='utf-8')
            secrets_path.write_text(dumps_toml(secrets_doc), encoding='utf-8')
        except FileNotFoundError:
            raise ConfigurationError(f"Config file not found: {toml_path}")
        except Exception as e:
            raise ConfigurationError(f"Could not save the config: {e}")
