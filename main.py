import sys
from pathlib import Path

import vlc

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QWidget


VIDEO_FILE = Path("media/video.mp4")


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()

        self.video_active = False

        self.setWindowTitle("DMX Video Player")

        self.setStyleSheet("background-color: black;")

        self.vlc_instance = vlc.Instance()

        self.player = self.vlc_instance.media_player_new()

    def start_video(self):
        media = self.vlc_instance.media_new(str(VIDEO_FILE))

        self.player.set_media(media)

        #Windows line:
        #self.player.set_hwnd(int(self.winId()))
        #Linux line:
        self.player.set_xwindow(int(self.winId()))

        self.player.play()

    def stop_video(self):
        self.player.stop()

        self.setStyleSheet("background-color: black;")

    def toggle_state(self):
        self.video_active = not self.video_active

        if self.video_active:
            print("VIDEO")
            self.start_video()
        else:
            print("BLACK")
            self.stop_video()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.close()

        elif event.key() == Qt.Key.Key_Space:
            self.toggle_state()


app = QApplication(sys.argv)

window = MainWindow()

window.showFullScreen()

sys.exit(app.exec())