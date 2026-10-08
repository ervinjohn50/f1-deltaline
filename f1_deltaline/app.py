"""F1 Deltaline desktop app (PySide6).

Choose a season, event and session, load it, then pick two drivers and laps to
compare. Loading and comparing run in the background so the window stays
responsive during the first download of a session (which can take a minute).
"""

import signal
import sys
from datetime import date

import matplotlib

matplotlib.use("QtAgg")

from matplotlib.backend_bases import ResizeEvent  # noqa: E402
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT  # noqa: E402
from matplotlib.figure import Figure  # noqa: E402
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, Signal  # noqa: E402
from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtWidgets import (QApplication, QComboBox, QHBoxLayout, QLabel,  # noqa: E402
                               QMainWindow, QMessageBox, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

from f1_deltaline.analysis import (check_lap_choices, compare_laps, distance_at_point,  # noqa: E402
                                   draw, hover_text, lap_rows, point_at)
import f1_deltaline.data as data  # noqa: E402
from f1_deltaline.data import drivers_in_order, load_schedule, load_session  # noqa: E402
from f1_deltaline.plot import BACKGROUND, FIGSIZE, MUTED, TEXT, format_lap_time  # noqa: E402

FIRST_YEAR = 2018  # detailed telemetry starts here
DEFAULT_SESSION = "Qualifying"
NOTE_COLOR = "#f5b84a"  # amber, for data notes
NOTES_MAX_WIDTH = 520  # pixels; longer data notes are shortened with "…"


class Signals(QObject):
    done = Signal(object)
    failed = Signal(str)


class Task(QRunnable):
    """Runs fn(*args) on a background thread and reports back through signals,
    which Qt delivers on the main thread."""

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args, self.signals = fn, args, Signals()

    def run(self):
        try:
            result = self.fn(*self.args)
        except Exception as error:  # shown to the user rather than crashing the app
            self.signals.failed.emit(str(error) or type(error).__name__)
        else:
            self.signals.done.emit(result)


def lap_choice_label(row):
    """Dropdown text for a lap, e.g. 'Lap 20 · 1:19.461 · Soft, 2 laps old · fastest'."""
    parts = [f"Lap {row['number']}", format_lap_time(row["lap_time"])]
    tyre = row["description"].split(", ", 1)
    if len(tyre) == 2:
        parts.append(tyre[1])
    parts += row["notes"]
    return " · ".join(parts)


class FitCanvas(FigureCanvasQTAgg):
    """A canvas that scales the whole figure to its size, keeping the designed
    16x10 layout.

    Matplotlib's own canvas keeps text the same size and stretches the layout
    to the window, so in a window smaller than the design size labels ran into
    each other. Scaling the resolution instead makes everything shrink together,
    exactly like the saved images. FitArea keeps the canvas at the right shape.
    """

    def resizeEvent(self, event):
        if self._in_resize_event or self.figure is None:
            return
        self._in_resize_event = True
        try:
            width = event.size().width() * self.device_pixel_ratio
            height = event.size().height() * self.device_pixel_ratio
            dpi = min(width / FIGSIZE[0], height / FIGSIZE[1])
            self.figure.set_dpi(dpi)
            # Size from the exact pixel count (within a pixel of 16x10 inches, as FitArea
            # keeps the shape). Using exactly 16x10 could leave the last pixel row
            # undrawn after rounding, showing leftovers from the previous size.
            self.figure.set_size_inches(width / dpi, height / dpi, forward=False)
            QWidget.resizeEvent(self, event)
            ResizeEvent("resize_event", self)._process()
            self.draw_idle()
        finally:
            self._in_resize_event = False


class FitArea(QWidget):
    """Holds the canvas, centred and as large as fits at the figure's 16:10 shape."""

    def __init__(self, canvas):
        super().__init__()
        self.canvas = canvas
        canvas.setParent(self)
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(BACKGROUND))
        self.setPalette(palette)
        self.setMinimumSize(640, 400)  # below this the text gets too small to read

    def resizeEvent(self, event):
        scale = min(self.width() / FIGSIZE[0], self.height() / FIGSIZE[1])
        width, height = int(FIGSIZE[0] * scale), int(FIGSIZE[1] * scale)
        self.canvas.setGeometry((self.width() - width) // 2, (self.height() - height) // 2,
                                width, height)
        super().resizeEvent(event)


