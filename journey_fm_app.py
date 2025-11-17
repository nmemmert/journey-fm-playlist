#!/usr/bin/env python3
"""
Journey FM Playlist Creator - Desktop Application

A cross-platform desktop application for automating Journey FM playlist updates.
Features system tray integration, log viewing, and easy setup.
"""

import sys
import os
import json
import threading
import time
from datetime import datetime
from pathlib import Path

# GUI imports
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QLineEdit, QFormLayout,
    QDialog, QDialogButtonBox, QSystemTrayIcon, QMenu,
    QGroupBox, QCheckBox, QSpinBox, QComboBox, QMessageBox,
    QProgressBar, QSplitter, QFrame, QScrollArea, QTextBrowser, QTableWidget, QTableWidgetItem, QHeaderView, QListWidget, QListWidgetItem
)
from PySide6.QtCore import (
    Qt, QTimer, QThread, Signal, QSettings, QSize
)
from PySide6.QtGui import (
    QIcon, QAction, QFont, QPixmap, QPainter, QColor, QDesktopServices
)

# Import our existing functionality
from main import scrape_recently_played, create_playlist_in_plex, PLEX_TOKEN, SERVER_IP, PLAYLIST_NAME

class Config:
    """Configuration management"""
    def __init__(self):
        self.settings = QSettings('JourneyFM', 'PlaylistCreator')
        self.config_file = Path('config.json')

    def get(self, key, default=None):
        return self.settings.value(key, default)

    def set(self, key, value):
        self.settings.setValue(key, value)
        self.settings.sync()

    def load_config(self):
        """Load config from JSON file for backward compatibility"""
        if self.config_file.exists():
            try:
                with open(self.config_file, 'r') as f:
                    config = json.load(f)
                # Migrate to QSettings
                for key, value in config.items():
                    self.set(key, value)
                # Remove old file
                self.config_file.unlink()
                return config
            except:
                pass
        return {}

    def save_config(self, config):
        """Save config to QSettings"""
        for key, value in config.items():
            self.set(key, value)

