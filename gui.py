import logging
import queue
import threading

from collections import Counter

from config import Config
from config_editor import ConfigEditor
from gui_utils import report_errors, set_window_icon, show_error
from models import PlaylistInfo, TrackInfo, TrackStatus
from pipeline import DownloadListener, download_playlist
from sources import extract_playlist_info
from utils import REJECTED_FOLDER_NAME

import tkinter as tk
from tkinter import messagebox, ttk

logger = logging.getLogger(__name__)

# Layout of the track table: id, heading, width ratio, centered, editable
COLUMNS = (
    ('name',         "Name",          0.24, False, True),
    ('title',        "Title",         0.14, False, True),
    ('artists',      "Artists",       0.14, False, True),
    ('album',        "Album",         0.10, False, True),
    ('albumartists', "Album Artists", 0.10, False, True),
    ('year',         "Year",          0.05, True,  True),
    ('number',       "Number",        0.05, True,  True),
    ('genre',        "Genre",         0.08, True,  True),
    ('category',     "Category",      0.05, True,  False),
    ('status',       "Status",        0.05, True,  False)
)

COLUMN_IDS = tuple(column[0] for column in COLUMNS)
STATUS_INDEX = COLUMN_IDS.index('status')

# Row tint per outcome, scanning a long playlist by colour is faster than reading
STATUS_COLOURS = {
    TrackStatus.DOWNLOADING: '#e3f2fd',
    TrackStatus.DOWNLOADED:  '#e8f5e9',
    TrackStatus.SKIPPED:     '#eceff1',
    TrackStatus.REJECTED:    '#fff4e5',
    TrackStatus.FAILED:      '#fdecea'
}

class EntryPopup(ttk.Entry):
    """ Text entry widget that gets displayed to edit TableView cells """
    def __init__(self, parent, row, column, text, **kw):
        super().__init__(parent, **kw)
        self.tableview = parent
        self.row = row
        self.column = column

        # Set initial text
        self.insert(0, text)
        # Disable copy to clipboard on select
        self['exportselection'] = False

        self.focus_force()
        self.select_all()
        self.bind('<Return>', self.on_return)
        self.bind('<FocusOut>', self.on_return)
        self.bind('<Control-a>', self.select_all)
        self.bind('<Escape>', lambda *ignore: self.destroy())

    def on_return(self, event):
        # Get row in table view
        values = list(self.tableview.item(self.row, 'values'))

        # Update cell in row
        values[self.column] = self.get()

        # Update row in table view
        self.tableview.item(self.row, values=values)

        # Close the entry popup
        self.destroy()

    def select_all(self, *ignore):
        # Select the whole text
        self.selection_range(0, 'end')

        # Interrupt default key bindings
        return 'break'

class TableView(ttk.Treeview):
    """ Tree view with mutable cells """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.bind("<Double-1>", self.on_double_click)
        self.readonly_columns = []

    def set_readonly_columns(self, columns):
        # Validate columns
        for column in columns:
            if column not in self['columns']:
                logger.error(f"Invalid column '{column}'")
        
        # Set columns
        self.readonly_columns = columns

    def on_double_click(self, event):
        # Close previous popup (if any)
        try:
            self.entryPopup.destroy()
        except AttributeError:
            pass # No previous popup

        # Identify cell that was clicked
        row = self.identify_row(event.y)
        column = self.identify_column(event.x)
        culumn_index = int(column[1:]) - 1

        # Don't do anything if an header was clicked
        if not row or self['columns'][culumn_index] in self.readonly_columns:
            return

        # Get cell rect
        x, y, width, height = self.bbox(row, column)

        # Offset y position (normally vertically centered)
        y += height // 2

        # Show entry popup
        text = self.item(row, 'values')[culumn_index]
        justification = 'center' if str(self.column(column, 'anchor')) == tk.CENTER else 'left'
        self.entryPopup = EntryPopup(self, row, culumn_index, text, justify=justification)
        self.entryPopup.place(x=x, y=y, width=width, height=height, anchor='w')

def add_list_entry(config: Config, tableview: TableView, track_info: TrackInfo):
    """ Adds a new track to a table view and returns its row """
    return tableview.insert(
        "",
        tk.END,
        values=(
            track_info.name,
            track_info.title,
            config.metadata.artist_delimiter.join(track_info.artists),
            track_info.album,
            config.metadata.artist_delimiter.join(track_info.album_artists),
            track_info.year,
            track_info.number,
            track_info.genre,
            track_info.category,
            TrackStatus.PENDING
        )
    )

def set_row_status(tableview: TableView, row, status: str):
    """ Updates the status cell of a row and tints it accordingly """
    values = list(tableview.item(row, 'values'))
    values[STATUS_INDEX] = status
    tableview.item(row, values=values, tags=(status,) if status else ())

