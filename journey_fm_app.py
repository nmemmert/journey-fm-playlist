#!/usr/bin/env python3
"""
Journey FM Playlist Creator - Desktop Application

A cross-platform desktop application for automating Journey FM playlist updates.
Features system tray integration, log viewing, and easy setup.
"""

import sys
import os
import logging
from datetime import datetime
from pathlib import Path

from journeyfm.config_store import load_runtime_config, save_runtime_config
from journeyfm.plex_service import PlexConnectionError, fetch_playlists, validate_playlist_target
from journeyfm.update_service import format_result_summary, run_update_job

# GUI imports
try:
    from PySide6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QPushButton, QTextEdit, QLineEdit, QLabel, QHBoxLayout, QDialog, QListWidget, QListWidgetItem, QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox, QInputDialog, QMessageBox, QProgressBar, QSystemTrayIcon, QMenu, QComboBox, QGroupBox, QFormLayout, QSpinBox, QTextBrowser, QTabWidget, QDialogButtonBox, QSplitter, QGridLayout
    from PySide6.QtCore import QTimer, Qt, QThread, Signal, QSettings, QUrl
    from PySide6.QtGui import QIcon, QDesktopServices, QFont, QFontDatabase, QAction
except Exception as gui_import_error:
    print("Failed to start GUI: required Qt/PySide6 dependencies are missing or not loadable.")
    print(f"Details: {gui_import_error}")
    print("On Linux, install graphics/runtime libs (for example: libgl1) and ensure PySide6 is installed.")
    print("Then run: pip install -r requirements.txt")
    sys.exit(1)

def configure_logging():
    """Configure logging with safe handlers for pythonw/GUI environments."""
    log_format = '%(asctime)s - %(levelname)s - %(message)s'
    handlers = []

    try:
        handlers.append(logging.FileHandler('app_log.txt', encoding='utf-8'))
    except Exception:
        pass

    stream = getattr(sys, 'stderr', None) or getattr(sys, 'stdout', None)
    if stream is not None:
        handlers.append(logging.StreamHandler(stream))

    logging.basicConfig(level=logging.INFO, format=log_format, handlers=handlers, force=True)
    for noisy_logger in ('webdriver_manager', 'WDM', 'matplotlib', 'urllib3', 'plexapi'):
        logging.getLogger(noisy_logger).setLevel(logging.WARNING)


configure_logging()
logger = logging.getLogger(__name__)