class SetupWizard(QDialog):
    """Setup wizard for initial configuration"""
    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.setWindowTitle("Journey FM Setup")
        self.setModal(True)
        self.resize(500, 400)

        layout = QVBoxLayout()

        # Welcome message
        welcome = QLabel("Welcome to Journey FM Playlist Creator!")
        welcome.setFont(QFont("Arial", 14, QFont.Weight.Bold))
        layout.addWidget(welcome)

        desc = QLabel("This wizard will help you set up automatic playlist updates from Journey FM.")
        desc.setWordWrap(True)
        layout.addWidget(desc)

        # Configuration form
        form_group = QGroupBox("Plex Configuration")
        form_layout = QFormLayout()

        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("Get this from https://plex.tv/claim")
        
        # Token input with help button
        token_layout = QHBoxLayout()
        token_layout.addWidget(self.token_input)
        help_button = QPushButton("?")
        help_button.setMaximumWidth(30)
        help_button.setToolTip("Click to open Plex token page")
        help_button.clicked.connect(lambda: QDesktopServices.openUrl("https://plex.tv/claim"))
        token_layout.addWidget(help_button)
        
        form_layout.addRow("Plex Token:", token_layout)

        self.server_input = QLineEdit()
        self.server_input.setPlaceholderText("e.g., 192.168.1.100")
        form_layout.addRow("Server IP:", self.server_input)

        self.playlist_input = QLineEdit("Journey FM Recently Played")
        form_layout.addRow("Playlist Name:", self.playlist_input)

        form_group.setLayout(form_layout)
        layout.addWidget(form_group)

        # Scheduling options
        sched_group = QGroupBox("Scheduling")
        sched_layout = QVBoxLayout()

        self.auto_update = QCheckBox("Enable automatic updates")
        self.auto_update.setChecked(True)
        sched_layout.addWidget(self.auto_update)

        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("Update every"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setValue(15)
        self.interval_spin.setRange(5, 120)
        interval_layout.addWidget(self.interval_spin)
        self.interval_unit = QComboBox()
        self.interval_unit.addItems(["Minutes", "Hours"])
        interval_layout.addWidget(self.interval_unit)
        interval_layout.addStretch()
        sched_layout.addLayout(interval_layout)

        sched_group.setLayout(sched_layout)
        layout.addWidget(sched_group)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

        # Load existing config
        self.token_input.setText(config.get('PLEX_TOKEN', ''))
        self.server_input.setText(config.get('SERVER_IP', ''))
        self.playlist_input.setText(config.get('PLAYLIST_NAME', 'Journey FM Recently Played'))

    def get_config(self):
        return {
            'PLEX_TOKEN': self.token_input.text().strip(),
            'SERVER_IP': self.server_input.text().strip(),
            'PLAYLIST_NAME': self.playlist_input.text().strip(),
            'AUTO_UPDATE': self.auto_update.isChecked(),
            'UPDATE_INTERVAL': self.interval_spin.value(),
            'UPDATE_UNIT': self.interval_unit.currentText()
        }

class LogViewer(QWidget):
    """Widget for viewing application logs"""
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout()

        # Header
        header = QHBoxLayout()
        header.addWidget(QLabel("Application Logs"))
        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(self.clear_logs)
        header.addWidget(clear_btn)
        header.addStretch()
        layout.addLayout(header)

        # Log text area
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 9))
        layout.addWidget(self.log_text)

        # Load existing logs
        self.load_logs()

        self.setLayout(layout)

    def load_logs(self):
        """Load logs from file"""
        log_file = Path('playlist_log.txt')
        if log_file.exists():
            try:
                with open(log_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    self.log_text.setPlainText(content)
                    # Scroll to bottom
                    cursor = self.log_text.textCursor()
                    cursor.movePosition(cursor.MoveOperation.End)
                    self.log_text.setTextCursor(cursor)
            except Exception as e:
                self.log_text.setPlainText(f"Error loading logs: {e}")

    def clear_logs(self):
        """Clear the log file"""
        try:
            with open('playlist_log.txt', 'w', encoding='utf-8') as f:
                f.write("")
            self.log_text.clear()
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to clear logs: {e}")

    def refresh_logs(self):
        """Refresh the log display"""
        self.load_logs()

class UpdateWorker(QThread):
    """Worker thread for running playlist updates"""
    finished = Signal(str)
    progress = Signal(str)

    def run(self):
        try:
            self.progress.emit("Starting playlist update...")

            # Import here to avoid circular imports
            from main import main as update_main

            # Capture output by redirecting stdout
            import io
            from contextlib import redirect_stdout

            output_buffer = io.StringIO()
            with redirect_stdout(output_buffer):
                update_main()

            result = output_buffer.getvalue()
            self.finished.emit(result)

        except Exception as e:
            self.finished.emit(f"Error: {str(e)}")

class MainWindow(QMainWindow):
    """Main application window"""
    def __init__(self):
        super().__init__()
        self.tray_icon = None  # Will be set later
        self.config = Config()
        self.config.load_config()

        self.setWindowTitle("Journey FM Playlist Creator")
        self.setWindowIcon(QIcon("icon.png"))  # You'll need to add an icon
        self.resize(800, 600)

        # Create central widget
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # Toolbar
        toolbar = self.addToolBar("Main")
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        update_action = QAction("Update Now", self)
        update_action.triggered.connect(self.manual_update)
        toolbar.addAction(update_action)

        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self.show_settings)
        toolbar.addAction(settings_action)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        # Splitter for main content
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Status section
        status_group = QGroupBox("Status")
        status_layout = QVBoxLayout()

        self.status_label = QLabel("Ready")
        status_layout.addWidget(self.status_label)

        self.last_update_label = QLabel("Last update: Never")
        status_layout.addWidget(self.last_update_label)

        # Buy list button
        self.buy_list_button = QPushButton("Show Buy List")
        self.buy_list_button.clicked.connect(self.show_buy_list)
        status_layout.addWidget(self.buy_list_button)

        # History button
        self.history_button = QPushButton("View History")
        self.history_button.clicked.connect(self.show_history)
        status_layout.addWidget(self.history_button)

        # Export button
        self.export_button = QPushButton("Export Playlist")
        self.export_button.clicked.connect(self.export_playlist)
        status_layout.addWidget(self.export_button)

        # Statistics button
        self.stats_button = QPushButton("Statistics")
        self.stats_button.clicked.connect(self.show_statistics)
        status_layout.addWidget(self.stats_button)

        status_group.setLayout(status_layout)
        splitter.addWidget(status_group)

        # Log viewer
        self.log_viewer = LogViewer()
        splitter.addWidget(self.log_viewer)

        splitter.setSizes([100, 400])
        layout.addWidget(splitter)

        # Setup timer for automatic updates
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.auto_update)

        # Load settings and start auto-update if enabled
        self.load_settings()

        # Check if first run
        if not self.config.get('PLEX_TOKEN'):
            self.show_setup_wizard()

    def set_tray_icon(self, tray_icon):
        """Set the tray icon reference"""
        self.tray_icon = tray_icon

    def show_setup_wizard(self):
        """Show the setup wizard"""
        wizard = SetupWizard(self.config, self)
        if wizard.exec() == QDialog.DialogCode.Accepted:
            config = wizard.get_config()
            self.config.save_config(config)
            self.load_settings()
            QMessageBox.information(self, "Setup Complete",
                                  "Configuration saved! The app will now update your playlist automatically.")

    def load_settings(self):
        """Load settings and configure auto-update"""
        auto_update = self.config.get('AUTO_UPDATE', False)
        if auto_update:
            interval = int(self.config.get('UPDATE_INTERVAL', 15))
            unit = self.config.get('UPDATE_UNIT', 'Minutes')

            # Convert to milliseconds
            if unit == 'Hours':
                interval_ms = interval * 60 * 60 * 1000
            else:
                interval_ms = interval * 60 * 1000

            self.update_timer.start(interval_ms)
            self.status_label.setText(f"Auto-update enabled (every {interval} {unit.lower()})")
        else:
            self.update_timer.stop()
            self.status_label.setText("Auto-update disabled")

    def manual_update(self):
        """Manually trigger playlist update"""
        if hasattr(self, 'worker') and self.worker.isRunning():
            QMessageBox.information(self, "Update in Progress",
                                  "An update is already running. Please wait.")
            return

        self.worker = UpdateWorker()
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.update_finished)
        self.worker.start()

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        self.status_label.setText("Updating playlist...")

    def update_progress(self, message):
        """Update progress display"""
        self.status_label.setText(message)

    def update_finished(self, result):
        """Handle update completion"""
        self.progress_bar.setVisible(False)
        self.last_update_label.setText(f"Last update: {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}")
        self.status_label.setText("Ready")

        # Append result to log file
        try:
            with open('playlist_log.txt', 'a', encoding='utf-8') as f:
                f.write(result + '\n')
        except Exception as e:
            print(f"Error writing to log: {e}")

        # Refresh logs
        self.log_viewer.refresh_logs()

        # Show result in status
        if "Error" in result:
            QMessageBox.warning(self, "Update Error", result)
        else:
            # Extract summary from result
            lines = result.strip().split('\n')
            for line in reversed(lines):
                if line.startswith("Added") or line.startswith("No new songs") or line.startswith("No matching"):
                    self.status_label.setText(line)
                    break

    def auto_update(self):
        """Automatic update (runs in background)"""
        if hasattr(self, 'worker') and self.worker.isRunning():
            return  # Skip if already running

        self.worker = UpdateWorker()
        self.worker.finished.connect(self.auto_update_finished)
        self.worker.start()

    def auto_update_finished(self, result):
        """Handle automatic update completion"""
        self.last_update_label.setText(f"Last update: {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}")

        # Append result to log file
        try:
            with open('playlist_log.txt', 'a', encoding='utf-8') as f:
                f.write(result + '\n')
        except Exception as e:
            print(f"Error writing to log: {e}")

        # Refresh logs
        self.log_viewer.refresh_logs()

        # Show tray notification if minimized
        if self.isMinimized() or not self.isVisible():
            if self.tray_icon:
                self.tray_icon.showMessage(
                    "Journey FM Update",
                    "Playlist updated successfully",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000
                )

    def show_settings(self):
        """Show settings dialog"""
        wizard = SetupWizard(self.config, self)
        if wizard.exec() == QDialog.DialogCode.Accepted:
            config = wizard.get_config()
            self.config.save_config(config)
            self.load_settings()
            QMessageBox.information(self, "Settings Saved", "Configuration updated successfully!")

    def show_buy_list(self):
        """Show the Amazon buy list dialog with interactive features"""
        try:
            with open('amazon_buy_list.txt', 'r') as f:
                content = f.read()
        except FileNotFoundError:
            QMessageBox.information(self, "No Buy List", "No buy list available. Run an update to generate the list.")
            return
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to read buy list file: {e}")
            return

        try:
            # Parse content to get songs
            lines = content.split('\n')
            songs = []
            i = 0
            while i < len(lines):
                if lines[i].startswith('Songs not in your library'):
                    i += 2  # Skip header
                    continue
                if lines[i].strip() and not lines[i].startswith('http'):
                    artist_title = lines[i].strip()
                    if i + 1 < len(lines) and lines[i + 1].startswith('http'):
                        url = lines[i + 1].strip()
                        songs.append((artist_title, url))
                        i += 3  # Skip blank line
                    else:
                        i += 1
                else:
                    i += 1

            dialog = QDialog(self)
            dialog.setWindowTitle("Amazon Buy List")
            dialog.setModal(True)
            dialog.resize(600, 400)

            layout = QVBoxLayout()

            # Search box
            search_layout = QHBoxLayout()
            search_layout.addWidget(QLabel("Search:"))
            self.search_input = QLineEdit()
            self.search_input.textChanged.connect(lambda: self.filter_buy_list(songs))
            search_layout.addWidget(self.search_input)
            layout.addLayout(search_layout)

            # List widget
            self.buy_list_widget = QListWidget()
            self.populate_buy_list(songs)
            layout.addWidget(QLabel(f"Found {len(songs)} songs to buy:"))
            layout.addWidget(self.buy_list_widget)

            # Buttons
            button_layout = QHBoxLayout()
            open_button = QPushButton("Open Selected")
            open_button.clicked.connect(self.open_selected_buy_items)
            button_layout.addWidget(open_button)

            remove_button = QPushButton("Remove Selected")
            remove_button.clicked.connect(lambda: self.remove_selected_buy_items(songs, dialog))
            button_layout.addWidget(remove_button)

            close_button = QPushButton("Close")
            close_button.clicked.connect(dialog.close)
            button_layout.addWidget(close_button)

            layout.addLayout(button_layout)

            dialog.setLayout(layout)
            dialog.show()
            dialog.raise_()
            dialog.activateWindow()
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to show buy list dialog: {e}")

    def populate_buy_list(self, songs):
        """Populate the buy list widget"""
        self.buy_list_widget.clear()
        for artist_title, url in songs:
            item = QListWidgetItem(artist_title)
            item.setData(1, url)  # Store URL in item data
            item.setCheckState(Qt.CheckState.Unchecked)
            self.buy_list_widget.addItem(item)

    def filter_buy_list(self, all_songs):
        """Filter the buy list based on search text"""
        search_text = self.search_input.text().lower()
        filtered = [(at, url) for at, url in all_songs if search_text in at.lower()]
        self.populate_buy_list(filtered)

    def open_selected_buy_items(self):
        """Open selected buy list items in browser"""
        for i in range(self.buy_list_widget.count()):
            item = self.buy_list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                url = item.data(1)
                QDesktopServices.openUrl(url)

    def remove_selected_buy_items(self, all_songs, dialog):
        """Remove selected items from buy list"""
        to_remove = []
        for i in range(self.buy_list_widget.count()):
            item = self.buy_list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                artist_title = item.text()
                to_remove.append(artist_title)

        if not to_remove:
            QMessageBox.information(dialog, "No Selection", "Please select items to remove.")
            return

        # Confirm
        reply = QMessageBox.question(dialog, "Confirm Removal", 
                                   f"Remove {len(to_remove)} selected items from buy list?",
                                   QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        # Remove from all_songs
        updated_songs = [(at, url) for at, url in all_songs if at not in to_remove]

        # Rewrite file
        with open('amazon_buy_list.txt', 'w') as f:
            f.write("Songs not in your library - Amazon search links:\n\n")
            for artist_title, url in updated_songs:
                f.write(f"{artist_title}\n{url}\n\n")

        # Update display
        self.populate_buy_list(updated_songs)
        QMessageBox.information(dialog, "Removed", f"Removed {len(to_remove)} items from buy list.")

    def show_statistics(self):
        """Show statistics dashboard"""
        import sqlite3
        import json

        dialog = QDialog(self)
        dialog.setWindowTitle("Statistics Dashboard")
        dialog.setModal(True)
        dialog.resize(400, 300)

        layout = QVBoxLayout()

        try:
            conn = sqlite3.connect('playlist_history.db')
            c = conn.cursor()
            c.execute('SELECT COUNT(*), SUM(added_count), SUM(missing_count) FROM history')
            result = c.fetchone()
            conn.close()

            total_updates = result[0] or 0
            total_added = result[1] or 0
            total_missing = result[2] or 0

            layout.addWidget(QLabel(f"Total Updates: {total_updates}"))
            layout.addWidget(QLabel(f"Total Songs Added to Plex: {total_added}"))
            layout.addWidget(QLabel(f"Total Songs in Buy List: {total_missing}"))

            if total_updates > 0:
                avg_added = total_added / total_updates
                avg_missing = total_missing / total_updates
                layout.addWidget(QLabel(f"Average Songs Added per Update: {avg_added:.1f}"))
                layout.addWidget(QLabel(f"Average Missing Songs per Update: {avg_missing:.1f}"))

        except Exception as e:
            layout.addWidget(QLabel(f"Error loading statistics: {str(e)}"))

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.close)
        layout.addWidget(buttons)

        dialog.setLayout(layout)
        dialog.exec()

    def show_history(self):
        """Show the playlist history dialog"""
        import sqlite3
        import json
        from datetime import datetime

        dialog = QDialog(self)
        dialog.setWindowTitle("Playlist History")
        dialog.setModal(True)
        dialog.resize(800, 600)

        layout = QVBoxLayout()

        table = QTableWidget()
        table.setColumnCount(4)
        table.setHorizontalHeaderLabels(["Date", "Added Songs", "Missing Songs", "Details"])
        table.horizontalHeader().setStretchLastSection(True)

        try:
            conn = sqlite3.connect('playlist_history.db')
            c = conn.cursor()
            c.execute('SELECT date, added_count, added_songs, missing_count, missing_songs FROM history ORDER BY date DESC')
            rows = c.fetchall()
            conn.close()

            table.setRowCount(len(rows))
            for row_idx, (date, added_count, added_songs_json, missing_count, missing_songs_json) in enumerate(rows):
                # Parse date
                try:
                    dt = datetime.fromisoformat(date)
                    date_str = dt.strftime('%Y-%m-%d %H:%M')
                except:
                    date_str = date

                # Added songs
                try:
                    added_songs = json.loads(added_songs_json)
                    added_text = f"{added_count} songs\n" + "\n".join(added_songs[:3])  # Show first 3
                    if len(added_songs) > 3:
                        added_text += f"\n... and {len(added_songs)-3} more"
                except:
                    added_text = f"{added_count} songs"

                # Missing songs
                try:
                    missing_songs = json.loads(missing_songs_json)
                    missing_text = f"{missing_count} songs\n" + "\n".join([f"{s['artist']} - {s['title']}" for s in missing_songs[:3]])
                    if len(missing_songs) > 3:
                        missing_text += f"\n... and {len(missing_songs)-3} more"
                except:
                    missing_text = f"{missing_count} songs"

                table.setItem(row_idx, 0, QTableWidgetItem(date_str))
                table.setItem(row_idx, 1, QTableWidgetItem(added_text))
                table.setItem(row_idx, 2, QTableWidgetItem(missing_text))
                table.setItem(row_idx, 3, QTableWidgetItem(f"Added: {added_count}, Missing: {missing_count}"))

        except Exception as e:
            table.setRowCount(1)
            table.setItem(0, 0, QTableWidgetItem("Error loading history"))
            table.setItem(0, 1, QTableWidgetItem(str(e)))

        layout.addWidget(table)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dialog.close)
        layout.addWidget(buttons)

        dialog.setLayout(layout)
        dialog.exec()

    def export_playlist(self):
        """Export the current Plex playlist to CSV"""
        try:
            # Get config
            plex_token = self.config.get('PLEX_TOKEN')
            server_ip = self.config.get('SERVER_IP')
            playlist_name = self.config.get('PLAYLIST_NAME', 'Journey FM Recently Played')

            if not plex_token or not server_ip:
                QMessageBox.warning(self, "Configuration Error", "Plex token and server IP are required. Please check settings.")
                return

            # Connect to Plex
            from plexapi.myplex import MyPlexAccount
            account = MyPlexAccount(token=plex_token)
            resources = account.resources()
            server_resource = None
            for r in resources:
                for conn in r.connections:
                    if server_ip in conn.address:
                        server_resource = r
                        break
                if server_resource:
                    break

            if not server_resource:
                QMessageBox.warning(self, "Connection Error", f"Server at {server_ip} not found.")
                return

            plex = server_resource.connect()

            # Get playlist
            try:
                playlist = plex.playlist(playlist_name)
                tracks = playlist.items()
            except:
                QMessageBox.warning(self, "Playlist Error", f"Playlist '{playlist_name}' not found.")
                return

            # Export to CSV
            import csv
            with open('playlist_export.csv', 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(['Title', 'Artist', 'Album'])
                for track in tracks:
                    writer.writerow([
                        track.title,
                        track.artist().title if track.artist() else '',
                        track.album().title if track.album() else ''
                    ])

            QMessageBox.information(self, "Export Complete", f"Playlist exported to playlist_export.csv ({len(tracks)} songs)")

        except Exception as e:
            QMessageBox.critical(self, "Export Error", f"Failed to export playlist: {str(e)}")

    def closeEvent(self, event):
        """Handle window close - minimize to tray instead of closing"""
        if self.tray_icon and self.tray_icon.isVisible():
            self.hide()
            self.tray_icon.showMessage(
                "Journey FM",
                "Application minimized to system tray",
                QSystemTrayIcon.MessageIcon.Information,
                2000
            )
            event.ignore()
        else:
            event.accept()

class SystemTrayApp:
    """System tray application wrapper"""
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.app.setApplicationName("Journey FM Playlist Creator")
        self.app.setApplicationVersion("1.0")
        self.app.setOrganizationName("JourneyFM")

        # Create main window first
        self.main_window = MainWindow()

        # Create system tray
        self.create_tray_icon()

        # Set tray icon reference in main window
        self.main_window.set_tray_icon(self.tray_icon)

        # Show window initially
        self.main_window.show()

    def create_tray_icon(self):
        """Create system tray icon"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            QMessageBox.critical(None, "System Tray",
                               "System tray not available on this system")
            return

        self.tray_icon = QSystemTrayIcon(self.main_window)
        self.tray_icon.setIcon(self.main_window.windowIcon())

        # Create tray menu
        tray_menu = QMenu()

        show_action = QAction("Show", self.main_window)
        show_action.triggered.connect(self.main_window.show)
        tray_menu.addAction(show_action)

        update_action = QAction("Update Now", self.main_window)
        update_action.triggered.connect(self.main_window.manual_update)
        tray_menu.addAction(update_action)

        tray_menu.addSeparator()

        quit_action = QAction("Quit", self.main_window)
        quit_action.triggered.connect(self.app.quit)
        tray_menu.addAction(quit_action)

        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.activated.connect(self.tray_activated)

        self.tray_icon.show()

    def tray_activated(self, reason):
        """Handle tray icon activation"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.main_window.show()
            self.main_window.raise_()
            self.main_window.activateWindow()

    def run(self):
        """Run the application"""
        return self.app.exec()

def main():
    """Main application entry point"""
    # Set up high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # Create and run application
    tray_app = SystemTrayApp()
    sys.exit(tray_app.run())

if __name__ == "__main__":
    main()