class HoverCursor:
    """Vertical line on every chart plus a ring on the track map, following the mouse.

    Uses blitting (redrawing only the cursor over a saved background) so it stays
    smooth on a figure this size.
    """

    def __init__(self, canvas, axes, comparison, show_text):
        self.canvas, self.axes, self.c, self.show_text = canvas, axes, comparison, show_text
        self.lines = [ax.axvline(0, color=TEXT, lw=0.8, alpha=0.8, animated=True,
                                 visible=False) for ax in axes["charts"]]
        axes["track"].set_autoscale_on(False)
        self.ring, = axes["track"].plot([], [], "o", ms=14, mfc="none", mec=TEXT, mew=2,
                                        animated=True, visible=False)
        self.background = None
        self.connections = [canvas.mpl_connect("draw_event", self.on_draw),
                            canvas.mpl_connect("motion_notify_event", self.on_move),
                            canvas.mpl_connect("figure_leave_event", self.on_leave)]

    def disconnect(self):
        for cid in self.connections:
            self.canvas.mpl_disconnect(cid)

    def on_draw(self, _event):
        # A full redraw (first draw, resize, zoom) happens while Qt is painting the
        # window, so draw the cursor straight into the new image here. Calling
        # canvas.blit() now would ask Qt to repaint mid-paint, which it refuses
        # ("Recursive repaint detected").
        self.background = self.canvas.copy_from_bbox(self.canvas.figure.bbox)
        self.draw_cursor()

    def draw_cursor(self):
        for artist in [*self.lines, self.ring]:
            artist.axes.draw_artist(artist)

    def on_move(self, event):
        distance = None
        if event.inaxes in self.axes["charts"] and event.xdata is not None:
            distance = event.xdata
        elif event.inaxes is self.axes["track"] and event.xdata is not None:
            distance = distance_at_point(self.c, event.xdata, event.ydata)
        if distance is None:
            self.on_leave()
            return
        point = point_at(self.c, distance)
        for line in self.lines:
            line.set_xdata([point["distance"]] * 2)
            line.set_visible(True)
        self.ring.set_data([point["x"]], [point["y"]])
        self.ring.set_visible(True)
        self.show_text(hover_text(self.c, point))
        self.blit()

    def on_leave(self, _event=None):
        if self.ring.get_visible():
            for artist in [*self.lines, self.ring]:
                artist.set_visible(False)
            self.show_text("")
            self.blit()

    def blit(self):
        if self.background is None:
            return
        self.canvas.restore_region(self.background)
        self.draw_cursor()
        self.canvas.blit(self.canvas.figure.bbox)


