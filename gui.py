import logging
import os
import queue
import threading

from collections import Counter

from config import Config
from config_editor import ConfigEditor
from gui_utils import (
    QueueLogHandler,
    apply_theme,
    fit_to_screen,
    report_errors,
    restore_window_layout,
    save_window_layout,
    set_window_icon,
    show_error,
    theme_colours
)
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

# Attributes the batch editor can overwrite, keyed by the heading it shows
EDITABLE_COLUMNS = {
    heading: column_id
    for column_id, heading, _, _, editable in COLUMNS if editable
}

WINDOW_TITLE = "Track Downloader"

# Lines kept in the log panel, a long run would grow it without bound
LOG_LINE_LIMIT = 500

# Row tint per outcome, scanning a long playlist by colour is faster than reading
# The hues are saturated enough to tell apart at a glance while keeping the
# text readable, paler tints made 'Downloaded' and 'Skipped' look alike
STATUS_COLOURS = {
    'classic': {
        TrackStatus.DOWNLOADING: '#90caf9',
        TrackStatus.DOWNLOADED:  '#7cc47f',
        TrackStatus.SKIPPED:     '#c3ccd1',
        TrackStatus.REJECTED:    '#ffb74d',
        TrackStatus.FAILED:      '#e57373'
    },
    'light': {
        TrackStatus.DOWNLOADING: '#90caf9',
        TrackStatus.DOWNLOADED:  '#7cc47f',
        TrackStatus.SKIPPED:     '#c3ccd1',
        TrackStatus.REJECTED:    '#ffb74d',
        TrackStatus.FAILED:      '#e57373'
    },
    'dark': {
        TrackStatus.DOWNLOADING: '#1e3a5f',
        TrackStatus.DOWNLOADED:  '#1e4620',
        TrackStatus.SKIPPED:     '#37474f',
        TrackStatus.REJECTED:    '#5d4037',
        TrackStatus.FAILED:      '#5c1e1e'
    }
}

# Text on the tints above, the light ones are too bright for white text
STATUS_TEXT_COLOURS = {'classic': '#000000', 'light': '#000000', 'dark': '#ffffff'}

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
        # Called instead of editing when a readonly cell is double clicked
        self.on_readonly_double_click = None

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
        if not row:
            return

        # A readonly cell can still act on the double click
        column_id = self['columns'][culumn_index]
        if column_id in self.readonly_columns:
            if self.on_readonly_double_click:
                self.on_readonly_double_click(row, column_id)
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

def update_playlist_info(config: Config, tableview: TableView, tracks_by_row):
    """ Updates track infos using current table view data
        Rows are matched by identity, sorting the table reorders them
    """
    for row in tableview.get_children():
        track_info = tracks_by_row.get(row)
        if not track_info:
            continue

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

