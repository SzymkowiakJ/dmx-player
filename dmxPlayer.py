import logging
from logging.handlers import TimedRotatingFileHandler

loggingHandler = TimedRotatingFileHandler(
    "app.log",
    when = "midnight",
    interval = 1,
    backupCount = 180
)

logger = logging.getLogger("dmx_app")
logger.setLevel(logging.INFO)

handler = logging.FileHandler("app.log")
formatter = logging.Formatter(
    "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

handler.setFormatter(formatter)
logger.addHandler(handler)


import sys
import time
import vlc
import serial
from serial.serialutil import SerialException
from PySide6.QtCore import Signal, QObject, Qt, QThread, QTimer, QAbstractTableModel, QModelIndex

from PySide6.QtWidgets import (
    QApplication,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
    QTableView,
)

from collections import deque

class DMXTableModel(QAbstractTableModel):
    def __init__(self, channels=512):
        super().__init__()
        self.channels = channels
        self.values = [0] * channels

    def rowCount(self, parent=QModelIndex()):
        return self.channels

    def columnCount(self, parent=QModelIndex()):
        return 2  # Channel + Value

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        channel = index.row()

        if role == Qt.DisplayRole:
            if index.column() == 0:
                return channel + 1  # DMX channels start at 1
            elif index.column() == 1:
                return self.values[channel]

        return None

    def headerData(self, section, orientation, role):
        if role != Qt.DisplayRole:
            return None

        if orientation == Qt.Horizontal:
            return ["Channel", "Value"][section]

        return None

    def update_frame(self, frame):
        """
        frame = list of DMX values (usually 512 bytes)
        """
        self.values = frame[:self.channels]

        # notify Qt that entire table changed
        top_left = self.index(0, 0)
        bottom_right = self.index(self.channels - 1, 1)

        self.dataChanged.emit(top_left, bottom_right, [Qt.DisplayRole])

class DMXController(QObject):
    connection_status_signal = Signal(bool, str)
    dmx_frame_signal = Signal(list)
    def __init__(self, port_name):
        super().__init__()
        self.port_name = port_name
        self.serial_port = None
        self.is_connected = False
        self.thread = None
        self.running = False
        self.signal_active = False
        self.last_frame_time = 0

    def start_reading(self):
        if not self.is_connected:
            return
        self.running = True
        self.thread = QThread()
        self.thread.run = self.read_loop
        self.thread.start()

    def read_loop(self):
        while self.running:
            try:
                # ENTTEC protocol frame start
                start = self.serial_port.read(1)
                if not start:
                    continue

                if start[0] != 0x7E:
                    continue

                label = self.serial_port.read(1)
                length_l = self.serial_port.read(1)
                length_h = self.serial_port.read(1)

                if not length_l or not length_h:
                    continue

                length = length_l[0] | (length_h[0] << 8)

                data = self.serial_port.read(length)

                if len(data) < length:
                    continue  # corrupted frame → skip

                self.serial_port.read(1)  # end byte

                if label[0] == 0x05:
                    # normalize to 512 channels
                    if len(data) < 512:
                        data = data + bytes(512 - len(data))
                    else:
                        data = data[:512]

                dmx_values = list(data)
                self.dmx_frame_signal.emit(dmx_values)
                self.last_frame_time = time.time()
                
                if not self.signal_active:
                    self.signal_active = True

            except Exception as e:
                logger.error("DMX read error", exc_info=True)
                self.is_connected = False
                break

    def openDmxDevice(self):
        try:
            self.serial_port = serial.Serial(
                self.port_name,
                baudrate = 57600,
                timeout = 1
            )
            self.is_connected = True
            self.connection_status_signal.emit(True, "DMX device connected!")
            logger.info("Connected to DMX device")
            self.start_reading()

        except SerialException as e:
            self.is_connected = False
            self.serial_port = None
            logger.error("Failed to connect to DMX device", exc_info=True)
            self.connection_status_signal.emit(False, str(e))
            
class MoviePlayerWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.isVideoPlaying = False
        self.setStyleSheet("background-color: black;")
        #Setup moviePlayerWindow
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.showFullScreen()
        #Setup VLC
        self.vlc_instance = vlc.Instance()
        self.vlcPlayer = self.vlc_instance.media_player_new()
        self.vlcPlayer.set_media(self.vlc_instance.media_new(str("media/video.mp4")))
        self.vlcPlayer.set_hwnd(int(self.winId()))
    def playVideo(self):
        if self.isVideoPlaying == False:
            self.vlcPlayer.play()
            self.isVideoPlaying = True

    def stopVideo(self):
        if self.isVideoPlaying == True:
            self.vlcPlayer.stop()
            self.isVideoPlaying = False

class UiWindow(QMainWindow):
    start_video_signal = Signal()
    stop_video_signal = Signal()
    connect_to_DMX_device_signal = Signal()

    def __init__(self):
        super().__init__()
        self.button = QPushButton("Play Video")
        self.button.clicked.connect(self.playVideo)
        self.button2 = QPushButton("Stop video")
        self.button2.clicked.connect(self.stopVideo)

        self.wached_channel_history = deque(maxlen=5)
        self.is_video_playing = False

        self.dmxDataTable = QTableView()
        self.model = DMXTableModel()
        self.dmxDataTable.setModel(self.model)
        self.last_update = 0

        self.is_DMX_device_connected = False
        self.deviceStateLabel=QLabel("DMX device status:")
        self.deviceStateVariableLabel = QLabel("DMX: checking...")
        self.deviceStateVariableLabel.setStyleSheet("color: orange;")
        self.DMXdevice_timer = QTimer()
        self.DMXdevice_timer.timeout.connect(self.check_DMXdevice_connection)
        self.DMXdevice_timer.start(2000)

        self.is_datastream_active = False
        self.datastreamStateLabel=QLabel("Datastream status:")
        self.datastreamStateVariableLabel = QLabel("Datastream: checking...")
        self.datastreamStateVariableLabel.setStyleSheet("color: orange;")
        self.datastream_statuscheck_timer=QTimer()
        self.datastream_statuscheck_timer.timeout.connect(self.datastream_lost)
        self.datastream_statuscheck_timer.setSingleShot(True)
        self.datastream_statuscheck_timer.start(5000)

        layout = QVBoxLayout()
        layout.addWidget(self.deviceStateLabel)
        layout.addWidget(self.deviceStateVariableLabel)
        layout.addWidget(self.datastreamStateLabel)
        layout.addWidget(self.datastreamStateVariableLabel)
        layout.addWidget(self.dmxDataTable)
        layout.addWidget(self.button)
        layout.addWidget(self.button2)
        widget = QWidget()
        widget.setLayout(layout)
        self.setCentralWidget(widget)

    def check_DMXdevice_connection(self):
        if not self.is_DMX_device_connected:
            self.connect_to_DMX_device_signal.emit()

    def datastream_lost(self):
        self.is_datastream_active = False
        self.datastreamStateVariableLabel.setText("Datastream: No data recived")
        self.datastreamStateVariableLabel.setStyleSheet("color: red")
        self.datastream_statuscheck_timer.start(5000)

    def dmxFrameHandle(self, frame):

        self.is_datastream_active = True

        #Updating UI with channel values
        now = time.time()
        if now - self.last_update < 0.2:
            return
        self.last_update = now
        self.model.update_frame(frame)
        self.datastreamStateVariableLabel.setText("Datastream: Reciving data")
        self.datastreamStateVariableLabel.setStyleSheet("color: green")
        self.datastream_statuscheck_timer.start(5000)

        #checking if video should be played/stopped
        if len(frame) <= 510:
            return

        value = frame[510]
        self.wached_channel_history.append(value)

        if len(self.wached_channel_history) < 5:
            return

        all_high = all(v > 150 for v in self.wached_channel_history)
        all_low = all(v < 100 for v in self.wached_channel_history)

        if all_high and not self.is_video_playing:
            self.playVideo()
            self.is_video_playing = True

        elif all_low and self.is_video_playing:
            self.stopVideo()
            self.is_video_playing = False

    def playVideo(self):
        self.start_video_signal.emit()

    def stopVideo(self):
        self.stop_video_signal.emit()

    def connectionStatusChange(self, isConnected, msg):
        if isConnected:
            self.deviceStateVariableLabel.setText(f"{msg}")
            self.deviceStateVariableLabel.setStyleSheet(f"color: green;")
            self.is_DMX_device_connected = True
        else:
            self.deviceStateVariableLabel.setText(f"Brak połączenia z użądzeniem DMX: {msg}")
            self.deviceStateVariableLabel.setStyleSheet(f"color: red;")
            self.is_DMX_device_connected = False
            




app = QApplication(sys.argv)
uiWindow = UiWindow()
playerWindow = MoviePlayerWindow()
dmxController = DMXController("COM4")


uiWindow.start_video_signal.connect(
    lambda:playerWindow.playVideo()
)
uiWindow.stop_video_signal.connect(
    lambda:playerWindow.stopVideo()
)

uiWindow.connect_to_DMX_device_signal.connect(
    dmxController.openDmxDevice
)
dmxController.connection_status_signal.connect(
    uiWindow.connectionStatusChange 
)
dmxController.dmx_frame_signal.connect(
    uiWindow.dmxFrameHandle
)


uiWindow.show()
playerWindow.show()
playerWindow.raise_()


app.exec()