"""A looping video backdrop.

Frames are pulled from a QVideoSink and painted by hand rather than handed to a
QVideoWidget. QVideoWidget takes a native child window on Windows, which paints
over everything Qt puts on top of it — no amount of raise_() gets text back in
front of it. Drawing the frames ourselves keeps the backdrop inside Qt's normal
compositing, so the overview content layers over it correctly.

The whole module degrades to a plain gradient when QtMultimedia is absent, since
it ships in PySide6-Addons rather than PySide6-Essentials.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRect, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter
from PySide6.QtWidgets import QWidget

from . import theme

try:
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer, QVideoSink

    MULTIMEDIA_AVAILABLE = True
except ImportError:  # pragma: no cover - depends on the installed wheel
    QAudioOutput = QMediaPlayer = QVideoSink = None  # type: ignore
    MULTIMEDIA_AVAILABLE = False

# Containers Qt's Windows backend handles without extra codecs installed.
SUPPORTED_SUFFIXES = (".mp4", ".m4v", ".mov", ".wmv", ".avi", ".mkv", ".webm")
FILE_FILTER = (
    "Video (*.mp4 *.m4v *.mov *.wmv *.avi *.mkv *.webm);;All files (*)"
)


class VideoBackground(QWidget):
    """Plays a video behind other widgets, scaled to cover, under a scrim."""

    error = Signal(str)
    # Playback starts asynchronously, so controls must follow the player rather
    # than assume the state they asked for took effect.
    state_changed = Signal()

    def __init__(self, accent: str = "", scrim: float = 0.62):
        super().__init__()
        self.setAttribute(Qt.WA_StyledBackground, False)
        self._image: QImage | None = None
        # Resolved here rather than in the signature: a default argument is
        # evaluated at import, which would pin this to the shipped accent.
        self._accent = accent or theme.ACCENT
        self._scrim = scrim
        self._player = None
        self._sink = None
        self._audio = None
        self._source: Path | None = None

    # -- playback --------------------------------------------------------

    @property
    def available(self) -> bool:
        return MULTIMEDIA_AVAILABLE

    @property
    def playing(self) -> bool:
        if self._player is None:
            return False
        return self._player.playbackState() == QMediaPlayer.PlayingState

    @property
    def muted(self) -> bool:
        return self._audio.isMuted() if self._audio is not None else True

    def set_accent(self, accent: str) -> None:
        self._accent = accent
        self.update()

    def set_source(self, path: str | Path | None) -> bool:
        """Point at a video file. Returns False if it cannot be played."""
        self.stop()
        self._image = None
        self._source = Path(path) if path else None
        self.update()

        if self._source is None:
            return False
        if not MULTIMEDIA_AVAILABLE:
            self.error.emit(
                "Video playback needs the PySide6-Addons package, which is not "
                "installed. Run: pip install PySide6-Addons"
            )
            return False
        if not self._source.is_file():
            self.error.emit(f"{self._source} no longer exists.")
            return False

        self._ensure_player()
        self._player.setSource(QUrl.fromLocalFile(str(self._source.resolve())))
        self._player.play()
        return True

    def _ensure_player(self) -> None:
        if self._player is not None:
            return
        self._sink = QVideoSink(self)
        self._sink.videoFrameChanged.connect(self._on_frame)

        self._audio = QAudioOutput(self)
        self._audio.setMuted(True)  # A backdrop should never surprise anyone.
        self._audio.setVolume(0.5)

        self._player = QMediaPlayer(self)
        self._player.setVideoSink(self._sink)
        self._player.setAudioOutput(self._audio)
        self._player.setLoops(QMediaPlayer.Loops.Infinite)
        self._player.errorOccurred.connect(
            lambda _err, text: self.error.emit(text or "The video could not be played.")
        )
        self._player.playbackStateChanged.connect(
            lambda _state: self.state_changed.emit()
        )

    def _on_frame(self, frame) -> None:
        if not frame.isValid():
            return
        image = frame.toImage()
        if not image.isNull():
            self._image = image
            self.update()

    def play(self) -> None:
        if self._player is not None:
            self._player.play()

    def pause(self) -> None:
        if self._player is not None:
            self._player.pause()

    def toggle_play(self) -> None:
        self.pause() if self.playing else self.play()

    def set_muted(self, muted: bool) -> None:
        if self._audio is not None:
            self._audio.setMuted(muted)

    def stop(self) -> None:
        if self._player is not None:
            self._player.stop()

    def release(self) -> None:
        """Tear the player down, so a hidden tab is not decoding video."""
        if self._player is not None:
            self._player.stop()
            self._player.setVideoSink(None)
            self._player.deleteLater()
        if self._sink is not None:
            self._sink.deleteLater()
        if self._audio is not None:
            self._audio.deleteLater()
        self._player = self._sink = self._audio = None
        self._image = None

    # -- painting --------------------------------------------------------

    def paintEvent(self, event):  # noqa: N802 - Qt naming
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        if self._image is not None and not self._image.isNull():
            self._paint_cover(painter)
            painter.fillRect(
                self.rect(), QColor(0, 0, 0, int(255 * self._scrim))
            )
        else:
            self._paint_fallback(painter)
        painter.end()

    def _paint_cover(self, painter: QPainter) -> None:
        """Fill the widget, cropping the overflow rather than letterboxing."""
        area = self.rect()
        size = QSize(self._image.width(), self._image.height())
        size.scale(area.size(), Qt.KeepAspectRatioByExpanding)
        painter.drawImage(
            QRect(
                area.x() + (area.width() - size.width()) // 2,
                area.y() + (area.height() - size.height()) // 2,
                size.width(),
                size.height(),
            ),
            self._image,
        )

    def _paint_fallback(self, painter: QPainter) -> None:
        """A quiet accent wash, used until a video is chosen."""
        gradient = QLinearGradient(0, 0, self.width(), self.height())
        tinted = QColor(theme._mix(self._accent, theme.BG, 0.86))
        gradient.setColorAt(0.0, tinted)
        gradient.setColorAt(0.55, QColor(theme.BG))
        gradient.setColorAt(1.0, QColor(theme.SURFACE))
        painter.fillRect(self.rect(), gradient)