class MainWindow(QMainWindow):
    def __init__(self, schedule_loader=load_schedule, session_loader=load_session):
        super().__init__()
        self.schedule_loader, self.session_loader = schedule_loader, session_loader
        self.pool = QThreadPool.globalInstance()
        self.tasks = set()  # keep running tasks alive until they report back
        self.latest = {}    # newest request per kind, so stale results are ignored
        self.events, self.session, self.cursor = [], None, None
        self.closed = False  # set on close, so results arriving afterwards are ignored

        self.setWindowTitle("F1 Deltaline")
        self.resize(1600, 1050)
        self.build_controls()
        self.figure = Figure(figsize=FIGSIZE, facecolor=BACKGROUND)
        self.canvas = FitCanvas(self.figure)
        self.show_placeholder("Choose a season, event and session, then press Load.")

        layout = QVBoxLayout()
        layout.addLayout(self.session_row)
        layout.addLayout(self.compare_row)
        # Zoom, pan and save; its coordinate readout is off since the status bar has a better one.
        layout.addWidget(NavigationToolbar2QT(self.canvas, self, coordinates=False))
        layout.addWidget(FitArea(self.canvas), stretch=1)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.hover_label = QLabel()
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # "busy" animation, since FastF1 gives no progress
        self.progress.setMaximumWidth(160)
        self.progress.hide()
        # Gaps in F1's data that affect the current comparison; full text on hover.
        self.notes_label = QLabel()
        self.notes_label.setStyleSheet(f"color: {NOTE_COLOR};")
        self.statusBar().addWidget(self.hover_label, 1)
        self.statusBar().addPermanentWidget(self.notes_label)
        self.statusBar().addPermanentWidget(self.progress)

        self.year.addItems([str(y) for y in range(date.today().year, FIRST_YEAR - 1, -1)])

    # --- controls -------------------------------------------------------------

    def build_controls(self):
        self.year, self.event, self.session_name = QComboBox(), QComboBox(), QComboBox()
        self.event.setMinimumWidth(240)
        self.session_name.setMinimumWidth(160)
        self.load_button = QPushButton("Load")
        self.session_row = row(("Season", self.year), ("Event", self.event),
                               ("Session", self.session_name), self.load_button)

        self.driver_a, self.lap_a = QComboBox(), QComboBox()
        self.driver_b, self.lap_b = QComboBox(), QComboBox()
        for lap in (self.lap_a, self.lap_b):
            lap.setMinimumWidth(320)
        self.compare_button = QPushButton("Compare")
        self.compare_row = row(("Driver A", self.driver_a), ("Lap", self.lap_a),
                               ("Driver B", self.driver_b), ("Lap", self.lap_b),
                               self.compare_button)
        self.set_compare_enabled(False)

        self.year.currentTextChanged.connect(self.on_year_changed)
        self.event.currentIndexChanged.connect(self.on_event_changed)
        self.load_button.clicked.connect(self.on_load)
        self.driver_a.currentTextChanged.connect(lambda d: self.fill_laps(self.lap_a, d))
        self.driver_b.currentTextChanged.connect(lambda d: self.fill_laps(self.lap_b, d))
        self.compare_button.clicked.connect(self.on_compare)

    def set_compare_enabled(self, enabled):
        for widget in (self.driver_a, self.lap_a, self.driver_b, self.lap_b,
                       self.compare_button):
            widget.setEnabled(enabled)

    def on_year_changed(self, year):
        if not year:
            return
        self.event.clear()
        self.session_name.clear()
        self.load_button.setEnabled(False)
        self.run("schedule", f"Loading the {year} calendar...", self.schedule_loader,
                 int(year), on_done=self.on_schedule_loaded)

    def on_schedule_loaded(self, events):
        self.events = events
        self.event.clear()
        for event in events:
            self.event.addItem(f"Round {event['round']}: {event['name']}", event)
        if events:
            self.event.setCurrentIndex(len(events) - 1)  # most recent event
        else:
            self.hover_label.setText("No sessions with data in this season yet.")

    def on_event_changed(self, _index):
        event = self.event.currentData()
        self.session_name.clear()
        if not event:
            return
        self.session_name.addItems(event["sessions"])
        if DEFAULT_SESSION in event["sessions"]:
            self.session_name.setCurrentText(DEFAULT_SESSION)
        self.load_button.setEnabled(True)

    def on_load(self):
        event, session_name = self.event.currentData(), self.session_name.currentText()
        if not event or not session_name:
            return
        self.set_compare_enabled(False)
        self.run("session", f"Loading {event['name']} {session_name} "
                            f"(the first load of a session can take a minute)...",
                 self.session_loader, int(self.year.currentText()), event["round"], session_name,
                 on_done=self.on_session_loaded)

    def on_session_loaded(self, session):
        self.session = session
        drivers = drivers_in_order(session)
        for combo in (self.driver_a, self.driver_b):
            combo.blockSignals(True)
            combo.clear()
            combo.addItems(drivers)
            combo.blockSignals(False)
        if len(drivers) >= 2:
            self.driver_b.setCurrentIndex(1)
        self.fill_laps(self.lap_a, self.driver_a.currentText())
        self.fill_laps(self.lap_b, self.driver_b.currentText())
        self.set_compare_enabled(bool(drivers))
        if drivers:
            self.on_compare()  # show something straight away: top two, fastest laps

    def fill_laps(self, combo, driver):
        combo.clear()
        if not self.session or not driver:
            return
        combo.addItem("Fastest lap", None)
        for lap in lap_rows(self.session.laps, driver):
            if lap["lap_time"] is not None:  # laps without a time can't be compared
                combo.addItem(lap_choice_label(lap), lap["number"])

    def on_compare(self):
        drivers = [self.driver_a.currentText(), self.driver_b.currentText()]
        laps = [self.lap_a.currentData(), self.lap_b.currentData()]
        try:
            check_lap_choices(drivers, laps)
        except ValueError as error:
            self.show_error(str(error))
            return
        self.run("compare", f"Comparing {drivers[0]} and {drivers[1]}...", compare_laps,
                 self.session, drivers, laps, on_done=self.on_compared)

    def on_compared(self, comparison):
        if self.cursor:
            self.cursor.disconnect()
        _, axes = draw(comparison, fig=self.figure)
        self.cursor = HoverCursor(self.canvas, axes, comparison, self.hover_label.setText)
        self.canvas.draw()
        a, b = comparison.labels
        gap = comparison.gap
        hint = "Hover over the track or charts for details." \
            if comparison.track["X"].notna().any() else "Hover over the charts for details."
        self.hover_label.setText(f"{a if gap > 0 else b} faster by {abs(gap):.3f}s. {hint}")
        self.show_data_notes(comparison.data_notes)

    def show_data_notes(self, notes):
        """A short warning in the status bar, with every note in its tooltip."""
        if not notes:
            self.notes_label.clear()
            self.notes_label.setToolTip("")
            return
        count = f"{len(notes)} data notes (hover for all)" if len(notes) > 1 else "Data note"
        # Shortened with "…" if long, so the hover readout on the left keeps its room.
        text = self.notes_label.fontMetrics().elidedText(
            f"⚠ {count}: {notes[0]}", Qt.TextElideMode.ElideRight, NOTES_MAX_WIDTH)
        self.notes_label.setText(text)
        self.notes_label.setToolTip("\n".join(notes))

    # --- background work --------------------------------------------------------

    def run(self, kind, message, fn, *args, on_done):
        """Run fn in the background; only the newest request of each kind is used."""
        task = Task(fn, *args)
        self.latest[kind] = task
        self.tasks.add(task)

        def finished(handler):
            def handle(result):
                self.tasks.discard(task)
                if self.closed:  # e.g. closed during a long download; widgets are gone
                    return
                self.progress.setVisible(bool(self.tasks))
                if self.latest.get(kind) is task:
                    handler(result)
            return handle

        task.signals.done.connect(finished(on_done))
        task.signals.failed.connect(finished(self.show_error))
        self.hover_label.setText(message)
        self.progress.show()
        self.pool.start(task)

    def closeEvent(self, event):
        self.closed = True
        super().closeEvent(event)

    def show_error(self, message):
        self.hover_label.setText("")
        QMessageBox.warning(self, "F1 Deltaline", message)
        self.set_compare_enabled(self.session is not None)

    def show_placeholder(self, message):
        self.figure.clear()
        self.figure.text(0.5, 0.5, message, ha="center", va="center", color=MUTED, fontsize=14)
        self.canvas.draw_idle()


