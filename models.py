from dataclasses import dataclass, field

class TrackStatus:
    """ Outcome of a track in a download run """
    PENDING = ''
    DOWNLOADING = 'Downloading'
    DOWNLOADED = 'Downloaded'
    # Found nothing to download for this track
    SKIPPED = 'Skipped'
    # Downloaded, but the tags didn't match the expected track
    REJECTED = 'Rejected'
    FAILED = 'Failed'

@dataclass(slots=True)
class TrackInfo:
    """ Single track info """
    name: str = ''
    title: str = ''
    artists: list[str] = field(default_factory=list)
    album: str = ''
    album_artists: list[str] = field(default_factory=list)
    year: str = ''
    number: int = 1
    genre: str = ''
    artwork_url: str = ''
    download_url: str = ''
    category: str = ''
    # Recording identifier, the only precise way to match a track on a backend
    isrc: str = ''
    # Where the track was listed, a backend may be able to use it directly
    source_url: str = ''

class PlaylistInfo:
    """ Track info collection """
    def __init__(self):
        self.direct_downloads: list[TrackInfo] = []
        self.gate_downloads: list[TrackInfo] = []
        self.buy_downloads: list[TrackInfo] = []

    def get_flat_list(self):
        """ Returns a flat list containing all the concatenated track infos (gate, direct, buy) """
        track_infos = []
        for track_info in self.gate_downloads:
            track_infos.append(track_info)
        for track_info in self.direct_downloads:
            track_infos.append(track_info)
        for track_info in self.buy_downloads:
            track_infos.append(track_info)
        return track_infos

    @classmethod
    def from_flat_list(cls, track_infos: list[TrackInfo]):
        """ Generates playlist info from concatenated flat list of track infos (gate, direct, buy) """
        result = cls()
        for track_info in track_infos:
            if track_info.category == 'Gate':
                result.gate_downloads.append(track_info)
            elif track_info.category == 'Direct':
                result.direct_downloads.append(track_info)
            elif track_info.category == 'Buy':
                result.buy_downloads.append(track_info)
        return result
