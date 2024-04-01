from api import Config

import tkinter as tk
from tkinter import ttk

def download_playlist_gui(config: Config, playlist_url: str):
    root = tk.Tk()
    root.title("Track Downloader")
    treeview = ttk.Treeview()
    treeview.pack()
    root.mainloop()