def row(*items):
    """A horizontal row of (label, widget) pairs and plain widgets."""
    layout = QHBoxLayout()
    for item in items:
        if isinstance(item, tuple):
            label, widget = item
            layout.addWidget(QLabel(label))
            layout.addWidget(widget)
        else:
            layout.addWidget(item)
    layout.addStretch(1)
    return layout


def dark_palette():
    role, group = QPalette.ColorRole, QPalette.ColorGroup
    palette = QPalette()
    colors = {role.Window: "#1e1e28", role.WindowText: TEXT, role.Base: BACKGROUND,
              role.AlternateBase: "#22222c", role.Text: TEXT, role.Button: "#2a2a36",
              role.ButtonText: TEXT, role.Highlight: "#3d5afe",
              role.HighlightedText: "#ffffff", role.ToolTipBase: "#2a2a36",
              role.ToolTipText: TEXT, role.PlaceholderText: MUTED}
    for color_role, color in colors.items():
        palette.setColor(color_role, QColor(color))
    palette.setColor(group.Disabled, role.Text, QColor(MUTED))
    palette.setColor(group.Disabled, role.ButtonText, QColor(MUTED))
    return palette


def main():
    # FastF1's data warnings are only noise in the terminal here; the ones that
    # affect a comparison are shown as data notes in the status bar instead.
    data.FASTF1_LOG_LEVEL = "ERROR"
    # Qt's event loop keeps Python from handling Ctrl+C, so it was ignored. Restore
    # the default, so Ctrl+C in the terminal quits straight away.
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setPalette(dark_palette())
    window = MainWindow()
    window.show()
    code = app.exec()
    if window.tasks:
        # Qt waits for background work before exiting. Stopping a FastF1 download
        # halfway could leave a broken file in its cache, so let it finish, and say so.
        print("Finishing a download before exiting, so the data cache stays intact "
              "(press Ctrl+C to quit now)...", flush=True)
    sys.exit(code)
