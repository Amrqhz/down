# this is just the basic code --Aug 21th 2025
import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')

from gi.repository import Gtk, Adw, GLib, Gio, GObject
import requests
import threading
import os
import urllib.parse
import json
from pathlib import Path

class DownloadItem(GObject.Object):
    def __init__(self, url, filename, download_path):
        super().__init__()
        self.url = url
        self.filename = filename
        self.download_path = download_path
        self.progress = 0.0
        self.status = "Waiting"
        self.size = 0
        self.downloaded = 0
        self.speed = 0
        self.cancelled = False

class DownloadRow(Gtk.Box):
    def __init__(self, download_item, on_cancel):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add_css_class("card")
        self.add_css_class("download-item")
        self.set_margin_top(6)
        self.set_margin_bottom(6)
        self.set_margin_start(12)
        self.set_margin_end(12)
        
        self.download_item = download_item
        self.on_cancel = on_cancel
        
        # Header with filename and cancel button
        header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        header.set_margin_top(12)
        header.set_margin_start(12)
        header.set_margin_end(12)
        
        self.filename_label = Gtk.Label(label=download_item.filename)
        self.filename_label.set_ellipsize(3)  # ELLIPSIZE_END
        self.filename_label.add_css_class("heading")
        self.filename_label.set_hexpand(True)
        self.filename_label.set_halign(Gtk.Align.START)
        
        self.cancel_button = Gtk.Button()
        self.cancel_button.set_icon_name("window-close-symbolic")
        self.cancel_button.add_css_class("flat")
        self.cancel_button.add_css_class("circular")
        self.cancel_button.connect("clicked", self._on_cancel_clicked)
        
        header.append(self.filename_label)
        header.append(self.cancel_button)
        
        # Progress bar
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_margin_start(12)
        self.progress_bar.set_margin_end(12)
        self.progress_bar.add_css_class("osd")
        
        # Status info
        status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        status_box.set_margin_bottom(12)
        status_box.set_margin_start(12)
        status_box.set_margin_end(12)
        
        self.status_label = Gtk.Label(label="Waiting...")
        self.status_label.add_css_class("dim-label")
        self.status_label.add_css_class("caption")
        self.status_label.set_hexpand(True)
        self.status_label.set_halign(Gtk.Align.START)
        
        self.size_label = Gtk.Label(label="")
        self.size_label.add_css_class("dim-label")
        self.size_label.add_css_class("caption")
        
        status_box.append(self.status_label)
        status_box.append(self.size_label)
        
        self.append(header)
        self.append(self.progress_bar)
        self.append(status_box)
    
    def _on_cancel_clicked(self, button):
        self.download_item.cancelled = True
        self.on_cancel(self.download_item)
    
    def update_progress(self):
        self.progress_bar.set_fraction(self.download_item.progress)
        self.status_label.set_text(self.download_item.status)
        
        if self.download_item.size > 0:
            size_text = f"{self._format_size(self.download_item.downloaded)} / {self._format_size(self.download_item.size)}"
            if self.download_item.speed > 0:
                size_text += f" • {self._format_size(self.download_item.speed)}/s"
            self.size_label.set_text(size_text)
    
    def _format_size(self, size):
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} TB"

class SettingsDialog(Adw.PreferencesWindow):
    def __init__(self, parent, current_path):
        super().__init__()
        self.set_transient_for(parent)
        self.set_modal(True)
        self.set_title("Settings")
        self.set_default_size(400, 300)
        
        # Download path preference
        page = Adw.PreferencesPage()
        page.set_title("General")
        
        group = Adw.PreferencesGroup()
        group.set_title("Download Location")
        
        self.path_row = Adw.ActionRow()
        self.path_row.set_title("Download Folder")
        self.path_row.set_subtitle(current_path)
        
        choose_button = Gtk.Button()
        choose_button.set_label("Choose")
        choose_button.add_css_class("flat")
        choose_button.connect("clicked", self._on_choose_folder)
        choose_button.set_valign(Gtk.Align.CENTER)
        
        self.path_row.add_suffix(choose_button)
        
        group.add(self.path_row)
        page.add(group)
        self.add(page)
        
        self.selected_path = current_path
    
    def _on_choose_folder(self, button):
        dialog = Gtk.FileChooserNative()
        dialog.set_title("Choose Download Folder")
        dialog.set_action(Gtk.FileChooserAction.SELECT_FOLDER)
        dialog.set_transient_for(self)
        dialog.connect("response", self._on_folder_selected)
        dialog.show()
    
    def _on_folder_selected(self, dialog, response):
        if response == Gtk.ResponseType.ACCEPT:
            folder = dialog.get_file()
            if folder:
                self.selected_path = folder.get_path()
                self.path_row.set_subtitle(self.selected_path)

