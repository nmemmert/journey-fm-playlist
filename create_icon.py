#!/usr/bin/env python3
"""
Create application icon
"""
from PySide6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont
from PySide6.QtCore import QSize

def create_icon():
    """Create a simple application icon"""
    pixmap = QPixmap(64, 64)
    pixmap.fill(QColor(30, 144, 255))  # Dodger blue background

    painter = QPainter(pixmap)
    painter.setPen(QColor(255, 255, 255))
    painter.setFont(QFont("Arial", 32, QFont.Weight.Bold))

    # Draw music note symbol
    painter.drawText(16, 48, "♪")

    painter.end()

    icon = QIcon(pixmap)
    return icon

if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    import sys

    app = QApplication(sys.argv)
    icon = create_icon()
    pixmap = icon.pixmap(QSize(64, 64))
    png_ok = pixmap.save("icon.png")
    ico_ok = pixmap.save("icon.ico")
    if png_ok:
        print("Icon created: icon.png")
    if ico_ok:
        print("Icon created: icon.ico")
    if not png_ok and not ico_ok:
        print("Failed to create icon files")