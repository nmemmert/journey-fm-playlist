# Journey FM Playlist Creator

A cross-platform desktop application that automatically creates Plex playlists from recently played songs on My Journey FM radio station.

![Application Screenshot](screenshot.png)

## ✨ Features

- **System Tray Integration**: Runs minimized in the taskbar/system tray
- **Automatic Updates**: Configurable automatic playlist updates
- **Cross-Platform**: Works on Windows and Linux
- **Log Viewer**: Built-in log viewer for monitoring updates
- **Easy Setup**: Guided setup wizard for initial configuration
- **Duplicate Prevention**: Smart duplicate detection and prevention
- **Artist Matching**: Handles featured artists, punctuation, and name variations

## 🚀 Quick Start

### Windows

1. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Create Application Icon**
   ```bash
   python create_icon.py
   ```

3. **Run the Application**
   ```bash
   python journey_fm_app.py
   ```
   Or use the batch file: `run_app.bat`

### Linux

1. **Run the Installer**
   ```bash
   ./install.sh
   ```
   This will:
   - Install Python dependencies
   - Set up virtual environment
   - Install Chromium browser
   - Create desktop icon
   - Add to applications menu

2. **Launch from Menu**
   - Search for "Journey FM Playlist" in your applications menu
   - Or run: `./journey_fm_app.sh`

## ⚙️ Configuration

### First-Time Setup

When you first run the application, a setup wizard will guide you through:

1. **Plex Token**: See below for how to get your Plex token
2. **Server IP**: Your Plex server's local IP address (e.g., 192.168.1.100)
3. **Playlist Name**: Name for your Journey FM playlist (default: "Journey FM Recently Played")
4. **Auto-Update Settings**: Enable automatic updates and set intervals

#### How to Get Your Plex Token

1. Go to [https://plex.tv/claim](https://plex.tv/claim) in your web browser
2. Sign in with your Plex account
3. Copy the claim token from the page (it looks like: `pU-mHWYUZU6iXJFhJyA`)
4. Paste it into the application setup

**Note**: This token is used to authenticate with your Plex server. Keep it secure and don't share it.

### Manual Configuration

You can also edit settings anytime through the Settings menu in the application.

## 📱 System Tray Features

- **Minimize to Tray**: The app minimizes to system tray instead of closing
- **Right-click Menu**:
  - Show: Restore the main window
  - Update Now: Manually trigger playlist update
  - Quit: Exit the application
- **Double-click**: Restore the main window
- **Notifications**: Get notified when automatic updates complete

## 📋 Log Viewer

The built-in log viewer shows:
- Update timestamps
- Songs added to playlist
- Error messages
- Update duration
- Connection status

Logs are automatically saved to `playlist_log.txt` for external viewing.

## 🔄 Automatic Updates

Configure automatic updates to run every:
- 5-120 minutes
- Hours (up to several hours)

The app will:
- Run in the background
- Show tray notifications when updates complete
- Prevent duplicate songs
- Handle connection errors gracefully

## 🛠️ Troubleshooting

### Common Issues

**"Server not found"**
- Ensure your Plex server is running
- Check that you've claimed the server at http://[SERVER_IP]:32400/web
- Verify the server IP address in settings

**"No matching tracks found"**
- Ensure your music library is properly scanned in Plex
- Check that song metadata matches (artist names, titles)
- The app handles variations like "&" vs "and", featured artists, etc.

**System tray not working**
- On Linux, ensure you have a system tray (like KDE/GNOME)
- Some desktop environments may need additional packages

### Manual Testing

Test the core functionality:
```bash
python main.py
```

This runs the update once without the GUI.

## 📁 Project Structure

```
journey-fm-playlist/
├── journey_fm_app.py      # Main GUI application
├── main.py                # Core update logic
├── create_icon.py         # Icon generator
├── run_app.bat           # Windows launcher
├── journey_fm_app.sh     # Linux launcher
├── requirements.txt       # Python dependencies
├── config.json           # Configuration (auto-generated)
├── playlist_log.txt      # Update logs
├── icon.png              # Application icon
└── README.md             # This file
```

## 🔧 Development

### Adding Features

The application is built with PyQt6 for cross-platform compatibility. Key components:

- `MainWindow`: Main application window
- `SystemTrayApp`: Tray icon and menu
- `SetupWizard`: Configuration wizard
- `LogViewer`: Log display widget
- `UpdateWorker`: Background update thread

### Building Standalone Executables

**Windows (PyInstaller)**
```bash
pip install pyinstaller
pyinstaller --onefile --windowed --icon=icon.ico journey_fm_app.py
```

**Linux (PyInstaller)**
```bash
pip install pyinstaller
pyinstaller --onefile --icon=icon.png journey_fm_app.py
```

## 📋 Requirements

- **Python**: 3.8+
- **PyQt6**: GUI framework
- **Selenium**: Web scraping
- **PlexAPI**: Plex integration
- **BeautifulSoup4**: HTML parsing

### System Requirements

- **Windows**: 10+ with system tray support
- **Linux**: Modern desktop environment with system tray
- **Plex Server**: Local or remote Plex server access

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Test on both Windows and Linux
5. Submit a pull request

## 📄 License

This project is open source. Feel free to use and modify as needed.

## 🆘 Support

If you encounter issues:
1. Check the application logs
2. Verify your Plex server connection
3. Ensure all dependencies are installed
4. Test with `python main.py` first

For bugs or feature requests, please create an issue on GitHub.