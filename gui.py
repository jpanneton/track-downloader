from config import Config
from config_editor import ConfigEditor
from models import PlaylistInfo, TrackInfo
from pipeline import download_playlist
from sources import extract_playlist_info

import tkinter as tk
from tkinter import messagebox, ttk

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
                print(f"ERROR: Invalid column '{column}'")
        
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
    """ Adds a new track to a table view """
    tableview.insert(
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
            track_info.category
        )
    )

def update_playlist_info(config: Config, tableview: TableView, playlist_info: PlaylistInfo):
    """ Updates playlist info using current table view data """
    row_index = 0

    for track_info in playlist_info.get_flat_list():
        row = tableview.get_children()[row_index]
        values = tableview.item(row, 'values')
        assert(len(values) == 9)
        assert(values[-1] == track_info.category)

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
    root.iconbitmap("icon.ico")

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

    # ========== Table View ==========
    tableview = TableView(root, columns=('name', 'title', 'artists', 'album', 'albumartists', 'year', 'number', 'genre', 'category'))
    tableview.set_readonly_columns(['category'])

    tableview.column('#0', width=0, stretch=tk.NO)
    tableview.column('name', width=int(tableview.winfo_reqwidth() * 0.25), minwidth=100)
    tableview.column('title', width=int(tableview.winfo_reqwidth() * 0.15), minwidth=100)
    tableview.column('artists', width=int(tableview.winfo_reqwidth() * 0.15), minwidth=100)
    tableview.column('album', width=int(tableview.winfo_reqwidth() * 0.1), minwidth=100)
    tableview.column('albumartists', width=int(tableview.winfo_reqwidth() * 0.1), minwidth=100)
    tableview.column('year', width=int(tableview.winfo_reqwidth() * 0.05), minwidth=100, anchor=tk.CENTER, stretch=False)
    tableview.column('number', width=int(tableview.winfo_reqwidth() * 0.05), minwidth=100, anchor=tk.CENTER, stretch=False)
    tableview.column('genre', width=int(tableview.winfo_reqwidth() * 0.10), minwidth=100, anchor=tk.CENTER)
    tableview.column('category', width=int(tableview.winfo_reqwidth() * 0.05), minwidth=100, anchor=tk.CENTER, stretch=False)

    tableview['show'] = 'headings'
    tableview.heading('name', text="Name")
    tableview.heading('title', text="Title")
    tableview.heading('artists', text="Artists")
    tableview.heading('album', text="Album")
    tableview.heading('albumartists', text="Album Artists")
    tableview.heading('year', text="Year")
    tableview.heading('number', text="Number")
    tableview.heading('genre', text="Genre")
    tableview.heading('category', text="Category")

    tableview.pack(expand=True, fill=tk.BOTH, padx=10)

    # Global playlist info
    playlist_info = PlaylistInfo()

    # ========== Callbacks ==========
    def on_prompt(message):
        # A console prompt would be invisible and freeze the window
        messagebox.showinfo("Manual Download", f"{message}\n\nClick OK once done.")

    def on_load_playlist():
        nonlocal playlist_info

        # Clear table view
        tableview.delete(*tableview.get_children())

        # Extract track infos
        playlist_info = extract_playlist_info(config, playlist_entry.get())

        # Populate table view
        for track_info in playlist_info.get_flat_list():
            add_list_entry(config, tableview, track_info)

    def on_download_selected():
        nonlocal playlist_info

        # Update global playlist info from table view
        update_playlist_info(config, tableview, playlist_info)

        # Extract selected track infos
        track_infos = playlist_info.get_flat_list()
        selected_track_infos = [track_infos[tableview.index(row)] for row in tableview.selection()]

        # Download selected tracks
        download_playlist(config, PlaylistInfo.from_flat_list(selected_track_infos), on_prompt)

    def on_download_all():
        nonlocal playlist_info
        update_playlist_info(config, tableview, playlist_info)
        download_playlist(config, playlist_info, on_prompt)

    # ========== Download Buttons ==========
    download_buttons_frame = ttk.Frame(root)
    download_selected_button = ttk.Button(download_buttons_frame, text="Download Selected", command=on_download_selected)
    download_all_button = ttk.Button(download_buttons_frame, text="Download All", command=on_download_all)

    download_selected_button.pack(side=tk.LEFT, padx=10)
    download_all_button.pack(side=tk.LEFT, padx=10)
    download_buttons_frame.pack(padx=10, pady=10)

    # Start main loop
    root.mainloop()