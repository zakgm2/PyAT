"""The words on a figure that can be edited for an export (figures/labels.py): found in reading order, changed only
inside the export and put back after, and a legend edit renames the series so the data CSV agrees with the figure."""

import io
import unittest

import numpy as np
from matplotlib.figure import Figure

from physicsanalysis_qt.figures import data as fd
from physicsanalysis_qt.figures import labels as fl


def event_like_figure():
    """The shape of the Event PETH figure: a heatmap with a colour bar above a mean trace with its SEM band."""
    fig = Figure()
    heat, line = fig.subplots(2, 1)
    im = heat.imshow(np.arange(12.0).reshape(3, 4), aspect="auto", extent=[-2, 2, 3.5, 0.5])
    heat.set_ylabel("Trial")
    heat.pyat_panel = "Trials heatmap"
    fig.colorbar(im, ax=heat, label="Z-score")
    x = np.linspace(-2, 2, 20)
    line.plot(x, np.sin(x), label="Mean")
    line.fill_between(x, np.sin(x) - 0.1, np.sin(x) + 0.1, alpha=0.2, label="SEM")
    line.set_xlabel("Time from Event (s)")
    line.set_ylabel("Z-Score (Mode)")
    line.legend()
    line.pyat_panel = "Group trace"
    fig.suptitle("Event PETH — L1P")
    return fig


class TestFindingTheText(unittest.TestCase):
    def test_everything_worth_editing_is_found_in_reading_order(self):
        items = fl.text_items(event_like_figure())
        self.assertEqual([i.caption for i in items], [
            "Figure title",
            "Trials heatmap: Y label",
            "Group trace: X label", "Group trace: Y label", "Group trace: Legend 1", "Group trace: Legend 2",
            "Colour bar label"])
        self.assertEqual([i.text for i in items], [
            "Event PETH — L1P", "Trial", "Time from Event (s)", "Z-Score (Mode)", "Mean", "SEM", "Z-score"])

    def test_a_single_panel_needs_no_panel_prefix(self):
        fig = Figure()
        ax = fig.subplots()
        ax.plot([0, 1], [0, 1], label="signal")
        ax.set_title("A title")
        ax.set_xlabel("Time (s)")
        ax.legend()
        self.assertEqual([i.caption for i in fl.text_items(fig)], ["Title", "X label", "Legend 1"])

    def test_labels_nobody_set_are_not_offered(self):
        fig = Figure()
        ax = fig.subplots()
        ax.plot([0, 1], [0, 1])
        self.assertEqual(fl.text_items(fig), [])

    def test_left_and_right_titles_are_found(self):
        fig = Figure()
        ax = fig.subplots()
        ax.set_title("left one", loc="left")
        ax.set_title("right one", loc="right")
        self.assertEqual([(i.caption, i.text) for i in fl.text_items(fig)], [("Title (left)", "left one"), ("Title (right)", "right one")])


class TestEditingInsideAnExportOnly(unittest.TestCase):
    def test_the_text_is_new_inside_and_old_after(self):
        fig = event_like_figure()
        items = {i.caption: i for i in fl.text_items(fig)}
        before = [i.text for i in items.values()]
        with fl.edited_texts({items["Figure title"]: "My title", items["Group trace: X label"]: "Time (s)"}):
            self.assertEqual(fig._suptitle.get_text(), "My title")
            self.assertEqual(fig.axes[1].get_xlabel(), "Time (s)")
        self.assertEqual([i.text for i in items.values()], before)
        self.assertEqual(fig.axes[1].get_xlabel(), "Time from Event (s)")

    def test_it_is_put_back_even_if_the_export_fails(self):
        fig = event_like_figure()
        item = fl.text_items(fig)[0]
        with self.assertRaises(RuntimeError):
            with fl.edited_texts({item: "temporary"}):
                raise RuntimeError("disk full")
        self.assertEqual(item.text, "Event PETH — L1P")

    def test_nothing_else_about_the_text_changes(self):
        fig = event_like_figure()
        item = next(i for i in fl.text_items(fig) if i.caption == "Group trace: X label")
        item.artist.set_fontsize(17)
        item.artist.set_fontweight("bold")
        with fl.edited_texts({item: "Time (s)"}):
            self.assertEqual((item.artist.get_fontsize(), item.artist.get_fontweight()), (17, "bold"))

    def test_an_unchanged_text_is_left_alone(self):
        fig = event_like_figure()
        item = fl.text_items(fig)[0]
        with fl.edited_texts({item: item.text}):
            self.assertEqual(item.text, "Event PETH — L1P")

    def test_the_edit_reaches_the_rendered_file(self):
        fig = event_like_figure()
        item = next(i for i in fl.text_items(fig) if i.caption == "Group trace: X label")

        def svg():
            buf = io.StringIO()
            with __import__("matplotlib").rc_context({"svg.fonttype": "none"}):
                fig.savefig(buf, format="svg")
            return buf.getvalue()
        self.assertIn("Time from Event (s)", svg())
        with fl.edited_texts({item: "Elapsed (s)"}):
            edited = svg()
        self.assertIn("Elapsed (s)", edited)
        self.assertNotIn("Time from Event (s)", edited)
        self.assertIn("Time from Event (s)", svg())


class TestLegendEditsRenameTheSeries(unittest.TestCase):
    def test_the_data_csv_calls_a_series_what_the_legend_now_does(self):
        fig = event_like_figure()
        mean = next(i for i in fl.text_items(fig) if i.text == "Mean")
        sem = next(i for i in fl.text_items(fig) if i.text == "SEM")
        with fl.edited_texts({mean: "Average", sem: "± SEM"}):
            data = fd.figure_tables(fig)["data"]
            self.assertEqual(sorted(data["series"].unique()), ["Average", "± SEM"])
            self.assertEqual(sorted(data["kind"].unique()), ["band", "line"])
        data = fd.figure_tables(fig)["data"]
        self.assertEqual(sorted(data["series"].unique()), ["Mean", "SEM"])

    def test_the_axis_labels_in_the_data_csv_follow_edits_too(self):
        fig = event_like_figure()
        item = next(i for i in fl.text_items(fig) if i.caption == "Group trace: X label")
        with fl.edited_texts({item: "Elapsed (s)"}):
            self.assertEqual(set(fd.figure_tables(fig)["data"]["x_label"]), {"Elapsed (s)"})

    def test_the_figure_data_names_panels_and_labels_the_heatmap_rows(self):
        fig = event_like_figure()
        fig.axes[0].pyat_row_labels = [4, 1, 9]
        tables = fd.figure_tables(fig)
        self.assertEqual(set(tables["data"]["panel"]), {"Group trace"})
        self.assertEqual(set(tables["image_1"]["panel"]), {"Trials heatmap"})
        self.assertEqual(list(tables["image_1"]["row"]), [4, 1, 9])


if __name__ == "__main__":
    unittest.main()