class DownloadManager(Adw.ApplicationWindow):
    def __init__(self, app):
        super().__init__(application=app)
        self.set_title("Down")
        self.set_default_size(600, 400)
        
        # Load settings
        self.settings_file = Path.home() / ".config" / "down" / "settings.json"
        self.load_settings()
        
        # Active downloads
        self.downloads = []
        self.download_rows = {}
        
        # Setup UI
        self.setup_ui()
        
        self.setup_clipboard_monitor()
    
    def load_settings(self):
        self.settings_file.parent.mkdir(parents=True, exist_ok=True)
        try:
            if self.settings_file.exists():
                with open(self.settings_file, 'r') as f:
                    settings = json.load(f)
                    self.download_path = settings.get('download_path', str(Path.home() / "Downloads"))
            else:
                self.download_path = str(Path.home() / "Downloads")
        except:
            self.download_path = str(Path.home() / "Downloads")
    
    def save_settings(self):
        try:
            settings = {'download_path': self.download_path}
            with open(self.settings_file, 'w') as f:
                json.dump(settings, f)
        except:
            pass
    
    def setup_ui(self):
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        
        # Header bar 
        header = Adw.HeaderBar()
        
        # Add URL button
        add_button = Gtk.Button()
        add_button.set_icon_name("list-add-symbolic")
        add_button.add_css_class("flat")
        add_button.connect("clicked", self._on_add_download)
        add_button.set_tooltip_text("Add download")
        header.pack_start(add_button)
        
        # Settings button
        settings_button = Gtk.Button()
        settings_button.set_icon_name("preferences-system-symbolic")
        settings_button.add_css_class("flat")
        settings_button.connect("clicked", self._on_settings_clicked)
        settings_button.set_tooltip_text("Settings")
        header.pack_end(settings_button)
        
        main_box.append(header)
        
        # URL entry
        self.url_revealer = Gtk.Revealer()
        url_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        url_box.set_margin_top(12)
        url_box.set_margin_bottom(6)
        url_box.set_margin_start(12)
        url_box.set_margin_end(12)
        
        self.url_entry = Gtk.Entry()
        self.url_entry.set_placeholder_text("Paste download URL here...")
        self.url_entry.set_hexpand(True)
        self.url_entry.connect("activate", self._on_url_entered)
        
        download_button = Gtk.Button()
        download_button.set_label("Download")
        download_button.add_css_class("suggested-action")
        download_button.connect("clicked", self._on_url_entered)
        
        url_box.append(self.url_entry)
        url_box.append(download_button)
        self.url_revealer.set_child(url_box)
        
        # Scrolled window for downloads
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled.set_vexpand(True)
        
        self.downloads_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        scrolled.set_child(self.downloads_box)
        
        # Empty state
        self.empty_state = Adw.StatusPage()
        self.empty_state.set_icon_name("folder-download-symbolic")
        self.empty_state.set_title("No Downloads")
        self.empty_state.set_description("Click the + button or paste a URL to start downloading")
        # Stack to switch between empty state and downloads
        self.stack = Gtk.Stack()
        self.stack.add_named(self.empty_state, "empty")
        self.stack.add_named(scrolled, "downloads")
        self.stack.set_visible_child_name("empty")
        
        main_box.append(self.url_revealer)
        main_box.append(self.stack)
        
        self.set_content(main_box)
    
    def setup_clipboard_monitor(self):
        # Check clipboard every 10 seconds for URLs it maybe be cancelled in the future update
        def check_clipboard():
            clipboard = self.get_clipboard()
            clipboard.read_text_async(None, self._on_clipboard_read)
            return True
        
        GLib.timeout_add_seconds(10, check_clipboard)
        self.last_clipboard_url = ""
    
    def _on_clipboard_read(self, clipboard, result):
        try:
            text = clipboard.read_text_finish(result)
            if text and text != self.last_clipboard_url and self._is_valid_url(text.strip()):
                self.last_clipboard_url = text.strip()
                # Auto-start download from clipboard
                GLib.idle_add(self._start_download, text.strip())
        except:
            pass
    
    def _is_valid_url(self, url):
        try:
            result = urllib.parse.urlparse(url)
            return all([result.scheme, result.netloc]) and result.scheme in ('http', 'https', 'ftp')
        except:
            return False
    
    def _on_add_download(self, button):
        # Show/hide URL entry
        self.url_revealer.set_reveal_child(not self.url_revealer.get_reveal_child())
        if self.url_revealer.get_reveal_child():
            self.url_entry.grab_focus()
    
    def _on_url_entered(self, widget):
        url = self.url_entry.get_text().strip()
        if url and self._is_valid_url(url):
            self._start_download(url)
            self.url_entry.set_text("")
            self.url_revealer.set_reveal_child(False)
    
    def _start_download(self, url):
        # Extract filename from URL
        parsed_url = urllib.parse.urlparse(url)
        filename = os.path.basename(parsed_url.path)
        if not filename or '.' not in filename:
            filename = f"download_{len(self.downloads) + 1}"
        
        # Create download item
        download_item = DownloadItem(url, filename, self.download_path)
        self.downloads.append(download_item)
        
        # Create UI row
        download_row = DownloadRow(download_item, self._cancel_download)
        self.downloads_box.append(download_row)
        self.download_rows[download_item] = download_row
        
        # Show downloads view
        self.stack.set_visible_child_name("downloads")
        
        # Start download in thread
        threading.Thread(target=self._download_file, args=(download_item,), daemon=True).start()
    
    def _download_file(self, download_item):
        try:
            download_item.status = "Connecting..."
            GLib.idle_add(self._update_download_ui, download_item)
            
            response = requests.get(download_item.url, stream=True, timeout=30)
            response.raise_for_status()
            
            # Get file size
            download_item.size = int(response.headers.get('content-length', 0))
            
            # Create full file path
            file_path = os.path.join(download_item.download_path, download_item.filename)
            os.makedirs(download_item.download_path, exist_ok=True)
            
            # Handle file conflicts
            counter = 1
            original_path = file_path
            while os.path.exists(file_path):
                name, ext = os.path.splitext(original_path)
                file_path = f"{name} ({counter}){ext}"
                counter += 1
            
            download_item.status = "Downloading..."
            
            with open(file_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if download_item.cancelled:
                        f.close()
                        os.unlink(file_path)
                        return
                    
                    if chunk:
                        f.write(chunk)
                        download_item.downloaded += len(chunk)
                        
                        if download_item.size > 0:
                            download_item.progress = download_item.downloaded / download_item.size
                        
                        GLib.idle_add(self._update_download_ui, download_item)
            
            download_item.status = "Completed"
            download_item.progress = 1.0
            GLib.idle_add(self._update_download_ui, download_item)
            
        except Exception as e:
            download_item.status = f"Error: {str(e)}"
            GLib.idle_add(self._update_download_ui, download_item)
    
    def _update_download_ui(self, download_item):
        if download_item in self.download_rows:
            self.download_rows[download_item].update_progress()
    
    def _cancel_download(self, download_item):
        if download_item in self.download_rows:
            self.downloads_box.remove(self.download_rows[download_item])
            del self.download_rows[download_item]
        
        if download_item in self.downloads:
            self.downloads.remove(download_item)
        
        # Show empty state if no downloads
        if not self.downloads:
            self.stack.set_visible_child_name("empty")
    
    def _on_settings_clicked(self, button):
        dialog = SettingsDialog(self, self.download_path)
        dialog.connect("close-request", self._on_settings_closed, dialog)
        dialog.present()
    
    def _on_settings_closed(self, dialog, user_data):
        self.download_path = user_data.selected_path
        self.save_settings()

class DownloadManagerApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id="com.github.downloadmanager")
        self.window = None
    
    def do_activate(self):
        if not self.window:
            self.window = DownloadManager(self)
        self.window.present()

if __name__ == "__main__":
    app = DownloadManagerApp()
    app.run()
