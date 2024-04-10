from api import (
    Config,
    PlaylistInfo,
    TrackInfo,
    download_playlist,
    extract_playlist_info
)

import tkinter as tk
from tkinter import ttk

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

    def on_double_click(self, event):
        # Close previous popup (if any)
        try:
            self.entryPopup.destroy()
        except AttributeError:
            pass # No previous popup

        # Identify cell that was clicked
        row = self.identify_row(event.y)
        column = self.identify_column(event.x)

        # Don't do anything if an header was clicked
        if not row:
            return

        # Get cell rect
        x, y, width, height = self.bbox(row, column)

        # Offset y position (normally vertically centered)
        y += height // 2

        # Show entry popup
        text = self.item(row, 'values')[int(column[1:]) - 1]
        self.entryPopup = EntryPopup(self, row, int(column[1:]) - 1, text)
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
        assert(len(values) == 8)
        assert(values[-1] == track_info.category)

        track_info.name = values[0]
        track_info.title = values[1]
        track_info.artists = values[2].split(config.metadata.artist_delimiter)
        track_info.album = values[3]
        track_info.year = values[4]
        track_info.number = values[5]
        track_info.genre = values[6]

        row_index += 1

def download_playlist_gui(config: Config, playlist_url: str):
    """ Downloads a playlist (graphical version) """
    # Create window
    root = tk.Tk()
    root.title("Track Downloader")
    root.minsize(640, 480)
    root.iconbitmap("icon.ico")

    # Init columns
    tableview = TableView(root, columns=('name', 'title', 'artists', 'album', 'year', 'number', 'genre', 'category'))

    tableview.column('#0', width=0, stretch=tk.NO)
    tableview.column('name', width=int(tableview.winfo_reqwidth() * 0.25), minwidth=100)
    tableview.column('title', width=int(tableview.winfo_reqwidth() * 0.2), minwidth=100)
    tableview.column('artists', width=int(tableview.winfo_reqwidth() * 0.2), minwidth=100)
    tableview.column('album', width=int(tableview.winfo_reqwidth() * 0.1), minwidth=100)
    tableview.column('year', width=int(tableview.winfo_reqwidth() * 0.05), minwidth=100, anchor='center', stretch=False)
    tableview.column('number', width=int(tableview.winfo_reqwidth() * 0.05), minwidth=100, anchor='center', stretch=False)
    tableview.column('genre', width=int(tableview.winfo_reqwidth() * 0.10), minwidth=100, anchor='center')
    tableview.column('category', width=int(tableview.winfo_reqwidth() * 0.05), minwidth=100, anchor='center', stretch=False)

    tableview['show'] = 'headings'
    tableview.heading('name', text="Name")
    tableview.heading('title', text="Title")
    tableview.heading('artists', text="Artists")
    tableview.heading('album', text="Album")
    tableview.heading('year', text="Year")
    tableview.heading('number', text="Number")
    tableview.heading('genre', text="Genre")
    tableview.heading('category', text="Category")

    playlist_frame = ttk.Frame(root)
    playlist_label = ttk.Label(playlist_frame, text="Playlist URL")
    playlist_entry = ttk.Entry(playlist_frame)
    playlist_entry.insert(0, playlist_url)

    # Global playlist info
    playlist_info = PlaylistInfo()

    # Define button callbacks
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
        selected_track_infos = []
        for row in tableview.selection():
            selected_track_infos.append(track_infos[tableview.index(row)])

        # Download selected tracks
        download_playlist(config, PlaylistInfo.from_flat_list(selected_track_infos))

    def on_download_all():
        nonlocal playlist_info

        # Update global playlist info from table view
        update_playlist_info(config, tableview, playlist_info)

        # Download every tracks
        download_playlist(config, playlist_info)

    # Create buttons
    playlist_button = ttk.Button(playlist_frame, text ="Load", command=on_load_playlist)

    download_buttons_frame = ttk.Frame(root)
    download_selected_button = ttk.Button(download_buttons_frame, text ="Download Selected", command=on_download_selected)
    download_all_button = ttk.Button(download_buttons_frame, text ="Download All", command=on_download_all)

    # Layout UI
    playlist_label.pack(side=tk.LEFT)
    playlist_entry.pack(side=tk.LEFT)
    playlist_button.pack(side=tk.LEFT)
    playlist_frame.pack(padx=10, pady=10)

    tableview.pack(expand=True, fill='both', padx=10)

    download_selected_button.pack(side=tk.LEFT, padx=10)
    download_all_button.pack(side=tk.LEFT, padx=10)
    download_buttons_frame.pack(padx=10, pady=10)

    # Run main loop
    root.mainloop()
