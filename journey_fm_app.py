#!/usr/bin/env python3
"""
Journey FM Playlist Creator - Desktop Application

A cross-platform desktop application for automating Journey FM playlist updates.
Features system tray integration, log viewing, and easy setup.
"""

import sys
import os
import json
import logging
from datetime import datetime
from pathlib import Path

# GUI imports
try:
    from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QTextEdit, QLineEdit, QLabel, QHBoxLayout, QDialog, QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox, QInputDialog, QMessageBox, QProgressBar, QSystemTrayIcon, QMenu, QComboBox, QGroupBox, QFormLayout, QSpinBox, QTextBrowser, QTabWidget, QDialogButtonBox, QSplitter, QGridLayout
    from PySide6.QtCore import QTimer, Qt, QThread, Signal, QSettings, QUrl
    from PySide6.QtGui import QIcon, QDesktopServices, QFont, QAction
except Exception as gui_import_error:
    print("Failed to start GUI: required Qt/PySide6 dependencies are missing or not loadable.")
    print(f"Details: {gui_import_error}")
    print("On Linux, install graphics/runtime libs (for example: libgl1) and ensure PySide6 is installed.")
    print("Then run: pip install -r requirements.txt")
    sys.exit(1)

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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
                return config
            except Exception as e:
                logger.warning("Failed loading config file %s: %s", self.config_file, e)
        return {}

    def save_config(self, config):
        """Save config to QSettings and config.json"""
        # Save to QSettings
        for key, value in config.items():
            # Handle list values (convert to comma-separated string)
            if isinstance(value, list):
                value = ','.join(value)
            self.set(key, value)
        
        # Also save to config.json for main.py to use
        json_config = {}
        for key, value in config.items():
            if isinstance(value, list):
                json_config[key] = ','.join(value)
            else:
                json_config[key] = value
        
        try:
            with open(self.config_file, 'w') as f:
                json.dump(json_config, f, indent=2)
        except Exception as e:
            logger.error("Error saving config.json: %s", e)