def download_playlist_gui(config: Config, playlist_url: str):
    """ Downloads a playlist (graphical version) """
    # Create window
    root = tk.Tk()
    root.title(WINDOW_TITLE)
    root.minsize(640, 480)
    set_window_icon(root)

    # Applied before the widgets are built so they pick up the styling
    theme = apply_theme(config.interface.theme)
    colours = theme_colours()

    restored_layout = restore_window_layout(root)

    # ========== Toolbar ==========
    # The playlist URL is the starting point, the rest are utilities
    toolbar_frame = ttk.Frame(root)
    toolbar_frame.pack(fill=tk.X, padx=10, pady=(8, 4))

    config_editor = ConfigEditor(config)
    config_button = ttk.Button(toolbar_frame, text="Config", command=lambda: config_editor.open(root))
    log_button = ttk.Button(toolbar_frame, text="Hide Log", command=lambda: toggle_log())
    open_folder_button = ttk.Button(toolbar_frame, text="Open Folder", command=lambda: on_open_downloads())

    # Packed first so they keep their size when the entry grows
    log_button.pack(side=tk.RIGHT)
    open_folder_button.pack(side=tk.RIGHT, padx=5)
    config_button.pack(side=tk.RIGHT)

    ttk.Label(toolbar_frame, text="Playlist URL").pack(side=tk.LEFT)

    playlist_entry = ttk.Entry(toolbar_frame)
    playlist_entry.insert(0, playlist_url)
    playlist_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=8)

    playlist_button = ttk.Button(toolbar_frame, text="Load", command=lambda: on_load_playlist())
    playlist_button.pack(side=tk.LEFT, padx=(0, 15))

    # Loading is the obvious thing to do after typing a URL
    playlist_entry.bind('<Return>', lambda *ignore: on_load_playlist())

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

    def sort_by_column(column_id, descending):
        """ Sorts the rows on a column, grouping outcomes together after a run """
        index = COLUMN_IDS.index(column_id)
        rows = sorted(tableview.get_children(),
                      key=lambda row: str(tableview.item(row, 'values')[index]).lower(),
                      reverse=descending)

        for position, row in enumerate(rows):
            tableview.move(row, '', position)

        # Clicking the same header again reverses the order
        tableview.heading(column_id, command=lambda: sort_by_column(column_id, not descending))

    for column_id, heading, _, _, _ in COLUMNS:
        tableview.heading(column_id, command=lambda c=column_id: sort_by_column(c, False))

    # Tint each row according to how its download went, the text colour is
    # pinned so a dark system theme doesn't put light text on these tints
    for status, colour in STATUS_COLOURS[theme].items():
        tableview.tag_configure(status, background=colour,
                                foreground=STATUS_TEXT_COLOURS[theme])


    # Sitting in front of an empty grid, there is nothing saying what to do
    empty_hint = ttk.Label(
        tableview,
        text="Paste a SoundCloud or Spotify playlist URL above, then click Load",
        foreground=colours['muted'],
        anchor='center'
    )

    def update_empty_hint():
        if tableview.get_children():
            empty_hint.place_forget()
        else:
            empty_hint.place(relx=0.5, rely=0.5, anchor='center')

    # The selection drives the counts and what the buttons act on
    tableview.bind('<<TreeviewSelect>>', lambda *ignore: update_status_label())

    # ========== Selected Tracks ==========
    # Everything acting on the selection lives together
    selection_frame = ttk.LabelFrame(root, text="Selected tracks", padding=(8, 4, 8, 8))

    select_row = ttk.Frame(selection_frame)
    select_row.pack(fill=tk.X)

    select_all_button = ttk.Button(select_row, text="Select All", command=lambda: on_select_all())
    invert_button = ttk.Button(select_row, text="Invert", command=lambda: on_invert_selection())

    select_all_button.pack(side=tk.LEFT)
    invert_button.pack(side=tk.LEFT, padx=5)

    ttk.Label(select_row, text="Select by status").pack(side=tk.LEFT, padx=(15, 5))
    status_filter = ttk.Combobox(
        select_row,
        values=[TrackStatus.DOWNLOADED, TrackStatus.SKIPPED, TrackStatus.REJECTED, TrackStatus.FAILED],
        state="readonly",
        width=12
    )
    status_filter.pack(side=tk.LEFT)
    status_filter.bind('<<ComboboxSelected>>', lambda *ignore: on_select_by_status())

    # The genre is the one worth setting in bulk, the backends report their own
    default_genre = config.metadata.genre_override or config.metadata.default_genre

    edit_row = ttk.Frame(selection_frame)
    edit_row.pack(fill=tk.X, pady=(8, 0))

    ttk.Label(edit_row, text="Set").pack(side=tk.LEFT)

    edit_column = ttk.Combobox(edit_row, values=list(EDITABLE_COLUMNS), state="readonly", width=14)
    edit_column.set("Genre")
    edit_column.pack(side=tk.LEFT, padx=5)

    ttk.Label(edit_row, text="to").pack(side=tk.LEFT)

    edit_value = ttk.Entry(edit_row)
    edit_value.insert(0, default_genre)
    edit_value.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=5)

    apply_button = ttk.Button(edit_row, text="Apply", command=lambda: on_apply_edit())
    apply_button.pack(side=tk.LEFT)

    def on_edit_column_changed(*ignore):
        # Only the genre has a sensible value to suggest
        edit_value.delete(0, tk.END)
        if EDITABLE_COLUMNS[edit_column.get()] == 'genre':
            edit_value.insert(0, default_genre)

    edit_column.bind('<<ComboboxSelected>>', on_edit_column_changed)
    edit_value.bind('<Return>', lambda *ignore: on_apply_edit())

    # ========== Log Panel ==========
    log_frame = ttk.LabelFrame(root, text="Log", padding=(8, 4, 8, 8))
    log_text = tk.Text(
        log_frame, height=8, wrap=tk.NONE, state=tk.DISABLED,
        background=colours['background'], foreground=colours['foreground'],
        insertbackground=colours['foreground'], relief=tk.FLAT,
        borderwidth=0, highlightthickness=0
    )
    log_scroll = ttk.Scrollbar(log_frame, orient=tk.VERTICAL, command=log_text.yview)
    log_text.configure(yscrollcommand=log_scroll.set)

    log_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    log_text.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)

    def append_log(line):
        """ Appends a line to the log panel, keeping only the recent ones """
        log_text.configure(state=tk.NORMAL)
        log_text.insert(tk.END, line + '\n')

        # Drop the oldest lines so a long run doesn't grow without bound
        extra = int(log_text.index('end-1c').split('.')[0]) - LOG_LINE_LIMIT
        if extra > 0:
            log_text.delete('1.0', f'{extra + 1}.0')

        log_text.see(tk.END)
        log_text.configure(state=tk.DISABLED)

    def show_log(visible):
        if visible:
            # Keep the panel between the table and the buttons, packing it
            # without a reference would drop it below them
            log_frame.pack(side=tk.BOTTOM, fill=tk.BOTH, padx=10, pady=(5, 0),
                           before=selection_frame)
        else:
            log_frame.pack_forget()

        log_button.configure(text="Hide Log" if visible else "Show Log")

    def toggle_log():
        show_log(not log_frame.winfo_ismapped())

    # Global playlist info
    playlist_info = PlaylistInfo()

    # Row of each track and back, TrackInfo isn't hashable so it is keyed by
    # identity. Both directions are needed once the table can be sorted.
    rows_by_track = {}
    tracks_by_row = {}

    # Downloads run off the main thread, every widget update goes through here
    events = queue.Queue()
    cancel_event = threading.Event()

    # Scheduled event pump, cancelled when the window closes
    pump_job = {'id': None}

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
        for widget in (playlist_button, download_selected_button, download_all_button,
                       config_button, apply_button):
            widget.configure(state=state)
        cancel_button.configure(state=tk.NORMAL if running else tk.DISABLED)

    def update_progress():
        """ Shows how many tracks are done out of how many were queued """
        if not progress['total']:
            progress_label.configure(text='')
            progress_bar.pack_forget()
            root.title(WINDOW_TITLE)
            return

        done, total = progress['done'], progress['total']
        progress_label.configure(text=f"{done} / {total}")

        # Shown only while a run is in progress
        if not progress_bar.winfo_ismapped():
            progress_bar.pack(side=tk.RIGHT, padx=(0, 5))

        progress_bar.configure(maximum=total, value=done)

        # Visible even when the window is behind something else
        root.title(f"{WINDOW_TITLE} - downloading {done}/{total}")

    def update_status_label():
        """ Summarises what is loaded, selected and what a run produced """
        total = len(tableview.get_children())
        if not total:
            status_label.configure(text="No playlist loaded")
            return

        parts = [f"{total} track{'s' if total != 1 else ''}"]

        selected = len(tableview.selection())
        if selected:
            parts.append(f"{selected} selected")

        if outcomes:
            counts = Counter(outcomes)
            parts.extend(f"{counts[status]} {status.lower()}"
                         for status in (TrackStatus.DOWNLOADED, TrackStatus.SKIPPED,
                                        TrackStatus.REJECTED, TrackStatus.FAILED)
                         if counts[status])

        status_label.configure(text='  ·  '.join(parts))

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
        progress['total'] = 0
        update_progress()
        update_status_label()

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
                        update_status_label()
                elif kind == 'prompt':
                    messagebox.showinfo("Manual Download", f"{event[1]}\n\nClick OK once done.")
                    event[2].set()
                elif kind == 'log':
                    append_log(event[1])
                elif kind == 'done':
                    on_download_finished(event[1])
        except queue.Empty:
            pass

        # Tracked so closing the window can cancel it, a pending callback
        # firing after the widgets are gone raises a Tcl error
        pump_job['id'] = root.after(100, pump_events)

    @report_errors("Load Playlist")
    def on_load_playlist():
        nonlocal playlist_info

        # Clear table view
        tableview.delete(*tableview.get_children())
        rows_by_track.clear()
        tracks_by_row.clear()
        outcomes.clear()
        playlist_info = PlaylistInfo()

        # Extract track infos
        playlist_info = extract_playlist_info(config, playlist_entry.get())

        # Populate table view
        for track_info in playlist_info.get_flat_list():
            row = add_list_entry(config, tableview, track_info)
            rows_by_track[id(track_info)] = row
            tracks_by_row[row] = track_info

        update_status_label()
        update_empty_hint()

        if not playlist_info.get_flat_list():
            messagebox.showinfo("Load Playlist", "This playlist has no track to download.")

    @report_errors("Download")
    def on_download_selected():
        nonlocal playlist_info

        # Update global playlist info from table view
        update_playlist_info(config, tableview, tracks_by_row)

        # Extract selected track infos
        selected_track_infos = [tracks_by_row[row] for row in tableview.selection()
                                if row in tracks_by_row]

        if not selected_track_infos:
            messagebox.showinfo("Download", "Select at least one track to download.")
            return

        # Download selected tracks
        start_download(PlaylistInfo.from_flat_list(selected_track_infos))

    @report_errors("Download")
    def on_download_all():
        nonlocal playlist_info

        update_playlist_info(config, tableview, tracks_by_row)

        if not playlist_info.get_flat_list():
            messagebox.showinfo("Download", "Load a playlist first.")
            return

        start_download(playlist_info)

    def on_cancel():
        # The current track finishes, the next one won't start
        cancel_event.set()
        cancel_button.configure(state=tk.DISABLED)

    @report_errors("Batch Edit")
    def on_apply_edit():
        rows = tableview.selection()
        if not rows:
            messagebox.showinfo("Batch Edit", "Select at least one track to edit.")
            return

        heading = edit_column.get()
        column_id = EDITABLE_COLUMNS[heading]
        column_index = COLUMN_IDS.index(column_id)
        value = edit_value.get()

        for row in rows:
            values = list(tableview.item(row, 'values'))
            values[column_index] = value
            tableview.item(row, values=values)


        logger.info(f"Set {heading.lower()} of {len(rows)} track(s) to '{value}'")

        # The edit would be silently ignored while an override is configured
        if column_id == 'genre' and config.metadata.genre_override:
            messagebox.showwarning(
                "Batch Edit",
                f"genre_override is set to '{config.metadata.genre_override}' in the config, "
                "so it is used instead of the genre set here.\n\n"
                "Clear it in the config to tag the genres from this table."
            )

    def on_select_all(*ignore):
        tableview.selection_set(tableview.get_children())
        return 'break'

    def on_invert_selection():
        selected = set(tableview.selection())
        tableview.selection_set([row for row in tableview.get_children() if row not in selected])

    def on_select_by_status():
        """ Selects every track that ended with the chosen status, to retry them """
        wanted = status_filter.get()
        matching = [row for row in tableview.get_children()
                    if tableview.item(row, 'values')[STATUS_INDEX] == wanted]

        tableview.selection_set(matching)
        if matching:
            tableview.see(matching[0])
        else:
            messagebox.showinfo("Select by status", f"No track is marked '{wanted}'.")

    @report_errors("Open Folder")
    def open_folder(folder_path):
        """ Reveals a folder in the file explorer """
        if not os.path.isdir(folder_path):
            messagebox.showinfo("Open Folder", f"Nothing downloaded there yet:\n{folder_path}")
            return

        os.startfile(folder_path)

    def on_open_downloads():
        # The dated folder only exists once something has been exported
        exported = config.downloads.flac_path if config.downloads.lossless else config.downloads.mp3_path
        open_folder(exported if os.path.isdir(exported) else config.downloads.root_path)

    # ========== Action Bar ==========
    # What is loaded on the left, what to do about it on the right
    download_buttons_frame = ttk.Frame(root)

    status_label = ttk.Label(download_buttons_frame, text="No playlist loaded")
    status_label.pack(side=tk.LEFT)

    download_all_button = ttk.Button(download_buttons_frame, text="Download All", command=on_download_all)
    download_selected_button = ttk.Button(download_buttons_frame, text="Download Selected", command=on_download_selected)
    cancel_button = ttk.Button(download_buttons_frame, text="Cancel", command=on_cancel, state=tk.DISABLED)

    cancel_button.pack(side=tk.RIGHT)
    download_all_button.pack(side=tk.RIGHT, padx=5)
    download_selected_button.pack(side=tk.RIGHT)

    progress_label = ttk.Label(download_buttons_frame, text='', anchor='e')
    progress_label.pack(side=tk.RIGHT, padx=(15, 10))

    progress_bar = ttk.Progressbar(download_buttons_frame, mode='determinate', length=140)

    # Anchored to the bottom and packed before the table, so a window too
    # small for its content shrinks the table instead of hiding these buttons
    download_buttons_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=10)

    # Packed after the action bar so it sits above it, the log slots in between
    selection_frame.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(8, 0))

    # Packed last, it is what absorbs whatever space is left
    tableview.pack(side=tk.TOP, expand=True, fill=tk.BOTH, padx=10)

    # Ctrl+A selects every track
    tableview.bind('<Control-a>', on_select_all)

    # Double-clicking the status of a rejected track opens where it was kept
    def on_status_click(row, column_id):
        if column_id != 'status':
            return
        values = tableview.item(row, 'values')
        if values[STATUS_INDEX] == TrackStatus.REJECTED:
            open_folder(os.path.join(config.downloads.root_path, REJECTED_FOLDER_NAME))

    tableview.on_readonly_double_click = on_status_click

    update_status_label()
    update_empty_hint()

    # Mirror the console log into the panel, shown by default so warnings
    # such as a rejected track don't go unnoticed
    log_handler = QueueLogHandler(events)
    logging.getLogger().addHandler(log_handler)
    show_log(True)

    def on_close():
        save_window_layout(root)

        # A running download would keep the process alive otherwise
        cancel_event.set()

        # Stop pumping before the widgets go away
        if pump_job['id']:
            root.after_cancel(pump_job['id'])

        logging.getLogger().removeHandler(log_handler)
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    # The window may never be shorter than the fixed parts need, otherwise the
    # bottom of it is cut off and the download buttons go with it
    root.update_idletasks()
    chrome_height = sum(
        widget.winfo_reqheight() for widget in root.pack_slaves() if widget is not tableview
    )
    root.minsize(
        min(700, int(root.winfo_screenwidth() * 0.9)),
        min(chrome_height + 80, int(root.winfo_screenheight() * 0.9))
    )

    # Without a saved layout the window opens at whatever the widgets ask for,
    # which can be taller than the screen on a scaled or small display
    if not restored_layout:
        fit_to_screen(root)

    # Start pumping worker events, then the main loop
    pump_job['id'] = root.after(100, pump_events)
    root.mainloop()