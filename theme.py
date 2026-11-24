"""The program's colours: dark, light, or old paper (warm sepia, like an archive), or
whichever of light and dark the computer uses. Every colour has a name here; the rest
of the program asks for names, never for colour codes.

The chart's colours in canvas.py (BACKGROUND, TEXT, ...) are QColor objects that other
modules import by name, so a theme change repaints them in place: everything holding
them follows without being told.
"""
from PySide6.QtGui import QColor, QPalette

THEMES = ("system", "dark", "light", "paper")
KEYS = ("background", "panel", "control", "text", "line", "frame", "highlight", "path", "portrait_light",
        "portrait_dark", "silhouette", "soft", "warn", "error", "divider", "selected_text", "disabled", "mark",
        "tile", "tile_text", "fan_father", "fan_mother", "card", "father_side", "mother_side", "shadow")

PALETTES = {
    "dark": {
        "background": "#2b2d31", "panel": "#232427", "control": "#34363b", "text": "#e8e8e8", "line": "#8f939b",
        "frame": "#a8acb3", "highlight": "#7fb2ff", "path": "#e6c06a", "portrait_light": "#5a5e66",
        "portrait_dark": "#3a3c42", "silhouette": "#25262a", "soft": "#a8acb3", "warn": "#e6c06a",
        "error": "#ff9c8f", "divider": "#44474d", "selected_text": "#10141a", "disabled": "#74777d",
        "mark": "#ffd24d", "tile": "#3a3d42", "tile_text": "#d6d8dc", "fan_father": "#3b4352",
        "fan_mother": "#4a3b4a", "card": "#32353a", "father_side": "#5b7fb8", "mother_side": "#b86b8f",
        "shadow": "#16171a",
    },
    "light": {
        "background": "#f6f6f4", "panel": "#ebedef", "control": "#dfe3e8", "text": "#1f2328", "line": "#7d838c",
        "frame": "#6b717a", "highlight": "#2862bd", "path": "#c07f00", "portrait_light": "#d6dae0",
        "portrait_dark": "#c3c9d1", "silhouette": "#9aa1ab", "soft": "#5b616b", "warn": "#865900",
        "error": "#c62828", "divider": "#c9ccd1", "selected_text": "#ffffff", "disabled": "#9aa0a6",
        "mark": "#e0a020", "tile": "#dde1e6", "tile_text": "#40464d", "fan_father": "#dbe4f3",
        "fan_mother": "#f3dde6", "card": "#ffffff", "father_side": "#3f6db3", "mother_side": "#b0507c",
        "shadow": "#b9bdc3",
    },
    "paper": {
        "background": "#f3ead6", "panel": "#e9dec4", "control": "#e0d2b2", "text": "#3a2c1e", "line": "#8c6b4a",
        "frame": "#7b5a3a", "highlight": "#9b4a1c", "path": "#b07a10", "portrait_light": "#d9c7a3",
        "portrait_dark": "#c4ae86", "silhouette": "#8f7652", "soft": "#6e5a44", "warn": "#7a4f00",
        "error": "#a3341d", "divider": "#c9b893", "selected_text": "#fff8ec", "disabled": "#a8977a",
        "mark": "#c0841a", "tile": "#e3d6b8", "tile_text": "#5a4630", "fan_father": "#e6d8b8",
        "fan_mother": "#ecd2c2", "card": "#faf4e6", "father_side": "#6f7d9a", "mother_side": "#a0646e",
        "shadow": "#cdbd98",
    },
}

current = "dark"


def resolve(name):
    """'system' becomes light or dark, as the computer is set; anything unknown is dark."""
    if name == "system":
        from PySide6.QtCore import Qt
        from PySide6.QtGui import QGuiApplication
        app = QGuiApplication.instance()
        scheme = app.styleHints().colorScheme() if app is not None else Qt.ColorScheme.Unknown
        return "light" if scheme == Qt.ColorScheme.Light else "dark"
    return name if name in PALETTES else "dark"


