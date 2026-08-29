import logging
import os

from dataclasses import asdict, dataclass, fields, is_dataclass
from datetime import datetime
from pathlib import Path
from tomlkit.api import dumps as dumps_toml, parse as parse_toml, table as toml_table
from tomlkit.items import Comment, Whitespace

from errors import ConfigurationError
from paths import app_path, resolve_path

logger = logging.getLogger(__name__)

CONFIG_PATH = app_path('config', 'config.toml')

# The templates are the reference, the files next to them hold the values
CONFIG_TEMPLATE_PATH = app_path('config', 'config.toml.example')

def sync_with_template(target_path: Path, template_path: Path):
    """ Creates a config file from its template, or brings it in line with it

        Settings the user changed are kept, ones added to or removed from the
        template are applied so the file never drifts from what the app expects
    """
    try:
        template_text = template_path.read_text(encoding='utf-8')
    except OSError as e:
        logger.debug(f"No template at {template_path}: {e}")
        return

    if not target_path.exists():
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(template_text, encoding='utf-8')
        logger.info(f"Created {target_path.name} from {template_path.name}")
        return

    try:
        current = parse_toml(target_path.read_text(encoding='utf-8'))
    except (OSError, ValueError) as e:
        logger.warning(f"Could not read {target_path.name}, leaving it alone: {e}")
        return

    # Start from the template so its comments and order stay current
    merged = parse_toml(template_text)

    added, removed = [], []
    for section_name, section in merged.items():
        current_section = current.get(section_name)
        for key in section:
            if current_section is not None and key in current_section:
                # Plain values only, tomlkit items carry the other file's layout
                value = current_section[key]
                merged[section_name][key] = value.unwrap() if hasattr(value, 'unwrap') else value
            else:
                added.append(f'{section_name}.{key}')

    for section_name, section in current.items():
        if section_name not in merged:
            removed.append(section_name)
        else:
            removed.extend(f'{section_name}.{key}' for key in section if key not in merged[section_name])

    if not added and not removed:
        return

    target_path.write_text(dumps_toml(merged), encoding='utf-8')
    if added:
        logger.info(f"Added new setting(s) to {target_path.name}: {', '.join(added)}")
    if removed:
        logger.info(f"Removed obsolete setting(s) from {target_path.name}: {', '.join(removed)}")

def build_section(cls, section: str, values):
    """ Builds a config section, ignoring settings the app no longer knows
        A leftover setting shouldn't make the whole config unreadable
    """
    known = {field.name for field in fields(cls)}

    unknown = sorted(set(values) - known)
    if unknown:
        logger.warning(f"Ignoring unknown {section} setting(s): {', '.join(unknown)}")

    return cls(**{name: value for name, value in values.items() if name in known})

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
SECRETS_PATH = app_path('config', 'secrets.toml')
SECRET_SECTIONS = ('spotify', 'deezer', 'qobuz')

# Saving rewrites secrets.toml without comments, the template keeps them
SECRETS_TEMPLATE_PATH = app_path('config', 'secrets.toml.example')

def load_setting_descriptions():
    """ Reads the comment documenting each setting, keyed by section and name
        The config files are the only place these explanations are written down
    """
    descriptions = {}

    for toml_path in (CONFIG_PATH, SECRETS_TEMPLATE_PATH):
        try:
            doc = parse_toml(Path(toml_path).read_text(encoding='utf-8'))
        except (OSError, ValueError) as e:
            logger.debug(f"Could not read the settings documented in {toml_path}: {e}")
            continue

        for section_name, table in doc.items():
            body = getattr(getattr(table, 'value', None), 'body', None)
            if body is None:
                continue

            section = descriptions.setdefault(section_name, {})

            # A setting is documented by the comment lines right above it
            pending = []
            for key, item in body:
                if isinstance(item, Comment):
                    pending.append(item.as_string().lstrip('#').strip())
                elif isinstance(item, Whitespace):
                    pending.clear()
                elif key is not None:
                    if pending:
                        section.setdefault(str(key.key), ' '.join(pending))
                    pending = []

    return descriptions

@dataclass(slots=True)
class DownloadsConfig:
    root_folder: str
    flac_folder: str
    mp3_folder: str
    wav_folder: str
    backend: str
    lossless: bool
    playlist_url: str

    # The fields above hold what the user configured. The paths below are
    # derived from them, storing the result would put today's date in the
    # config and change it every day.

    @property
    def root_path(self):
        """ Absolute path of the folder downloads land in
            A relative folder is relative to the app, not the working directory
        """
        return resolve_path(self.root_folder)

    def export_path(self, folder: str):
        """ Path a format is exported to, grouped by the day of the download """
        return os.path.join(self.root_path, datetime.now().strftime('%Y-%m-%d'), folder)

    @property
    def flac_path(self):
        return self.export_path(self.flac_folder)

    @property
    def mp3_path(self):
        return self.export_path(self.mp3_folder)

    @property
    def wav_path(self):
        return self.export_path(self.wav_folder)

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
class InterfaceConfig:
    theme: str = 'classic'

@dataclass(slots=True)
class SoundcloudConfig:
    supported_download_gates: list[str]
    use_web_driver: bool

@dataclass(slots=True)
class SpotifyConfig:
    client_id: str = ''
    client_secret: str = ''
    user_login: bool = False
    redirect_uri: str = 'http://127.0.0.1:8080/callback'

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
    interface: InterfaceConfig
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
            # A config predating the split still holds the credentials, move
            # them out first or syncing would drop what the template lacks
            if CONFIG_PATH.exists() and not SECRETS_PATH.exists():
                existing = CONFIG_PATH.read_text(encoding='utf-8')
                if any(section in parse_toml(existing) for section in SECRET_SECTIONS):
                    cls._migrate_secrets(existing)

            # Create both files from their template and pick up its changes
            sync_with_template(CONFIG_PATH, CONFIG_TEMPLATE_PATH)
            sync_with_template(SECRETS_PATH, SECRETS_TEMPLATE_PATH)

            text = Path(toml_path).read_text(encoding='utf-8')
            # Unwrap to plain values, tomlkit containers can't be copied back out
            doc = parse_toml(text).unwrap()

            # Credentials live in their own file
            if SECRETS_PATH.exists():
                secrets_doc = parse_toml(SECRETS_PATH.read_text(encoding='utf-8')).unwrap()
                for section in SECRET_SECTIONS:
                    if section in secrets_doc:
                        doc[section] = secrets_doc[section]

            downloads = build_section(DownloadsConfig, 'downloads', doc['downloads'])
            metadata = build_section(MetadataConfig, 'metadata', doc['metadata'])
            soundcloud = build_section(SoundcloudConfig, 'soundcloud', doc['soundcloud'])
            # Added after the first release, an older config file won't have it
            interface = build_section(InterfaceConfig, 'interface', doc.get('interface', {}))
            # Credential sections only live in the secrets file on a fresh clone
            spotify = build_section(SpotifyConfig, 'spotify', doc.get('spotify', {}))
            deezer = build_section(DeezerConfig, 'deezer', doc.get('deezer', {}))
            qobuz = build_section(QobuzConfig, 'qobuz', doc.get('qobuz', {}))

            return cls(
                downloads=downloads,
                metadata=metadata,
                interface=interface,
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

        try:
            # Load original TOML doc to preserve comments
            toml_path = CONFIG_PATH
            text = Path(toml_path).read_text(encoding='utf-8')
            doc = parse_toml(text)

            # Convert config to dict, the fields hold exactly what was configured
            config_dict = dataclass_to_dict(self)

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
