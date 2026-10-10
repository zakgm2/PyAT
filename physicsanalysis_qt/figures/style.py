"""
figures/style.py
----------------
What every figure shares: the golden-ratio font sizes, and the colours a signal is drawn in unless it was given one.
"""

PHI = 1.6180339887  # golden ratio

# The colour a TDT signal is drawn in by default, by the key of the signal (PyAT's Plot menu uses these, and lets a
# person override them) and, for NIRS, by the name of the mean trace.
SIGNAL_COLORS = {
    "normalized": "blue",
    "main_driver": "#2E7D32",      # green — conventional for the probe/signal channel
    "isosbestic": "#7B1FA2",       # purple — conventional for the isosbestic control
}
NIRS_COLORS = {"Mean O2Hb": "#CC0000", "Mean HHb": "#0033CC", "Mean tHb": "#228B22"}
DEFAULT_COLOR = "#2196F3"          # the colour of a channel with no more specific one ("Signal")

_LABEL_PREFIXES = (("Normalized", SIGNAL_COLORS["normalized"]), ("Main Driver", SIGNAL_COLORS["main_driver"]),
                   ("Isosbestic", SIGNAL_COLORS["isosbestic"]), *NIRS_COLORS.items())


UNKNOWN_SIGNAL_COLOR = "#555555"   # a raw channel whose role the app has no colour for


def signal_color(key):
    """The colour a TDT signal is drawn in by its key in a recording's `signals` ("normalized", "main_driver", "isosbestic", or any
    other channel a block reports): what the app's Plot menu gives it unless the person picked another."""
    return SIGNAL_COLORS.get(key, UNKNOWN_SIGNAL_COLOR)


def channel_color(label):
    """The default colour for a channel known only by its name ("Normalized (dF/F)", "Main Driver (x465A)",
    "Mean O2Hb", ...): what PyAT draws it in unless the person chose another."""
    text = str(label)
    for prefix, color in _LABEL_PREFIXES:
        if text.startswith(prefix):
            return color
    return DEFAULT_COLOR


def fig_font_sizes(fig):
    """
    Return (title_fs, label_fs, legend_fs) using the golden ratio.

    Title scales linearly with the figure diagonal. Each tier down is
    title / phi, then title / phi^2. Anchor: 8x4 in diagonal (~8.94 in)
    -> title ~ 24 pt. Halved when the figure contains multiple subplots.
    """
    diag = (fig.get_figwidth() ** 2 + fig.get_figheight() ** 2) ** 0.5
    title_fs = max(8, round(diag * (24 / ((8**2 + 4**2) ** 0.5))))
    label_fs = max(6, round(title_fs / PHI))
    leg_fs = max(5, round(label_fs / PHI))
    if len(fig.axes) > 1:
        title_fs = max(6, title_fs // 2)
        label_fs = max(5, label_fs // 2)
        leg_fs = max(4, leg_fs // 2)
    return title_fs, label_fs, leg_fs