# How strong generated colours (initials, surnames) may be: calm on old paper, bolder on light.
SATURATION = {"dark": 55, "light": 70, "paper": 38}
LIGHTNESS = {"dark": 95, "light": 150, "paper": 140}


def soft_colour(hue):
    """A colour of this hue that sits quietly in the current theme."""
    return QColor.fromHsl(hue % 360, SATURATION[current], LIGHTNESS[current])


def hex(key):  # noqa: A001 - the name reads best at the call sites: theme.hex("soft").
    return PALETTES[current][key]


def colour(key):
    return QColor(PALETTES[current][key])


def apply(name, app=None):
    """Use a theme from now on: the chart's colours, the window colours, and the paper look's
    serif type for titles. Windows already open repaint when they next draw."""
    global current
    current = resolve(name)
    import canvas
    for constant, key in (("BACKGROUND", "background"), ("PANEL", "panel"), ("CONTROL", "control"),
                          ("TEXT", "text"), ("LINE", "line"), ("FRAME", "frame"), ("HIGHLIGHT", "highlight"),
                          ("PATH_COLOUR", "path"), ("PORTRAIT_LIGHT", "portrait_light"),
                          ("PORTRAIT_DARK", "portrait_dark"), ("SILHOUETTE", "silhouette")):
        getattr(canvas, constant).setRgba(QColor(hex(key)).rgba())  # In place: every holder follows.
    if app is not None:
        palette = QPalette()
        roles = {
            QPalette.ColorRole.Window: "panel", QPalette.ColorRole.WindowText: "text",
            QPalette.ColorRole.Base: "background", QPalette.ColorRole.AlternateBase: "panel",
            QPalette.ColorRole.Text: "text", QPalette.ColorRole.Button: "control",
            QPalette.ColorRole.ButtonText: "text", QPalette.ColorRole.ToolTipBase: "panel",
            QPalette.ColorRole.ToolTipText: "text", QPalette.ColorRole.Highlight: "highlight",
            QPalette.ColorRole.HighlightedText: "selected_text", QPalette.ColorRole.PlaceholderText: "soft",
            QPalette.ColorRole.Link: "highlight", QPalette.ColorRole.Light: "card",
            QPalette.ColorRole.Mid: "divider", QPalette.ColorRole.Dark: "shadow",
        }
        for role, key in roles.items():
            palette.setColor(role, colour(key))
        for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
            palette.setColor(QPalette.ColorGroup.Disabled, role, colour("disabled"))
        app.setPalette(palette)
    return current


def _outlined_style_class():
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QPen
    from PySide6.QtWidgets import QProxyStyle, QStyle

    class OutlinedStyle(QProxyStyle):
        """Fusion draws a check box's edge from the window colour: on a dark or pale
        window it all but disappears (1.1:1). An outline in the theme's line colour is
        drawn on top, so every check box and option button can be seen (at least 3:1)."""

        def drawPrimitive(self, element, option, painter, widget=None):
            super().drawPrimitive(element, option, painter, widget)
            if element not in (QStyle.PrimitiveElement.PE_IndicatorCheckBox,
                               QStyle.PrimitiveElement.PE_IndicatorRadioButton):
                return
            painter.save()
            painter.setRenderHint(painter.RenderHint.Antialiasing)
            painter.setPen(QPen(colour("line"), 1.2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            box = QRectF(option.rect).adjusted(0.6, 0.6, -0.6, -0.6)
            if element == QStyle.PrimitiveElement.PE_IndicatorRadioButton:
                painter.drawEllipse(box)
            else:
                painter.drawRoundedRect(box, 2, 2)
            painter.restore()

    return OutlinedStyle


def __getattr__(name):
    if name == "OutlinedStyle":  # Made on first use: theme.py is imported before Qt is ready.
        return _outlined_style_class()
    raise AttributeError(name)