def update_playlist_info(config: Config, tableview: TableView, playlist_info: PlaylistInfo):
    """ Updates playlist info using current table view data """
    row_index = 0

    for track_info in playlist_info.get_flat_list():
        row = tableview.get_children()[row_index]
        values = tableview.item(row, 'values')
        assert(len(values) == len(COLUMN_IDS))
        assert(values[COLUMN_IDS.index('category')] == track_info.category)

        track_info.name = values[0]
        track_info.title = values[1]
        track_info.artists = values[2].split(config.metadata.artist_delimiter)
        track_info.album = values[3]
        track_info.album_artists = values[4].split(config.metadata.artist_delimiter)
        track_info.year = values[5]
        track_info.number = values[6]
        track_info.genre = values[7]

        row_index += 1

def download_playlist_gui(config: Config, playlist_url: str):
    """ Downloads a playlist (graphical version) """
    # Create window
    root = tk.Tk()
    root.title("Track Downloader")
    root.minsize(640, 480)
    set_window_icon(root)

    # ========== Toolbar ==========
    toolbar_frame = ttk.Frame(root)
    toolbar_frame.pack(fill=tk.X, padx=10, pady=5)

    # Config Button (left-aligned)
    config_editor = ConfigEditor(config)
    config_button = ttk.Button(toolbar_frame, text="Config", command=lambda: config_editor.open(root))
    config_button.pack(side=tk.LEFT)

    # Playlist controls (centered inside a nested frame)
    playlist_controls_frame = ttk.Frame(toolbar_frame)
    playlist_controls_frame.pack(side=tk.LEFT, expand=True)

    playlist_label = ttk.Label(playlist_controls_frame, text="Playlist URL")
    playlist_entry = ttk.Entry(playlist_controls_frame, width=70)
    playlist_entry.insert(0, playlist_url)
    playlist_button = ttk.Button(playlist_controls_frame, text="Load", command=lambda: on_load_playlist())

    playlist_label.pack(side=tk.LEFT)
    playlist_entry.pack(side=tk.LEFT, padx=10)
    playlist_button.pack(side=tk.LEFT)

    # Progress of the current run (right-aligned)
    progress_label = ttk.Label(toolbar_frame, text='', width=12, anchor='e')
    progress_label.pack(side=tk.RIGHT)

    # ========== Table View ==========
    tableview = TableView(root, columns=COLUMN_IDS)
    tableview.set_readonly_columns([column_id for column_id, _, _, _, editable in COLUMNS if not editable])

    total_width = tableview.winfo_reqwidth()
    tableview.column('#0', width=0, stretch=tk.NO)

    for column_id, heading, ratio, centered, _ in COLUMNS:
        tableview.column(
            column_id,
            width=int(total_width * ratio),
            minwidth=60,
            anchor=tk.CENTER if centered else tk.W,
            stretch=not centered
        )
        tableview.heading(column_id, text=heading)

    tableview['show'] = 'headings'

    # Tint each row according to how its download went
    for status, colour in STATUS_COLOURS.items():
        tableview.tag_configure(status, background=colour)

    tableview.pack(expand=True, fill=tk.BOTH, padx=10)

    # Global playlist info
    playlist_info = PlaylistInfo()

    # Row of each track, TrackInfo isn't hashable so it is keyed by identity
    rows_by_track = {}

    # Downloads run off the main thread, every widget update goes through here
    events = queue.Queue()
    cancel_event = threading.Event()

    # Progress of the current run and how each track ended
    progress = {'done': 0, 'total': 0}
    outcomes = []

    # ========== Callbacks ==========
    class GuiListener(DownloadListener):
        """ Reports the progress of a download run to the window
            Runs on the worker thread, so it may only post events
        """

        def prompt(self, message):
            # Block the download until the dialog is acknowledged
            acknowledged = threading.Event()
            events.put(('prompt', message, acknowledged))
            acknowledged.wait()

        def track_status(self, track_info, status):
            events.put(('status', id(track_info), status))

        def is_cancelled(self):
            return cancel_event.is_set()

    def set_running(running):
        """ Keeps the window out of a state a running download can't handle """
        state = tk.DISABLED if running else tk.NORMAL
        for widget in (playlist_button, download_selected_button, download_all_button, config_button):
            widget.configure(state=state)
        cancel_button.configure(state=tk.NORMAL if running else tk.DISABLED)

    def update_progress():
        """ Shows how many tracks are done out of how many were queued """
        if not progress['total']:
            progress_label.configure(text='')
            return

        progress_label.configure(text=f"{progress['done']} / {progress['total']}")

    def start_download(tracks_to_download):
        """ Runs a download on a worker thread so the window stays responsive """
        cancel_event.clear()

        # Reset the outcome of a previous run
        outcomes.clear()
        progress['done'] = 0
        progress['total'] = len(tracks_to_download.get_flat_list())
        update_progress()

        for track_info in tracks_to_download.get_flat_list():
            row = rows_by_track.get(id(track_info))
            if row:
                set_row_status(tableview, row, TrackStatus.PENDING)

        set_running(True)

        def run():
            error = None
            try:
                download_playlist(config, tracks_to_download, GuiListener())
            except Exception as e:
                error = e
            events.put(('done', error))

        threading.Thread(target=run, daemon=True).start()

    def on_download_finished(error):
        set_running(False)

        if error:
            show_error("Download", error)
            return

        if not outcomes:
            return

        # Report what happened, the console log has the details
        counts = Counter(outcomes)
        summary = ', '.join(f"{counts[status]} {status.lower()}"
                            for status in (TrackStatus.DOWNLOADED, TrackStatus.SKIPPED,
                                           TrackStatus.REJECTED, TrackStatus.FAILED)
                            if counts[status])

        if cancel_event.is_set():
            summary = f"Cancelled after {len(outcomes)} of {progress['total']} tracks.\n\n{summary}"
        if counts[TrackStatus.REJECTED]:
            summary += f"\n\nRejected tracks are kept in '{REJECTED_FOLDER_NAME}'."

        messagebox.showinfo("Download", summary or "Nothing was downloaded.")

    def pump_events():
        """ Applies the events posted by the worker thread """
        try:
            while True:
                event = events.get_nowait()
                kind = event[0]

                if kind == 'status':
                    status = event[2]
                    row = rows_by_track.get(event[1])
                    if row:
                        set_row_status(tableview, row, status)

                    # A track is done once it reaches a final status
                    if status != TrackStatus.DOWNLOADING:
                        outcomes.append(status)
                        progress['done'] = len(outcomes)
                        update_progress()
                elif kind == 'prompt':
                    messagebox.showinfo("Manual Download", f"{event[1]}\n\nClick OK once done.")
                    event[2].set()
                elif kind == 'done':
                    on_download_finished(event[1])
        except queue.Empty:
            pass

        root.after(100, pump_events)

    @report_errors("Load Playlist")
    def on_load_playlist():
        nonlocal playlist_info

        # Clear table view
        tableview.delete(*tableview.get_children())
        rows_by_track.clear()
        playlist_info = PlaylistInfo()

        # Extract track infos
        playlist_info = extract_playlist_info(config, playlist_entry.get())

        # Populate table view
        for track_info in playlist_info.get_flat_list():
            rows_by_track[id(track_info)] = add_list_entry(config, tableview, track_info)

        if not playlist_info.get_flat_list():
            messagebox.showinfo("Load Playlist", "This playlist has no track to download.")

    @report_errors("Download")
    def on_download_selected():
        nonlocal playlist_info

        # Update global playlist info from table view
        update_playlist_info(config, tableview, playlist_info)

        # Extract selected track infos
        track_infos = playlist_info.get_flat_list()
        selected_track_infos = [track_infos[tableview.index(row)] for row in tableview.selection()]

        if not selected_track_infos:
            messagebox.showinfo("Download", "Select at least one track to download.")
            return

        # Download selected tracks
        start_download(PlaylistInfo.from_flat_list(selected_track_infos))

    @report_errors("Download")
    def on_download_all():
        nonlocal playlist_info

        update_playlist_info(config, tableview, playlist_info)

        if not playlist_info.get_flat_list():
            messagebox.showinfo("Download", "Load a playlist first.")
            return

        start_download(playlist_info)

    def on_cancel():
        # The current track finishes, the next one won't start
        cancel_event.set()
        cancel_button.configure(state=tk.DISABLED)

    # ========== Download Buttons ==========
    download_buttons_frame = ttk.Frame(root)
    download_selected_button = ttk.Button(download_buttons_frame, text="Download Selected", command=on_download_selected)
    download_all_button = ttk.Button(download_buttons_frame, text="Download All", command=on_download_all)
    cancel_button = ttk.Button(download_buttons_frame, text="Cancel", command=on_cancel, state=tk.DISABLED)

    download_selected_button.pack(side=tk.LEFT, padx=10)
    download_all_button.pack(side=tk.LEFT, padx=10)
    cancel_button.pack(side=tk.LEFT, padx=10)
    download_buttons_frame.pack(padx=10, pady=10)

    # Start pumping worker events, then the main loop
    root.after(100, pump_events)
    root.mainloop()