class Config:
    """Configuration management"""
    def __init__(self):
        self.config_file = Path('config.json')
        self._cache = {}

    def get(self, key, default=None):
        return self._cache.get(key, default)

    def set(self, key, value):
        self._cache[key] = value

    def load_config(self):
        """Load config using shared runtime config rules."""
        self._cache = load_runtime_config(self.config_file)
        return dict(self._cache)

    def save_config(self, config):
        """Save config with secrets stored outside config.json when possible."""
        save_runtime_config(config, self.config_file)
        self.load_config()

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
        self.playlist_records = []
        self.connection_validated = False
        self.setWindowTitle("Journey FM Setup")
        self.setModal(True)
        self.resize(620, 470)

        layout = QVBoxLayout()

        # Welcome message
        welcome = QLabel("Welcome to Journey FM Playlist Creator!")
        welcome_font = QFont(self.font())
        base_size = welcome_font.pointSize()
        if base_size <= 0:
            base_size = 10
        welcome_font.setPointSize(max(base_size + 3, 14))
        welcome_font.setBold(True)
        welcome.setFont(welcome_font)
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

        self.connection_status = QLabel("Connection not tested")
        self.connection_status.setObjectName("SecondaryStatus")
        form_layout.addRow("Connection:", self.connection_status)

        connection_button_row = QHBoxLayout()
        self.test_connection_btn = QPushButton("Test Plex")
        self.test_connection_btn.clicked.connect(self.test_connection)
        connection_button_row.addWidget(self.test_connection_btn)
        connection_button_row.addStretch()
        form_layout.addRow("", connection_button_row)

        # Editable combo — user can pick an existing playlist or type a new name.
        playlist_row = QHBoxLayout()
        self.playlist_combo = QComboBox()
        self.playlist_combo.setEditable(True)
        self.playlist_combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.playlist_combo.lineEdit().setPlaceholderText("Type a name or click Browse")
        self.playlist_combo.addItem("Journey FM Recently Played")
        playlist_row.addWidget(self.playlist_combo, stretch=1)

        self.new_playlist_btn = QPushButton("New…")
        self.new_playlist_btn.setToolTip("Create a new playlist name")
        self.new_playlist_btn.clicked.connect(self.create_new_playlist_name)
        playlist_row.addWidget(self.new_playlist_btn)

        self.browse_btn = QPushButton("Browse…")
        self.browse_btn.setToolTip("Fetch playlists from your Plex server")
        self.browse_btn.clicked.connect(self.fetch_playlists)
        playlist_row.addWidget(self.browse_btn)

        form_layout.addRow("Playlist:", playlist_row)

        self.music_only_checkbox = QCheckBox("Show music playlists only")
        self.music_only_checkbox.setChecked(True)
        self.music_only_checkbox.toggled.connect(self.refresh_playlist_combo)
        form_layout.addRow("", self.music_only_checkbox)

        self.playlist_fetch_status = QLabel("")
        self.playlist_fetch_status.setObjectName("SecondaryStatus")
        form_layout.addRow("", self.playlist_fetch_status)

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

        self.klove_checkbox = QCheckBox("K-LOVE (klove.com)")
        self.klove_checkbox.setChecked(False)
        station_layout.addWidget(self.klove_checkbox)

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
        saved_playlist = config.get('PLAYLIST_NAME', 'Journey FM Recently Played')
        self.playlist_combo.setCurrentText(saved_playlist)

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
        self.klove_checkbox.setChecked('klove' in selected_stations)

    def get_config(self):
        selected_stations = []
        if self.journey_fm_checkbox.isChecked():
            selected_stations.append('journey_fm')
        if self.spirit_fm_checkbox.isChecked():
            selected_stations.append('spirit_fm')
        if self.klove_checkbox.isChecked():
            selected_stations.append('klove')

        playlist_name = self._selected_playlist_title()
        return {
            'PLEX_TOKEN': self.token_input.text().strip(),
            'SERVER_IP': self.server_input.text().strip(),
            'PLAYLIST_NAME': playlist_name,
            'AUTO_UPDATE': self.auto_update.isChecked(),
            'UPDATE_INTERVAL': self.interval_spin.value(),
            'UPDATE_UNIT': self.interval_unit.currentText(),
            'SELECTED_STATIONS': ','.join(selected_stations)
        }

    def _selected_playlist_title(self):
        current_index = self.playlist_combo.currentIndex()
        if current_index >= 0:
            record = self.playlist_combo.itemData(current_index)
            if isinstance(record, dict) and record.get('title'):
                return record['title']
        return self.playlist_combo.currentText().strip() or 'Journey FM Recently Played'

    def _format_playlist_label(self, record):
        playlist_type = record.get('playlist_type', 'unknown')
        item_count = record.get('item_count', 0)
        return f"{record['title']} [{playlist_type}, {item_count} items]"

    def refresh_playlist_combo(self, *_):
        current_title = self._selected_playlist_title()
        self.playlist_combo.blockSignals(True)
        self.playlist_combo.clear()
        records = self.playlist_records
        if self.music_only_checkbox.isChecked():
            records = [record for record in records if record.get('playlist_type') == 'audio']
        for record in records:
            self.playlist_combo.addItem(self._format_playlist_label(record), record)
        match_index = -1
        for index in range(self.playlist_combo.count()):
            record = self.playlist_combo.itemData(index)
            if isinstance(record, dict) and record.get('title', '').lower() == current_title.lower():
                match_index = index
                break
        if match_index >= 0:
            self.playlist_combo.setCurrentIndex(match_index)
        else:
            self.playlist_combo.setCurrentText(current_title)
        self.playlist_combo.blockSignals(False)

    def create_new_playlist_name(self):
        name, accepted = QInputDialog.getText(self, 'Create Playlist', 'Enter a new playlist name:')
        if accepted and name.strip():
            self.playlist_combo.setCurrentText(name.strip())
            self.connection_validated = False

    def fetch_playlists(self):
        """Connect to Plex in background and populate the playlist combo."""
        token = self.token_input.text().strip()
        server_ip = self.server_input.text().strip()
        if not token or not server_ip:
            QMessageBox.warning(self, "Missing Credentials",
                                "Please enter your Plex Token and Server IP first.")
            return

        self.browse_btn.setEnabled(False)
        self.playlist_fetch_status.setText("Connecting to Plex…")

        self._fetch_worker = PlexFetchPlaylistsWorker(token, server_ip, False, parent=self)
        self._fetch_worker.finished.connect(self._on_playlists_fetched)
        self._fetch_worker.error.connect(self._on_fetch_error)
        self._fetch_worker.start()

    def _on_playlists_fetched(self, records):
        self.playlist_records = records
        self.refresh_playlist_combo()
        count = len(records)
        self.playlist_fetch_status.setText(f"{count} playlist{'s' if count != 1 else ''} found")
        self.browse_btn.setEnabled(True)
        self.connection_validated = False

    def _on_fetch_error(self, message):
        self.playlist_fetch_status.setText(f"Error: {message}")
        self.browse_btn.setEnabled(True)
        self.connection_validated = False

    def test_connection(self):
        token = self.token_input.text().strip()
        server_ip = self.server_input.text().strip()
        playlist_name = self._selected_playlist_title()
        if not token or not server_ip:
            QMessageBox.warning(self, 'Missing Credentials', 'Please enter your Plex Token and Server IP first.')
            return
        self.connection_status.setText('Testing Plex connection…')
        self.test_connection_btn.setEnabled(False)
        self._validation_worker = PlexConnectionTestWorker(
            token,
            server_ip,
            playlist_name,
            self.music_only_checkbox.isChecked(),
            parent=self,
        )
        self._validation_worker.finished.connect(self._on_connection_tested)
        self._validation_worker.error.connect(self._on_connection_failed)
        self._validation_worker.start()

    def _on_connection_tested(self, payload):
        self.connection_status.setText(payload.get('message', 'Plex connection verified'))
        self.test_connection_btn.setEnabled(True)
        self.connection_validated = True

    def _on_connection_failed(self, message):
        self.connection_status.setText(f'Connection failed: {message}')
        self.test_connection_btn.setEnabled(True)
        self.connection_validated = False

    def validate_and_accept(self):
        """Validate configuration before accepting"""
        if not self.journey_fm_checkbox.isChecked() and not self.spirit_fm_checkbox.isChecked():
            QMessageBox.warning(self, "Validation Error",
                              "Please select at least one station to monitor.")
            return
        try:
            validate_playlist_target(
                self.token_input.text().strip(),
                self.server_input.text().strip(),
                self._selected_playlist_title(),
                self.music_only_checkbox.isChecked(),
            )
        except Exception as exc:
            QMessageBox.warning(self, 'Validation Error', str(exc))
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
        log_font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        log_size = log_font.pointSize()
        if log_size <= 0:
            log_font.setPointSize(10)
        self.log_text.setFont(log_font)
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

class PlexFetchPlaylistsWorker(QThread):
    """Fetch Plex playlists in the background."""
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, token, server_ip, music_only, parent=None):
        super().__init__(parent)
        self.token = token
        self.server_ip = server_ip
        self.music_only = music_only

    def run(self):
        try:
            records = fetch_playlists(self.token, self.server_ip, self.music_only)
            self.finished.emit(records)
        except Exception as e:
            self.error.emit(str(e))


class PlexConnectionTestWorker(QThread):
    """Validate Plex connectivity and playlist write target in the background."""
    finished = Signal(dict)
    error = Signal(str)

    def __init__(self, token, server_ip, playlist_name, music_only, parent=None):
        super().__init__(parent)
        self.token = token
        self.server_ip = server_ip
        self.playlist_name = playlist_name
        self.music_only = music_only

    def run(self):
        try:
            payload = validate_playlist_target(
                self.token,
                self.server_ip,
                self.playlist_name,
                self.music_only,
            )
            self.finished.emit(payload)
        except Exception as e:
            self.error.emit(str(e))


class UpdateWorker(QThread):
    """Worker thread for running playlist updates"""
    finished = Signal(str)
    progress = Signal(str)

    def __init__(self, config_data=None, parent=None):
        super().__init__(parent)
        self.config_data = config_data

    def run(self):
        try:
            self.progress.emit("Starting playlist update...")
            result = run_update_job(config=self.config_data)
            self.finished.emit(format_result_summary(result))

        except Exception as e:
            self.finished.emit(f"Error: {str(e)}")


class PreviewWorker(QThread):
    """Worker thread for generating sync preview without writing changes."""
    finished = Signal(dict)
    progress = Signal(str)
    error = Signal(str)

    def __init__(self, config_data=None, parent=None):
        super().__init__(parent)
        self.config_data = config_data

    def run(self):
        try:
            self.progress.emit("Preparing sync preview...")
            result = run_update_job(
                config=self.config_data,
                dry_run=True,
                persist_history=False,
                write_buy_list=False,
            )
            self.finished.emit(result)
        except Exception as exc:
            self.error.emit(str(exc))