def parse_bool(value):
    """Safely parse truthy values from QSettings/JSON."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    if isinstance(value, (int, float)):
        return value != 0
    return False

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
        help_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://plex.tv/claim")))
        token_layout.addWidget(help_button)
        
        form_layout.addRow("Plex Token:", token_layout)

        self.server_input = QLineEdit()
        self.server_input.setPlaceholderText("e.g., 192.168.1.100")
        form_layout.addRow("Server IP:", self.server_input)

        self.playlist_input = QLineEdit("Journey FM Recently Played")
        form_layout.addRow("Playlist Name:", self.playlist_input)

        form_group.setLayout(form_layout)
        layout.addWidget(form_group)

        # Station Selection
        station_group = QGroupBox("Station Selection")
        station_layout = QVBoxLayout()

        station_layout.addWidget(QLabel("Select which stations to monitor:"))
        self.journey_fm_checkbox = QCheckBox("Journey FM (myjourneyfm.com)")
        self.journey_fm_checkbox.setChecked(True)
        station_layout.addWidget(self.journey_fm_checkbox)

        self.spirit_fm_checkbox = QCheckBox("Spirit FM (spiritfm.com)")
        self.spirit_fm_checkbox.setChecked(True)
        station_layout.addWidget(self.spirit_fm_checkbox)

        station_group.setLayout(station_layout)
        layout.addWidget(station_group)

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
        buttons.accepted.connect(self.validate_and_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

        # Load existing config
        self.token_input.setText(config.get('PLEX_TOKEN', ''))
        self.server_input.setText(config.get('SERVER_IP', ''))
        self.playlist_input.setText(config.get('PLAYLIST_NAME', 'Journey FM Recently Played'))

        # Load station selections
        selected_stations = config.get('SELECTED_STATIONS', 'journey_fm,spirit_fm')
        if isinstance(selected_stations, str):
            selected_stations = selected_stations.split(',')
        elif isinstance(selected_stations, list):
            selected_stations = [str(station).strip() for station in selected_stations]
        else:
            selected_stations = ['journey_fm', 'spirit_fm']
        self.journey_fm_checkbox.setChecked('journey_fm' in selected_stations)
        self.spirit_fm_checkbox.setChecked('spirit_fm' in selected_stations)

    def get_config(self):
        selected_stations = []
        if self.journey_fm_checkbox.isChecked():
            selected_stations.append('journey_fm')
        if self.spirit_fm_checkbox.isChecked():
            selected_stations.append('spirit_fm')

        return {
            'PLEX_TOKEN': self.token_input.text().strip(),
            'SERVER_IP': self.server_input.text().strip(),
            'PLAYLIST_NAME': self.playlist_input.text().strip(),
            'AUTO_UPDATE': self.auto_update.isChecked(),
            'UPDATE_INTERVAL': self.interval_spin.value(),
            'UPDATE_UNIT': self.interval_unit.currentText(),
            'SELECTED_STATIONS': ','.join(selected_stations)
        }

    def validate_and_accept(self):
        """Validate configuration before accepting"""
        if not self.journey_fm_checkbox.isChecked() and not self.spirit_fm_checkbox.isChecked():
            QMessageBox.warning(self, "Validation Error",
                              "Please select at least one station to monitor.")
            return
        self.accept()

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
            from contextlib import redirect_stdout, redirect_stderr

            output_buffer = io.StringIO()
            with redirect_stdout(output_buffer), redirect_stderr(output_buffer):
                update_main()

            result = output_buffer.getvalue()
            if not result.strip():
                result = "Update completed."
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
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icon.png')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(800, 600)
        self.setMinimumSize(760, 520)

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

        # Buttons in grid layout
        button_layout = QGridLayout()
        
        # Row 1
        self.update_button = QPushButton("Update Playlist")
        self.update_button.clicked.connect(self.run_update_playlist)
        button_layout.addWidget(self.update_button, 0, 0)
        
        self.buy_list_button = QPushButton("Show Buy List")
        self.buy_list_button.clicked.connect(self.show_buy_list)
        button_layout.addWidget(self.buy_list_button, 0, 1)
        
        # Row 2
        self.history_button = QPushButton("View History")
        self.history_button.clicked.connect(self.show_history)
        button_layout.addWidget(self.history_button, 1, 0)
        
        self.export_button = QPushButton("Export Playlist")
        self.export_button.clicked.connect(self.export_playlist)
        button_layout.addWidget(self.export_button, 1, 1)
        
        # Row 3
        self.stats_button = QPushButton("Statistics")
        self.stats_button.clicked.connect(self.show_statistics)
        button_layout.addWidget(self.stats_button, 2, 0)
        
        self.analytics_button = QPushButton("Analytics")
        self.analytics_button.clicked.connect(self.show_analytics)
        button_layout.addWidget(self.analytics_button, 2, 1)
        
        status_layout.addLayout(button_layout)

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

    def run_update_playlist(self):
        """Run playlist update in background thread"""
        self.manual_update()

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
        auto_update = parse_bool(self.config.get('AUTO_UPDATE', False))
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

        self.update_button.setEnabled(False)
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
        self.update_button.setEnabled(True)
        self.last_update_label.setText(f"Last update: {datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')}")
        self.status_label.setText("Ready")

        # Append result to log file
        try:
            with open('playlist_log.txt', 'a', encoding='utf-8') as f:
                f.write(result + '\n')
        except Exception as e:
            logger.error("Error writing to log: %s", e)

        # Refresh logs
        self.log_viewer.refresh_logs()

        # Show result in status
        if "Error" in result:
            QMessageBox.warning(self, "Update Error", result)
        else:
            # Extract summary from result
            lines = result.strip().split('\n')
            summary_found = False
            for line in reversed(lines):
                if line.startswith("Added") or line.startswith("No new songs") or line.startswith("No matching"):
                    self.status_label.setText(line)
                    summary_found = True
                    break
            if not summary_found:
                self.status_label.setText("Update completed")

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
            logger.error("Error writing to log: %s", e)

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
            buy_list_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'amazon_buy_list.txt')
            with open(buy_list_path, 'r') as f:
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
            self.buy_list_label = QLabel(f"Found {len(songs)} songs to buy:")
            layout.addWidget(self.buy_list_label)
            self.populate_buy_list(songs)
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
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to show buy list dialog: {e}")

    def populate_buy_list(self, songs):
        """Populate the buy list widget"""
        self.buy_list_widget.clear()
        self.buy_list_label.setText(f"Found {len(songs)} songs to buy:")
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
                QDesktopServices.openUrl(QUrl(url))

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
        try:
            with open('amazon_buy_list.txt', 'w') as f:
                f.write("Songs not in your library - Amazon search links:\n\n")
                for artist_title, url in updated_songs:
                    f.write(f"{artist_title}\n{url}\n\n")
        except Exception as e:
            QMessageBox.warning(dialog, "Error", f"Failed to update buy list file: {e}")
            return

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

    def show_analytics(self):
        """Show analytics dashboard with charts"""
        import sqlite3
        import json
        from datetime import datetime
        from collections import Counter
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.figure import Figure

        dialog = QDialog(self)
        dialog.setWindowTitle("Playlist Analytics")
        dialog.setModal(True)
        dialog.resize(1000, 700)

        layout = QVBoxLayout()

        tab_widget = QTabWidget()

        try:
            conn = sqlite3.connect('playlist_history.db')
            c = conn.cursor()
            c.execute('SELECT date, added_songs, missing_songs FROM history ORDER BY date')
            rows = c.fetchall()
            conn.close()

            # Prepare data
            dates = []
            cumulative_added = 0
            cumulative_list = []
            artist_counter = Counter()
            update_freq = []

            for date, added_json, missing_json in rows:
                dt = datetime.fromisoformat(date)
                dates.append(dt.strftime('%Y-%m-%d'))
                
                added_songs = json.loads(added_json) if added_json else []
                cumulative_added += len(added_songs)
                cumulative_list.append(cumulative_added)
                update_freq.append(len(added_songs))
                
                for song in added_songs:
                    # Parse artist from "Title by Artist"
                    if " by " in song:
                        artist = song.split(" by ", 1)[1]
                        artist_counter[artist] += 1

            # Tab 1: Playlist Growth
            growth_tab = QWidget()
            growth_layout = QVBoxLayout()
            fig1 = Figure(figsize=(8, 6))
            ax1 = fig1.add_subplot(111)
            ax1.plot(dates, cumulative_list, marker='o')
            ax1.set_title('Playlist Growth Over Time')
            ax1.set_xlabel('Date')
            ax1.set_ylabel('Total Songs')
            ax1.tick_params(axis='x', rotation=45)
            canvas1 = FigureCanvas(fig1)
            growth_layout.addWidget(canvas1)
            growth_tab.setLayout(growth_layout)
            tab_widget.addTab(growth_tab, "Growth")

            # Tab 2: Top Artists
            artists_tab = QWidget()
            artists_layout = QVBoxLayout()
            fig2 = Figure(figsize=(8, 6))
            ax2 = fig2.add_subplot(111)
            top_artists = artist_counter.most_common(10)
            if top_artists:
                artists, counts = zip(*top_artists)
                ax2.bar(artists, counts)
                ax2.set_title('Top 10 Artists')
                ax2.set_xlabel('Artist')
                ax2.set_ylabel('Songs Added')
                ax2.tick_params(axis='x', rotation=45)
            canvas2 = FigureCanvas(fig2)
            artists_layout.addWidget(canvas2)
            artists_tab.setLayout(artists_layout)
            tab_widget.addTab(artists_tab, "Top Artists")

            # Tab 3: Update Frequency
            freq_tab = QWidget()
            freq_layout = QVBoxLayout()
            fig3 = Figure(figsize=(8, 6))
            ax3 = fig3.add_subplot(111)
            ax3.bar(dates, update_freq)
            ax3.set_title('Songs Added per Update')
            ax3.set_xlabel('Date')
            ax3.set_ylabel('Songs Added')
            ax3.tick_params(axis='x', rotation=45)
            canvas3 = FigureCanvas(fig3)
            freq_layout.addWidget(canvas3)
            freq_tab.setLayout(freq_layout)
            tab_widget.addTab(freq_tab, "Update Frequency")

        except Exception as e:
            error_tab = QWidget()
            error_layout = QVBoxLayout()
            error_layout.addWidget(QLabel(f"Error loading analytics: {str(e)}"))
            error_tab.setLayout(error_layout)
            tab_widget.addTab(error_tab, "Error")

        layout.addWidget(tab_widget)

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
        table.setHorizontalHeaderLabels(["Date", "Type", "Artist", "Song"])
        table.setWordWrap(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)

        try:
            conn = sqlite3.connect('playlist_history.db')
            c = conn.cursor()
            c.execute('SELECT date, added_songs, missing_songs FROM history ORDER BY date DESC')
            rows = c.fetchall()
            conn.close()

            # Collect all entries
            entries = []
            for date, added_songs_json, missing_songs_json in rows:
                try:
                    dt = datetime.fromisoformat(date)
                    date_str = dt.strftime('%Y-%m-%d %H:%M')
                except Exception:
                    date_str = date

                # Added songs
                try:
                    added_songs = json.loads(added_songs_json)
                    for song in added_songs:
                        # Format is "Title by Artist"
                        if " by " in song:
                            title, artist = song.split(" by ", 1)
                        else:
                            title = song
                            artist = "Unknown"
                        entries.append((date_str, "Added", artist, title))
                except Exception:
                    pass

                # Missing songs
                try:
                    missing_songs = json.loads(missing_songs_json)
                    for song in missing_songs:
                        artist = song.get('artist', 'Unknown')
                        title = song.get('title', 'Unknown')
                        entries.append((date_str, "Missing", artist, title))
                except Exception:
                    pass

            table.setRowCount(len(entries))
            for row_idx, (date_str, type_str, artist, song) in enumerate(entries):
                table.setItem(row_idx, 0, QTableWidgetItem(date_str))
                table.setItem(row_idx, 1, QTableWidgetItem(type_str))
                table.setItem(row_idx, 2, QTableWidgetItem(artist))
                table.setItem(row_idx, 3, QTableWidgetItem(song))

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
            except Exception:
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
        self.tray_icon = None
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
        show_action.triggered.connect(self.show_main_window)
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

    def show_main_window(self):
        """Restore and focus the main window."""
        self.main_window.show()
        self.main_window.setWindowState(
            self.main_window.windowState() & ~Qt.WindowState.WindowMinimized
        )
        self.main_window.raise_()
        self.main_window.activateWindow()

    def tray_activated(self, reason):
        """Handle tray icon activation"""
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_main_window()

    def run(self):
        """Run the application"""
        return self.app.exec()

def main():
    """Main application entry point"""
    with open('app_log.txt', 'a') as log:
        log.write(f"{datetime.now()}: Starting Journey FM Playlist app...\n")
    print("Starting Journey FM Playlist app...")
    try:
        has_x11 = bool(os.environ.get('DISPLAY'))
        has_wayland = bool(os.environ.get('WAYLAND_DISPLAY'))
        if os.name != 'nt' and not (has_x11 or has_wayland):
            raise Exception("No graphical display detected (DISPLAY/WAYLAND_DISPLAY not set)")
        
        print("Initializing GUI...")
        with open('app_log.txt', 'a') as log:
            log.write(f"{datetime.now()}: DISPLAY set, initializing GUI\n")
        # Set up high DPI scaling
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )

        # Create and run application
        tray_app = SystemTrayApp()
        print("App initialized, starting event loop...")
        with open('app_log.txt', 'a') as log:
            log.write(f"{datetime.now()}: App initialized, starting event loop\n")
        sys.exit(tray_app.run())
    except Exception as e:
        error_msg = f"Failed to start GUI application: {e}"
        print(error_msg)
        print("Make sure you have a graphical display available (X11/Wayland) and DISPLAY environment variable is set.")
        print("If running remotely, use X forwarding or a VNC session.")
        with open('app_log.txt', 'a') as log:
            log.write(f"{datetime.now()}: {error_msg}\n")
        sys.exit(1)

if __name__ == "__main__":
    main()