class MainWindow(QMainWindow):
    """Main application window"""
    def __init__(self):
        super().__init__()
        self.tray_icon = None  # Will be set later
        self.config = Config()
        self.config.load_config()
        self.connection_verified = False

        self.setWindowTitle("Journey FM Playlist Creator")
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'icon.png')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(980, 700)
        self.setMinimumSize(860, 600)

        # Create central widget
        central = QWidget()
        central.setObjectName("AppRoot")
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # Hero panel
        hero_panel = QWidget()
        hero_panel.setObjectName("HeroPanel")
        hero_layout = QHBoxLayout(hero_panel)
        hero_layout.setContentsMargins(20, 16, 20, 16)

        hero_text_layout = QVBoxLayout()
        hero_title = QLabel("Journey FM Sync Hub")
        hero_title.setObjectName("HeroTitle")
        hero_subtitle = QLabel("Automate radio-to-Plex updates, monitor run health, and manage your backlog.")
        hero_subtitle.setObjectName("HeroSubtitle")
        hero_subtitle.setWordWrap(True)
        hero_text_layout.addWidget(hero_title)
        hero_text_layout.addWidget(hero_subtitle)

        chip_layout = QVBoxLayout()
        chip_layout.setSpacing(8)
        self.connection_status_chip = QLabel("Plex: Not checked")
        self.connection_status_chip.setObjectName("StatusChip")
        chip_layout.addWidget(self.connection_status_chip)
        self.auto_status_chip = QLabel("Auto: Disabled")
        self.auto_status_chip.setObjectName("StatusChip")
        self.last_sync_chip = QLabel("Last sync: Never")
        self.last_sync_chip.setObjectName("StatusChip")
        chip_layout.addWidget(self.auto_status_chip)
        chip_layout.addWidget(self.last_sync_chip)
        chip_layout.addStretch()

        hero_layout.addLayout(hero_text_layout, stretch=3)
        hero_layout.addLayout(chip_layout, stretch=2)
        layout.addWidget(hero_panel)

        # Toolbar
        toolbar = self.addToolBar("Main")
        toolbar.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)

        update_action = QAction("Update Now", self)
        update_action.triggered.connect(self.manual_update)
        toolbar.addAction(update_action)

        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self.show_settings)
        toolbar.addAction(settings_action)

        test_action = QAction("Test Plex", self)
        test_action.triggered.connect(self.refresh_connection_status)
        toolbar.addAction(test_action)
        toolbar.setObjectName("MainToolbar")

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
        self.status_label.setObjectName("PrimaryStatus")
        status_layout.addWidget(self.status_label)

        self.last_update_label = QLabel("Last update: Never")
        self.last_update_label.setObjectName("SecondaryStatus")
        status_layout.addWidget(self.last_update_label)

        # Buttons in grid layout
        button_layout = QGridLayout()
        
        # Row 1
        self.update_button = QPushButton("Update Playlist")
        self.update_button.clicked.connect(self.run_update_playlist)
        button_layout.addWidget(self.update_button, 0, 0)

        self.preview_button = QPushButton("Preview Sync")
        self.preview_button.clicked.connect(self.preview_update)
        button_layout.addWidget(self.preview_button, 0, 1)
        
        self.buy_list_button = QPushButton("Show Buy List")
        self.buy_list_button.clicked.connect(self.show_buy_list)
        button_layout.addWidget(self.buy_list_button, 0, 2)
        
        # Row 2
        self.history_button = QPushButton("View History")
        self.history_button.clicked.connect(self.show_history)
        button_layout.addWidget(self.history_button, 1, 0)
        
        self.export_button = QPushButton("Export Playlist")
        self.export_button.clicked.connect(self.export_playlist)
        button_layout.addWidget(self.export_button, 1, 1)

        self.station_health_button = QPushButton("Station Health")
        self.station_health_button.clicked.connect(self.show_station_health)
        button_layout.addWidget(self.station_health_button, 1, 2)
        
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

        self.apply_modern_theme()

        self.load_settings()
        self.set_action_controls_enabled(False)

        # Check if first run
        if not self.config.get('PLEX_TOKEN'):
            self.show_setup_wizard()
        else:
            self.refresh_connection_status()

    def apply_modern_theme(self):
        """Apply an updated visual style to the desktop app."""
        self.setStyleSheet("""
            /* ── Global base: dark text everywhere by default ── */
            QWidget {
                font-family: 'Trebuchet MS', 'Segoe UI', sans-serif;
                font-size: 13px;
                color: #22343d;
            }
            QWidget#AppRoot {
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:1,
                    stop:0 #f7f3ec,
                    stop:0.45 #f1efe8,
                    stop:1 #e7ece7
                );
            }

            /* ── Labels default to dark ── */
            QLabel { color: #22343d; }

            /* ── GroupBox ── */
            QGroupBox {
                color: #22343d;
                font-weight: 700;
                border: 1px solid #d2d7ce;
                border-radius: 10px;
                margin-top: 8px;
                padding-top: 10px;
                background-color: #fbfaf6;
            }
            QGroupBox::title { color: #22343d; }

            /* ── Hero panel: light text on dark bg ── */
            QWidget#HeroPanel {
                border-radius: 14px;
                border: 1px solid #d0d8d1;
                background: qlineargradient(
                    x1:0, y1:0, x2:1, y2:0,
                    stop:0 #204a57,
                    stop:1 #2f6f7b
                );
            }
            QLabel#HeroTitle {
                color: #f8f4e8;
                font-size: 22px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }
            QLabel#HeroSubtitle {
                color: #d4ebe6;
                font-size: 12px;
            }
            QLabel#StatusChip {
                background-color: rgba(255, 255, 255, 0.18);
                color: #f0f4f2;
                border: 1px solid rgba(255, 255, 255, 0.35);
                border-radius: 14px;
                padding: 6px 12px;
                font-weight: 600;
            }

            /* ── Toolbar ── */
            QToolBar#MainToolbar {
                background: #f2ede2;
                border: 1px solid #d3cbba;
                border-radius: 10px;
                spacing: 8px;
                padding: 5px;
            }
            QToolBar#MainToolbar QToolButton {
                color: #22343d;
                background: transparent;
                border: 1px solid transparent;
                border-radius: 7px;
                padding: 4px 10px;
                font-weight: 600;
            }
            QToolBar#MainToolbar QToolButton:hover {
                background: #e4ddd1;
                border-color: #c8bfb0;
            }
            QToolBar#MainToolbar QToolButton:pressed {
                background: #d8d0c4;
            }

            /* ── Action buttons: white text on dark teal ── */
            QPushButton {
                background-color: #1f7668;
                color: #f0f4f2;
                border: 1px solid #15584d;
                border-radius: 9px;
                min-height: 30px;
                padding: 5px 10px;
                font-weight: 600;
            }
            QPushButton:hover  { background-color: #2a8d7c; }
            QPushButton:pressed { background-color: #1a5e53; }

            /* ── Named status labels ── */
            QLabel#PrimaryStatus {
                color: #19434f;
                font-size: 15px;
                font-weight: 700;
            }
            QLabel#SecondaryStatus {
                color: #57656b;
                font-size: 12px;
            }

            /* ── Inputs ── */
            QLineEdit, QSpinBox, QComboBox {
                color: #22343d;
                background-color: #ffffff;
                border: 1px solid #c8ccc7;
                border-radius: 6px;
                padding: 4px 8px;
            }
            QComboBox QAbstractItemView {
                color: #22343d;
                background-color: #ffffff;
                selection-color: #ffffff;
                selection-background-color: #1f7668;
                border: 1px solid #c8ccc7;
                outline: none;
            }
            QComboBox QAbstractItemView::item {
                color: #22343d;
                background-color: #ffffff;
                padding: 4px 8px;
                min-height: 24px;
            }
            QComboBox QAbstractItemView::item:hover {
                color: #ffffff;
                background-color: #2a8d7c;
            }
            QCheckBox { color: #22343d; }

            /* ── Text areas ── */
            QTextEdit {
                color: #22343d;
                background-color: #fffdf8;
                border: 1px solid #d7d9d2;
                border-radius: 8px;
            }

            /* ── Tables ── */
            QTableWidget {
                color: #22343d;
                background-color: #ffffff;
                alternate-background-color: #f6f8f4;
                gridline-color: #d9ddd6;
                selection-color: #ffffff;
                selection-background-color: #1f7668;
            }
            QTableWidget::item {
                color: #22343d;
                background-color: #ffffff;
            }
            QTableWidget::item:selected {
                color: #ffffff;
                background-color: #1f7668;
            }
            QHeaderView::section {
                color: #22343d;
                background-color: #eceae3;
                font-weight: 600;
                border: none;
                padding: 4px 8px;
            }

            /* ── Tabs ── */
            QTabWidget::pane {
                border: 1px solid #d4d8d1;
                background: #fffdf8;
            }
            QTabBar::tab {
                color: #22343d;
                background: #ebe9e0;
                border: 1px solid #d4d8d1;
                padding: 6px 12px;
                margin-right: 2px;
            }
            QTabBar::tab:selected {
                color: #ffffff;
                background: #1f7668;
                border-color: #15584d;
            }

            /* ── Dialogs ── */
            QDialog { background-color: #f7f3ec; color: #22343d; }
            QDialogButtonBox QPushButton { min-width: 80px; }

            /* ── Progress bar ── */
            QProgressBar {
                border: 1px solid #d2d5cb;
                border-radius: 7px;
                background: #f0f2ec;
                text-align: center;
                min-height: 12px;
                color: #22343d;
            }
            QProgressBar::chunk {
                border-radius: 7px;
                background-color: #d17b2f;
            }
        """)

    def run_update_playlist(self):
        """Run playlist update in background thread"""
        self.manual_update()

    def set_action_controls_enabled(self, enabled):
        self.update_button.setEnabled(enabled)
        self.preview_button.setEnabled(enabled)
        self.export_button.setEnabled(enabled)
        self.station_health_button.setEnabled(True)

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
            self.refresh_connection_status()
            QMessageBox.information(self, "Setup Complete",
                                  "Configuration saved! The app will now update your playlist automatically.")

    def load_settings(self):
        """Load settings and configure auto-update"""
        auto_update = parse_bool(self.config.get('AUTO_UPDATE', False))
        interval = int(self.config.get('UPDATE_INTERVAL', 15))
        unit = self.config.get('UPDATE_UNIT', 'Minutes')
        self.requested_interval_ms = interval * 60 * 1000 if unit != 'Hours' else interval * 60 * 60 * 1000
        if auto_update:
            self.update_timer.stop()
            self.status_label.setText(f"Auto-update armed (every {interval} {unit.lower()})")
            self.auto_status_chip.setText(f"Auto: On ({interval} {unit.lower()})")
        else:
            self.update_timer.stop()
            self.status_label.setText("Auto-update disabled")
            self.auto_status_chip.setText("Auto: Off")

    def refresh_connection_status(self):
        token = self.config.get('PLEX_TOKEN', '')
        server_ip = self.config.get('SERVER_IP', '')
        playlist_name = self.config.get('PLAYLIST_NAME', 'Journey FM Recently Played')
        if not token or not server_ip:
            self.connection_verified = False
            self.connection_status_chip.setText('Plex: Setup required')
            self.status_label.setText('Plex configuration incomplete')
            self.set_action_controls_enabled(False)
            self.update_timer.stop()
            return

        self.connection_status_chip.setText('Plex: Checking…')
        self.status_label.setText('Validating Plex connection…')
        self.set_action_controls_enabled(False)
        self._connection_worker = PlexConnectionTestWorker(token, server_ip, playlist_name, True, parent=self)
        self._connection_worker.finished.connect(self._on_connection_ready)
        self._connection_worker.error.connect(self._on_connection_error)
        self._connection_worker.start()

    def _on_connection_ready(self, payload):
        self.connection_verified = True
        self.connection_status_chip.setText('Plex: Connected')
        self.status_label.setText(payload.get('message', 'Plex connection verified'))
        self.set_action_controls_enabled(True)
        if parse_bool(self.config.get('AUTO_UPDATE', False)):
            self.update_timer.start(self.requested_interval_ms)

    def _on_connection_error(self, message):
        self.connection_verified = False
        self.connection_status_chip.setText('Plex: Not Connected')
        self.status_label.setText(message)
        self.set_action_controls_enabled(False)
        self.update_timer.stop()

    def manual_update(self):
        """Manually trigger playlist update"""
        if not self.connection_verified:
            QMessageBox.warning(self, 'Plex Not Ready', 'Validate Plex connection before running updates.')
            return
        if hasattr(self, 'worker') and self.worker.isRunning():
            QMessageBox.information(self, "Update in Progress",
                                  "An update is already running. Please wait.")
            return

        self.set_action_controls_enabled(False)
        self.worker = UpdateWorker(self.config.load_config())
        self.worker.progress.connect(self.update_progress)
        self.worker.finished.connect(self.update_finished)
        self.worker.start()

        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)  # Indeterminate progress
        self.status_label.setText("Updating playlist...")
        self.last_sync_chip.setText("Last sync: In progress")

    def update_progress(self, message):
        """Update progress display"""
        self.status_label.setText(message)

    def update_finished(self, result):
        """Handle update completion"""
        self.progress_bar.setVisible(False)
        self.set_action_controls_enabled(self.connection_verified)
        last_sync = datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')
        self.last_update_label.setText(f"Last update: {last_sync}")
        self.last_sync_chip.setText(f"Last sync: {last_sync}")
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
        if not self.connection_verified:
            self.update_timer.stop()
            return
        if hasattr(self, 'worker') and self.worker.isRunning():
            return  # Skip if already running

        self.worker = UpdateWorker(self.config.load_config())
        self.worker.finished.connect(self.auto_update_finished)
        self.worker.start()

    def preview_update(self):
        """Generate a dry-run preview of sync changes before applying."""
        if not self.connection_verified:
            QMessageBox.warning(self, 'Plex Not Ready', 'Validate Plex connection before previewing updates.')
            return
        if hasattr(self, 'preview_worker') and self.preview_worker.isRunning():
            QMessageBox.information(self, 'Preview in Progress', 'A preview is already running. Please wait.')
            return

        self.set_action_controls_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)
        self.status_label.setText('Building preview...')

        self.preview_worker = PreviewWorker(self.config.load_config(), self)
        self.preview_worker.progress.connect(self.update_progress)
        self.preview_worker.finished.connect(self.preview_finished)
        self.preview_worker.error.connect(self.preview_failed)
        self.preview_worker.start()

    def preview_finished(self, result):
        self.progress_bar.setVisible(False)
        self.set_action_controls_enabled(self.connection_verified)
        self.status_label.setText('Preview ready')
        self.show_preview_dialog(result)

    def preview_failed(self, message):
        self.progress_bar.setVisible(False)
        self.set_action_controls_enabled(self.connection_verified)
        self.status_label.setText('Preview failed')
        QMessageBox.warning(self, 'Preview Error', message)

    def auto_update_finished(self, result):
        """Handle automatic update completion"""
        last_sync = datetime.now().strftime('%Y-%m-%d %I:%M:%S %p')
        self.last_update_label.setText(f"Last update: {last_sync}")
        self.last_sync_chip.setText(f"Last sync: {last_sync}")

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
                message_icon = QSystemTrayIcon.MessageIcon.Information
                message_text = "Playlist updated successfully"
                if "Error" in result:
                    message_icon = QSystemTrayIcon.MessageIcon.Warning
                    message_text = "Playlist update failed"
                self.tray_icon.showMessage(
                    "Journey FM Update",
                    message_text,
                    message_icon,
                    3000
                )

    def show_settings(self):
        """Show settings dialog"""
        wizard = SetupWizard(self.config, self)
        if wizard.exec() == QDialog.DialogCode.Accepted:
            config = wizard.get_config()
            self.config.save_config(config)
            self.load_settings()
            self.refresh_connection_status()
            QMessageBox.information(self, "Settings Saved", "Configuration updated successfully!")

    def show_buy_list(self):
        """Show the Amazon buy list dialog with interactive features"""
        try:
            buy_list_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'amazon_buy_list.txt')
            with open(buy_list_path, 'r', encoding='utf-8') as f:
                content = f.read()
        except FileNotFoundError:
            QMessageBox.information(self, "No Buy List", "No buy list available. Run an update to generate the list.")
            return
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to read buy list file: {e}")
            return

        try:
            self.buy_list_state_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'amazon_buy_list_state.json')
            self.buy_list_state = self.load_buy_list_state()

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
                        songs.append({
                            'artist_title': artist_title,
                            'amazon_url': url,
                            'key': artist_title.lower(),
                        })
                        i += 3  # Skip blank line
                    else:
                        i += 1
                else:
                    i += 1

            self.buy_list_all_songs = songs

            dialog = QDialog(self)
            dialog.setWindowTitle("Amazon Buy List")
            dialog.setModal(True)
            dialog.resize(760, 470)
            dialog.setStyleSheet("""
                QDialog {
                    background-color: #f7f3ec;
                    color: #22343d;
                }
                QLabel {
                    color: #22343d;
                    font-weight: 600;
                }
                QLineEdit {
                    color: #22343d;
                    background-color: #ffffff;
                    border: 1px solid #c8ccc7;
                    border-radius: 6px;
                    padding: 4px 8px;
                }
                QListWidget {
                    color: #22343d;
                    background-color: #ffffff;
                    alternate-background-color: #f6f8f4;
                    border: 1px solid #c8ccc7;
                    border-radius: 8px;
                    padding: 4px;
                }
                QListWidget::item {
                    color: #22343d;
                    background-color: #ffffff;
                    padding: 6px 8px;
                    border-radius: 4px;
                }
                QListWidget::item:selected {
                    color: #ffffff;
                    background-color: #1f7668;
                }
            """)

            layout = QVBoxLayout()

            # Search box
            search_layout = QHBoxLayout()
            search_layout.addWidget(QLabel("Search:"))
            self.search_input = QLineEdit()
            self.search_input.textChanged.connect(self.filter_buy_list)
            search_layout.addWidget(self.search_input)

            self.hide_completed_checkbox = QCheckBox('Hide purchased')
            self.hide_completed_checkbox.toggled.connect(self.filter_buy_list)
            search_layout.addWidget(self.hide_completed_checkbox)
            layout.addLayout(search_layout)

            # List widget
            self.buy_list_widget = QListWidget()
            self.buy_list_widget.setAlternatingRowColors(True)
            self.buy_list_label = QLabel(f"Found {len(songs)} songs to buy:")
            layout.addWidget(self.buy_list_label)
            self.populate_buy_list(songs)
            layout.addWidget(self.buy_list_widget)

            # Buttons
            button_layout = QHBoxLayout()

            open_amazon_button = QPushButton('Open Amazon')
            open_amazon_button.clicked.connect(lambda: self.open_selected_buy_items('amazon'))
            button_layout.addWidget(open_amazon_button)

            open_apple_button = QPushButton('Open Apple Music')
            open_apple_button.clicked.connect(lambda: self.open_selected_buy_items('apple'))
            button_layout.addWidget(open_apple_button)

            open_spotify_button = QPushButton('Open Spotify')
            open_spotify_button.clicked.connect(lambda: self.open_selected_buy_items('spotify'))
            button_layout.addWidget(open_spotify_button)

            purchased_button = QPushButton('Mark Purchased')
            purchased_button.clicked.connect(lambda: self.set_selected_purchase_state(True))
            button_layout.addWidget(purchased_button)

            unpurchased_button = QPushButton('Unmark Purchased')
            unpurchased_button.clicked.connect(lambda: self.set_selected_purchase_state(False))
            button_layout.addWidget(unpurchased_button)

            remove_button = QPushButton("Remove Selected")
            remove_button.clicked.connect(lambda: self.remove_selected_buy_items(dialog))
            button_layout.addWidget(remove_button)

            close_button = QPushButton("Close")
            close_button.clicked.connect(dialog.close)
            button_layout.addWidget(close_button)

            layout.addLayout(button_layout)

            dialog.setLayout(layout)
            dialog.exec()
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to show buy list dialog: {e}")

    def load_buy_list_state(self):
        import json

        if not os.path.exists(self.buy_list_state_path):
            return {}
        try:
            with open(self.buy_list_state_path, 'r', encoding='utf-8') as file_handle:
                payload = json.load(file_handle)
            return payload if isinstance(payload, dict) else {}
        except Exception:
            return {}

    def save_buy_list_state(self):
        import json

        try:
            with open(self.buy_list_state_path, 'w', encoding='utf-8') as file_handle:
                json.dump(self.buy_list_state, file_handle, indent=2)
        except Exception as exc:
            logger.error('Failed to save buy-list state: %s', exc)

    def build_store_url(self, artist_title, provider):
        import urllib.parse

        query = urllib.parse.quote_plus(artist_title)
        if provider == 'apple':
            return f'https://music.apple.com/us/search?term={query}'
        if provider == 'spotify':
            return f'https://open.spotify.com/search/{query}'
        return f'https://www.amazon.com/s?k={query}&i=digital-music'

    def populate_buy_list(self, songs):
        """Populate the buy list widget"""
        self.buy_list_widget.clear()
        active_count = 0
        for song in songs:
            key = song.get('key', song.get('artist_title', '').lower())
            purchased = bool(self.buy_list_state.get(key, {}).get('purchased', False))
            if purchased:
                display = f"[Purchased] {song['artist_title']}"
            else:
                display = song['artist_title']
                active_count += 1
            item = QListWidgetItem(display)
            item.setData(1, song)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.buy_list_widget.addItem(item)
        self.buy_list_label.setText(f"Showing {len(songs)} songs ({active_count} not purchased)")

    def filter_buy_list(self, *_):
        """Filter the buy list based on search text and purchased state."""
        search_text = self.search_input.text().lower().strip()
        hide_purchased = self.hide_completed_checkbox.isChecked()

        filtered = []
        for song in self.buy_list_all_songs:
            artist_title = song.get('artist_title', '')
            if search_text and search_text not in artist_title.lower():
                continue
            key = song.get('key', artist_title.lower())
            purchased = bool(self.buy_list_state.get(key, {}).get('purchased', False))
            if hide_purchased and purchased:
                continue
            filtered.append(song)

        self.populate_buy_list(filtered)

    def open_selected_buy_items(self, provider='amazon'):
        """Open selected buy list items in browser for requested provider."""
        for i in range(self.buy_list_widget.count()):
            item = self.buy_list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                song = item.data(1)
                artist_title = song.get('artist_title', '')
                url = song.get('amazon_url') if provider == 'amazon' else self.build_store_url(artist_title, provider)
                QDesktopServices.openUrl(QUrl(url))

    def set_selected_purchase_state(self, purchased):
        selected = 0
        for i in range(self.buy_list_widget.count()):
            item = self.buy_list_widget.item(i)
            if item.checkState() != Qt.CheckState.Checked:
                continue
            song = item.data(1)
            key = song.get('key', song.get('artist_title', '').lower())
            self.buy_list_state.setdefault(key, {})['purchased'] = purchased
            selected += 1

        if selected == 0:
            QMessageBox.information(self, 'No Selection', 'Please check one or more songs first.')
            return

        self.save_buy_list_state()
        self.filter_buy_list()

    def remove_selected_buy_items(self, dialog):
        """Remove selected items from buy list"""
        to_remove = set()
        for i in range(self.buy_list_widget.count()):
            item = self.buy_list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                song = item.data(1)
                to_remove.add(song.get('key', song.get('artist_title', '').lower()))

        if not to_remove:
            QMessageBox.information(dialog, "No Selection", "Please select items to remove.")
            return

        # Confirm
        reply = QMessageBox.question(dialog, "Confirm Removal", 
                                   f"Remove {len(to_remove)} selected items from buy list?",
                                   QMessageBox.Yes | QMessageBox.No)
        if reply != QMessageBox.Yes:
            return

        # Remove from song cache
        updated_songs = [song for song in self.buy_list_all_songs if song.get('key', song.get('artist_title', '').lower()) not in to_remove]

        # Rewrite file
        try:
            with open('amazon_buy_list.txt', 'w', encoding='utf-8') as f:
                f.write("Songs not in your library - Amazon search links:\n\n")
                for song in updated_songs:
                    artist_title = song.get('artist_title', '')
                    url = song.get('amazon_url', '')
                    f.write(f"{artist_title}\n{url}\n\n")
        except Exception as e:
            QMessageBox.warning(dialog, "Error", f"Failed to update buy list file: {e}")
            return

        self.buy_list_all_songs = updated_songs
        for key in list(self.buy_list_state.keys()):
            if key in to_remove:
                del self.buy_list_state[key]
        self.save_buy_list_state()

        # Update display
        self.filter_buy_list()
        QMessageBox.information(dialog, "Removed", f"Removed {len(to_remove)} items from buy list.")

    def show_statistics(self):
        """Show statistics dashboard"""
        import sqlite3
        import json
        from collections import Counter

        dialog = QDialog(self)
        dialog.setWindowTitle("Statistics Dashboard")
        dialog.setModal(True)
        dialog.resize(460, 380)

        layout = QVBoxLayout()

        try:
            conn = sqlite3.connect('playlist_history.db')
            c = conn.cursor()
            c.execute('SELECT COUNT(*), SUM(scraped_count), SUM(matched_count), SUM(added_count), SUM(missing_count), SUM(duplicate_count), SUM(skipped_count) FROM history')
            result = c.fetchone()
            c.execute("SELECT MAX(date), MAX(CASE WHEN status='success' THEN date END) FROM history")
            run_markers = c.fetchone()
            c.execute('SELECT station_breakdown FROM history')
            station_rows = c.fetchall()
            conn.close()

            total_updates = result[0] or 0
            total_scraped = result[1] or 0
            total_matched = result[2] or 0
            total_added = result[3] or 0
            total_missing = result[4] or 0
            total_duplicates = result[5] or 0
            total_skipped = result[6] or 0

            station_counter = Counter()
            for (station_json,) in station_rows:
                try:
                    for station in json.loads(station_json or '[]'):
                        if station.get('success'):
                            station_counter[station.get('display_name', station.get('station', 'Unknown'))] += station.get('scraped_count', 0)
                except Exception:
                    continue

            layout.addWidget(QLabel(f"Total Updates: {total_updates}"))
            layout.addWidget(QLabel(f"Total Songs Scraped: {total_scraped}"))
            layout.addWidget(QLabel(f"Total Songs Matched in Plex: {total_matched}"))
            layout.addWidget(QLabel(f"Total Songs Added to Plex: {total_added}"))
            layout.addWidget(QLabel(f"Total Songs in Buy List: {total_missing}"))
            layout.addWidget(QLabel(f"Duplicates Suppressed: {total_duplicates}"))
            layout.addWidget(QLabel(f"Invalid/Skipped Entries: {total_skipped}"))
            layout.addWidget(QLabel(f"Last Attempted Run: {run_markers[0] or 'Never'}"))
            layout.addWidget(QLabel(f"Last Successful Run: {run_markers[1] or 'Never'}"))

            if total_updates > 0:
                avg_match_rate = (total_matched / total_scraped * 100) if total_scraped else 0
                layout.addWidget(QLabel(f"Overall Match Rate: {avg_match_rate:.1f}%"))
                layout.addWidget(QLabel(f"Average Songs Added per Update: {total_added / total_updates:.1f}"))
                layout.addWidget(QLabel(f"Average Missing Songs per Update: {total_missing / total_updates:.1f}"))

            if station_counter:
                layout.addWidget(QLabel('Per-Station Scrape Totals:'))
                for station_name, count in station_counter.most_common():
                    layout.addWidget(QLabel(f"{station_name}: {count}"))

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

        def style_axis(fig, ax):
            fig.patch.set_facecolor('#fffdf8')
            ax.set_facecolor('#fffdf8')
            for spine in ax.spines.values():
                spine.set_color('#b9c2b6')
            ax.tick_params(axis='x', colors='#22343d')
            ax.tick_params(axis='y', colors='#22343d')
            ax.title.set_color('#22343d')
            ax.xaxis.label.set_color('#22343d')
            ax.yaxis.label.set_color('#22343d')
            ax.grid(color='#d8ddd5', linestyle='-', linewidth=0.6, alpha=0.6)

        try:
            conn = sqlite3.connect('playlist_history.db')
            c = conn.cursor()
            c.execute('SELECT date, added_songs, missing_songs, matched_count, duplicate_count, station_breakdown FROM history ORDER BY date')
            rows = c.fetchall()
            conn.close()

            # Prepare data
            dates = []
            cumulative_added = 0
            cumulative_list = []
            artist_counter = Counter()
            update_freq = []
            matched_counts = []
            duplicate_counts = []
            station_counter = Counter()

            for date, added_json, missing_json, matched_count, duplicate_count, station_json in rows:
                dt = datetime.fromisoformat(date)
                dates.append(dt.strftime('%Y-%m-%d'))
                
                added_songs = json.loads(added_json) if added_json else []
                cumulative_added += len(added_songs)
                cumulative_list.append(cumulative_added)
                update_freq.append(len(added_songs))
                matched_counts.append(matched_count or 0)
                duplicate_counts.append(duplicate_count or 0)

                try:
                    for station in json.loads(station_json or '[]'):
                        if station.get('success'):
                            station_counter[station.get('display_name', station.get('station', 'Unknown'))] += station.get('scraped_count', 0)
                except Exception:
                    pass
                
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
            style_axis(fig1, ax1)
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
            style_axis(fig2, ax2)
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
            style_axis(fig3, ax3)
            canvas3 = FigureCanvas(fig3)
            freq_layout.addWidget(canvas3)
            freq_tab.setLayout(freq_layout)
            tab_widget.addTab(freq_tab, "Update Frequency")

            # Tab 4: Match efficiency
            match_tab = QWidget()
            match_layout = QVBoxLayout()
            fig4 = Figure(figsize=(8, 6))
            ax4 = fig4.add_subplot(111)
            ax4.plot(dates, matched_counts, marker='o', label='Matched')
            ax4.plot(dates, duplicate_counts, marker='s', label='Duplicates Suppressed')
            ax4.set_title('Plex Match Quality')
            ax4.set_xlabel('Date')
            ax4.set_ylabel('Songs')
            ax4.tick_params(axis='x', rotation=45)
            ax4.legend()
            style_axis(fig4, ax4)
            canvas4 = FigureCanvas(fig4)
            match_layout.addWidget(canvas4)
            match_tab.setLayout(match_layout)
            tab_widget.addTab(match_tab, "Match Quality")

            # Tab 5: Station contribution
            station_tab = QWidget()
            station_layout = QVBoxLayout()
            fig5 = Figure(figsize=(8, 6))
            ax5 = fig5.add_subplot(111)
            if station_counter:
                station_names, station_values = zip(*station_counter.items())
                ax5.bar(station_names, station_values)
                ax5.set_title('Songs Scraped by Station')
                ax5.set_xlabel('Station')
                ax5.set_ylabel('Songs')
            style_axis(fig5, ax5)
            canvas5 = FigureCanvas(fig5)
            station_layout.addWidget(canvas5)
            station_tab.setLayout(station_layout)
            tab_widget.addTab(station_tab, "Stations")

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

    def show_preview_dialog(self, result):
        """Display dry-run sync results and offer apply action."""
        dialog = QDialog(self)
        dialog.setWindowTitle('Sync Preview')
        dialog.setModal(True)
        dialog.resize(980, 680)

        layout = QVBoxLayout()
        summary = QLabel(format_result_summary(result))
        summary.setWordWrap(True)
        layout.addWidget(summary)

        tab_widget = QTabWidget()

        def build_table(headers, rows):
            table = QTableWidget()
            table.setColumnCount(len(headers))
            table.setHorizontalHeaderLabels(headers)
            table.setRowCount(len(rows))
            table.setAlternatingRowColors(True)
            for row_idx, row in enumerate(rows):
                for col_idx, value in enumerate(row):
                    table.setItem(row_idx, col_idx, QTableWidgetItem(str(value)))
            table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            return table

        added_rows = []
        for entry in result.get('added_songs', []):
            if ' by ' in entry:
                title, rest = entry.split(' by ', 1)
                added_rows.append((title.strip(), rest.strip()))
            else:
                added_rows.append((entry, ''))
        tab_widget.addTab(build_table(['Title', 'Artist/Source'], added_rows), f"Will Add ({len(added_rows)})")

        duplicate_rows = [
            (song.get('title', ''), song.get('artist', ''), song.get('reason', ''))
            for song in result.get('duplicate_songs', [])
        ]
        tab_widget.addTab(build_table(['Title', 'Artist', 'Reason'], duplicate_rows), f"Duplicates ({len(duplicate_rows)})")

        missing_rows = [
            (song.get('title', ''), song.get('artist', ''), song.get('reason', ''))
            for song in result.get('missing_songs', [])
        ]
        tab_widget.addTab(build_table(['Title', 'Artist', 'Reason'], missing_rows), f"Missing ({len(missing_rows)})")

        skipped_rows = [
            (song.get('title', ''), song.get('artist', ''), song.get('reason', ''))
            for song in result.get('skipped_songs', [])
        ]
        tab_widget.addTab(build_table(['Title', 'Artist', 'Reason'], skipped_rows), f"Skipped ({len(skipped_rows)})")

        layout.addWidget(tab_widget)

        button_row = QHBoxLayout()
        apply_btn = QPushButton('Apply Sync Now')
        apply_btn.setEnabled(result.get('status') != 'error')

        def apply_and_close():
            dialog.accept()
            self.manual_update()

        apply_btn.clicked.connect(apply_and_close)
        button_row.addWidget(apply_btn)
        button_row.addStretch()

        close_btn = QPushButton('Close')
        close_btn.clicked.connect(dialog.close)
        button_row.addWidget(close_btn)
        layout.addLayout(button_row)

        dialog.setLayout(layout)
        dialog.exec()

    def show_station_health(self):
        """Show station reliability/quality metrics over recorded history."""
        import sqlite3
        import json
        from datetime import datetime

        dialog = QDialog(self)
        dialog.setWindowTitle('Station Health')
        dialog.setModal(True)
        dialog.resize(980, 520)
        layout = QVBoxLayout()

        table = QTableWidget()
        table.setColumnCount(7)
        table.setHorizontalHeaderLabels([
            'Station', 'Attempts', 'Success %', 'Last Success',
            'Last Pattern', 'Avg Payload KiB', 'Last Error'
        ])
        table.setAlternatingRowColors(True)

        station_stats = {}
        try:
            conn = sqlite3.connect('playlist_history.db')
            c = conn.cursor()
            c.execute('SELECT date, station_breakdown FROM history ORDER BY date')
            rows = c.fetchall()
            conn.close()

            for date_text, station_json in rows:
                try:
                    entries = json.loads(station_json or '[]')
                except Exception:
                    entries = []
                for entry in entries:
                    station_name = entry.get('display_name', entry.get('station', 'Unknown'))
                    data = station_stats.setdefault(station_name, {
                        'attempts': 0,
                        'success': 0,
                        'last_success': '',
                        'last_pattern': '',
                        'payload_total': 0,
                        'payload_samples': 0,
                        'last_error': '',
                    })
                    data['attempts'] += 1
                    if entry.get('success'):
                        data['success'] += 1
                        data['last_pattern'] = entry.get('parse_pattern', data['last_pattern'])
                        payload = int(entry.get('raw_payload_bytes', 0) or 0)
                        if payload > 0:
                            data['payload_total'] += payload
                            data['payload_samples'] += 1
                        try:
                            data['last_success'] = datetime.fromisoformat(date_text).strftime('%Y-%m-%d %H:%M')
                        except Exception:
                            data['last_success'] = date_text
                    else:
                        data['last_error'] = entry.get('error', '')

            table.setRowCount(len(station_stats))
            for row_idx, (station_name, stats) in enumerate(sorted(station_stats.items())):
                success_rate = (stats['success'] / stats['attempts'] * 100.0) if stats['attempts'] else 0.0
                avg_payload = (stats['payload_total'] / stats['payload_samples'] / 1024.0) if stats['payload_samples'] else 0.0
                values = [
                    station_name,
                    str(stats['attempts']),
                    f"{success_rate:.1f}",
                    stats['last_success'] or 'Never',
                    stats['last_pattern'] or 'n/a',
                    f"{avg_payload:.1f}",
                    stats['last_error'] or '',
                ]
                for col_idx, value in enumerate(values):
                    table.setItem(row_idx, col_idx, QTableWidgetItem(value))
        except Exception as exc:
            table.setRowCount(1)
            table.setItem(0, 0, QTableWidgetItem('Error loading station health'))
            table.setItem(0, 1, QTableWidgetItem(str(exc)))

        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(table)

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
        table.setColumnCount(5)
        table.setHorizontalHeaderLabels(["Date", "Type", "Artist", "Song", "Reason"])
        table.setAlternatingRowColors(True)
        table.setWordWrap(True)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)

        try:
            conn = sqlite3.connect('playlist_history.db')
            c = conn.cursor()
            c.execute('SELECT date, added_songs, missing_songs, skipped_songs, duplicate_count FROM history ORDER BY date DESC')
            rows = c.fetchall()
            conn.close()

            # Collect all entries
            entries = []
            for date, added_songs_json, missing_songs_json, skipped_songs_json, duplicate_count in rows:
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
                        entries.append((date_str, "Added", artist, title, ""))
                except Exception:
                    pass

                # Missing songs
                try:
                    missing_songs = json.loads(missing_songs_json)
                    for song in missing_songs:
                        artist = song.get('artist', 'Unknown')
                        title = song.get('title', 'Unknown')
                        entries.append((date_str, "Missing", artist, title, song.get('reason', 'not-found')))
                except Exception:
                    pass

                try:
                    skipped_songs = json.loads(skipped_songs_json)
                    for song in skipped_songs:
                        artist = song.get('artist', 'Unknown')
                        title = song.get('title', 'Unknown')
                        entries.append((date_str, "Skipped", artist, title, song.get('reason', 'skipped')))
                except Exception:
                    pass

                if duplicate_count:
                    entries.append((date_str, "Info", "", "Duplicate suppression", str(duplicate_count)))

            table.setRowCount(len(entries))
            for row_idx, (date_str, type_str, artist, song, reason) in enumerate(entries):
                table.setItem(row_idx, 0, QTableWidgetItem(date_str))
                table.setItem(row_idx, 1, QTableWidgetItem(type_str))
                table.setItem(row_idx, 2, QTableWidgetItem(artist))
                table.setItem(row_idx, 3, QTableWidgetItem(song))
                table.setItem(row_idx, 4, QTableWidgetItem(reason))

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

            from main import connect_to_plex_server
            plex = connect_to_plex_server(plex_token, server_ip)

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