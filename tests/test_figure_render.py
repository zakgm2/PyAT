"""Writing a figure for a manuscript (figures/render.py): PNG/TIFF at the dpi asked, vector PDF/SVG with text that stays
text, no clock in a vector file, edits for the export only."""

import io
import os
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from physicsanalysis_qt.figures import labels as figure_labels
from physicsanalysis_qt.figures import render as fr

from tests.test_figure_labels import event_like_figure


def render(fig, **kw):
    buf = io.BytesIO()
    fr.render_figure(fig, buf, **kw)
    return buf.getvalue()


class TestRenderFigure(unittest.TestCase):
    def test_a_png_has_the_pixels_the_dpi_asks_for_and_says_what_dpi_it_is(self):
        fig = event_like_figure()
        low, high = (Image.open(io.BytesIO(render(fig, fmt="png", dpi=dpi))) for dpi in (100, 300))
        self.assertAlmostEqual(high.width / low.width, 3.0, delta=0.02)
        self.assertAlmostEqual(high.info["dpi"][0], 300, delta=0.5)
        self.assertTrue(high.info["Software"].startswith("PyAT "))                        # PyAT's name unless the program gives its own
        with_name = Image.open(io.BytesIO(render(fig, fmt="png", dpi=100, software="PyAT 9.9")))
        self.assertEqual(with_name.info["Software"], "PyAT 9.9")

    def test_a_tiff_is_a_compressed_tiff_at_that_dpi(self):
        image = Image.open(io.BytesIO(render(event_like_figure(), fmt="tiff", dpi=600)))
        self.assertEqual(image.format, "TIFF")
        self.assertEqual(image.info["compression"], "tiff_lzw")
        self.assertAlmostEqual(float(image.info["dpi"][0]), 600, delta=1)

    def test_a_pdf_keeps_its_text_as_embedded_truetype_unless_told_to_outline_it(self):
        fig = event_like_figure()
        editable = render(fig, fmt="pdf")
        self.assertTrue(editable.startswith(b"%PDF-"))
        self.assertIn(b"FontFile2", editable)
        self.assertNotIn(b"/Type3", editable)
        outlined = render(fig, fmt="pdf", editable_text=False)
        self.assertIn(b"/Type3", outlined)

    def test_an_svg_keeps_its_words_as_words_unless_told_to_outline_them(self):
        fig = event_like_figure()
        editable = render(fig, fmt="svg").decode("utf-8")
        self.assertIn(">Time from Event (s)</text>", editable)
        self.assertNotIn("<text", render(fig, fmt="svg", editable_text=False).decode("utf-8"))      # glyph outlines instead

    def test_the_same_figure_exported_twice_is_the_same_vector_file(self):
        fig = event_like_figure()
        for fmt in ("pdf", "svg"):
            with self.subTest(fmt=fmt):
                self.assertEqual(render(fig, fmt=fmt), render(fig, fmt=fmt))

    def test_a_vector_file_carries_no_date(self):
        pdf = render(event_like_figure(), fmt="pdf")
        self.assertNotIn(b"CreationDate", pdf)
        self.assertIn(b"PyAT", pdf)
        svg = render(event_like_figure(), fmt="svg").decode("utf-8")
        self.assertNotIn("<dc:date>", svg)

    def test_a_transparent_background_is_transparent_and_the_default_is_not(self):
        fig = event_like_figure()
        see_through = Image.open(io.BytesIO(render(fig, fmt="png", dpi=50, transparent=True))).convert("RGBA")
        opaque = Image.open(io.BytesIO(render(fig, fmt="png", dpi=50))).convert("RGBA")
        self.assertEqual(see_through.getpixel((0, 0))[3], 0)
        self.assertEqual(opaque.getpixel((0, 0)), (255, 255, 255, 255))

    def test_the_figure_is_trimmed_to_its_content_with_a_margin(self):
        fig = event_like_figure()
        full = fig.get_size_inches()
        written = Image.open(io.BytesIO(render(fig, fmt="png", dpi=100)))
        self.assertLessEqual(written.width, full[0] * 100 + 2)
        self.assertLessEqual(written.height, full[1] * 100 + 2)

    def test_edits_are_in_the_file_and_gone_from_the_figure(self):
        fig = event_like_figure()
        item = next(i for i in figure_labels.text_items(fig) if i.caption == "Group trace: X label")
        edited = render(fig, fmt="svg", edits={item: "Elapsed (s)"}).decode("utf-8")
        self.assertIn("Elapsed (s)", edited)
        self.assertEqual(fig.axes[1].get_xlabel(), "Time from Event (s)")

    def test_notes_say_how_the_file_was_made_and_what_was_edited(self):
        fig = event_like_figure()
        item = next(i for i in figure_labels.text_items(fig) if i.caption == "Figure title")
        png = fr.figure_notes({"format": "png", "dpi": 600, "transparent": True, "editable_text": True}, {item: "New"})
        self.assertEqual(png[0], "Figure exported as PNG image at 600 dpi, transparent background")
        self.assertEqual(png[1], "Label edited (Figure title): 'Event PETH — L1P' -> 'New'")
        pdf = fr.figure_notes({"format": "pdf", "dpi": 300, "transparent": False, "editable_text": False}, {})
        self.assertEqual(pdf, ["Figure exported as PDF (vector), text converted to outlines"])


class TestSize(unittest.TestCase):
    """render_figure(size=...): the figure written at exactly the size asked, laid out again to fit it, and put back afterwards."""

    def test_a_png_or_tiff_has_exactly_the_pixels_the_size_and_dpi_give(self):
        fig = event_like_figure()
        for fmt in ("png", "tiff"):
            for size, dpi in (((3.35, 2.3), 300), ((12.0, 4.0), 200), ((6.0, 6.0), 100), ((2.3, 4.1), 300), ((1.0, 30.0), 72)):
                with self.subTest(fmt=fmt, size=size, dpi=dpi):
                    image = Image.open(io.BytesIO(render(fig, fmt=fmt, dpi=dpi, size=size)))
                    self.assertEqual(image.size, (round(size[0] * dpi), round(size[1] * dpi)))            # (2.3 x 300 is 689.99999 as a float: still 690)

    def test_without_a_size_the_figure_is_trimmed_to_its_content_as_before(self):
        fig = event_like_figure()
        self.assertEqual(render(fig, fmt="png", dpi=100), render(fig, fmt="png", dpi=100, size=None))
        self.assertNotEqual(render(fig, fmt="png", dpi=100), render(fig, fmt="png", dpi=100, size=tuple(fig.get_size_inches())))

    def test_a_pdf_page_and_an_svg_are_that_size_too(self):
        fig = event_like_figure()
        pdf = render(fig, fmt="pdf", size=(5.0, 3.0)).decode("latin-1")
        box = [float(v) for v in re.search(r"/MediaBox \[([^\]]*)\]", pdf).group(1).split()]
        self.assertEqual(box, [0.0, 0.0, 360.0, 216.0])                                                  # points: 72 to the inch
        svg = render(fig, fmt="svg", size=(5.0, 3.0)).decode("utf-8")
        self.assertRegex(svg, r'width="360(\.0+)?pt"')
        self.assertRegex(svg, r'height="216(\.0+)?pt"')

    def test_the_figure_is_put_back_exactly_as_it_was(self):
        fig = event_like_figure()
        fig.set_size_inches(7.3, 4.1)
        before = ([tuple(ax.get_position().bounds) for ax in fig.axes], tuple(fig.get_size_inches()), fig.get_layout_engine().__class__)
        render(fig, fmt="png", dpi=100, size=(3.0, 2.0))
        render(fig, fmt="png", dpi=100, size=(20.0, 5.0))
        self.assertEqual(([tuple(ax.get_position().bounds) for ax in fig.axes], tuple(fig.get_size_inches()), fig.get_layout_engine().__class__), before)

    def test_it_is_put_back_when_writing_fails(self):
        fig = event_like_figure()
        before = ([tuple(ax.get_position().bounds) for ax in fig.axes], tuple(fig.get_size_inches()))
        with mock.patch.object(type(fig), "savefig", side_effect=OSError("disk full")), self.assertRaises(OSError):
            fr.render_figure(fig, io.BytesIO(), size=(3.0, 2.0))
        self.assertEqual(([tuple(ax.get_position().bounds) for ax in fig.axes], tuple(fig.get_size_inches())), before)

    def test_it_is_laid_out_again_so_nothing_is_cut_off_at_a_small_or_a_wide_size(self):
        fig = event_like_figure()
        for size in ((3.0, 2.2), (14.0, 3.0), (5.0, 9.0)):
            with self.subTest(size=size), fr._sized(fig, size, 100, True):
                fig.canvas.draw()
                tight, page = fig.get_tightbbox(), fig.bbox_inches
                self.assertGreaterEqual(tight.x0, page.x0 - 0.02)
                self.assertGreaterEqual(tight.y0, page.y0 - 0.02)
                self.assertLessEqual(tight.x1, page.x1 + 0.02)
                self.assertLessEqual(tight.y1, page.y1 + 0.02)

    def test_a_figure_with_a_layout_engine_of_its_own_keeps_it(self):
        from matplotlib.figure import Figure
        fig = Figure(layout="constrained")
        fig.subplots(2, 1)[1].set_xlabel("Time (s)")
        image = Image.open(io.BytesIO(render(fig, fmt="png", dpi=100, size=(4.0, 7.0))))
        self.assertEqual(image.size, (400, 700))
        self.assertEqual(type(fig.get_layout_engine()).__name__, "ConstrainedLayoutEngine")

    def test_a_window_showing_the_figure_is_not_resized(self):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        fig = event_like_figure()
        canvas = FigureCanvasQTAgg(fig)
        canvas.resize(520, 340)
        app.processEvents()
        shown = (canvas.width(), canvas.height())
        render(fig, fmt="png", dpi=100, size=(9.0, 2.0))
        app.processEvents()
        self.assertEqual((canvas.width(), canvas.height()), shown)
        canvas.deleteLater()

    def test_a_size_that_is_not_two_numbers_or_is_out_of_range_is_refused(self):
        fig = event_like_figure()
        for bad in ((5.0,), (5.0, 3.0, 1.0), ("a", "b"), 5.0, (0.5, 3.0), (3.0, 31.0), (float("nan"), 3.0), (float("inf"), 3.0), (-2.0, 3.0)):
            with self.subTest(bad), self.assertRaisesRegex(ValueError, "size must be"):
                render(fig, fmt="png", dpi=100, size=bad)

    def test_a_raster_file_with_too_many_pixels_is_refused_and_a_vector_file_is_not(self):
        fig = event_like_figure()
        with self.assertRaisesRegex(ValueError, "megapixels; the most a file may have is 120"):
            render(fig, fmt="png", dpi=1200, size=(30.0, 30.0))
        self.assertEqual(fr.checked_size((30.0, 30.0), "pdf", 1200), (30.0, 30.0))
        self.assertEqual(fr.checked_size((10.0, 10.0), "png", 1000), (10.0, 10.0))                       # exactly 100 megapixels
        self.assertIsNone(fr.checked_size(None))

    def test_the_notes_say_the_size_that_was_set(self):
        notes = fr.figure_notes({"format": "png", "dpi": 300, "transparent": False, "editable_text": True, "size": (6.0, 4.25)}, {})
        self.assertEqual(notes, ["Figure exported as PNG image at 300 dpi, size set to 6.00 x 4.25 in"])
        self.assertEqual(fr.figure_notes({"format": "png", "dpi": 300, "transparent": False, "editable_text": True}, {}),
                         ["Figure exported as PNG image at 300 dpi"])


def points_figure():
    """A scatter of points, a line drawn with markers, an error bar, a plain line: and a legend naming them."""
    import numpy as np
    from matplotlib.figure import Figure
    fig = Figure(figsize=(6, 4))
    ax = fig.subplots()
    x = np.arange(6.0)
    ax.scatter(x, x ** 2, s=30, label="peaks")
    ax.plot(x, x, marker="o", markersize=5, label="marked")
    ax.errorbar(x, x + 3, yerr=0.4, fmt="s", markersize=4, capsize=3, label="spread")
    ax.plot(x, x * 0.5, label="plain")
    ax.legend()
    return fig


def sizes_of(fig):
    """(scatter sizes, marker sizes of the marked lines, marker sizes of the caps, the plain line's marker, and the legend handles' sizes)."""
    ax = fig.axes[0]
    scatter = ax.collections[0].get_sizes().tolist()
    marked = [line.get_markersize() for line in ax.lines if line.get_label() == "marked"]
    caps = [cap.get_markersize() for container in ax.containers for cap in container.lines[1]]
    plain = [line.get_marker() for line in ax.lines if line.get_label() == "plain"]
    handles = [(h.get_sizes().tolist() if hasattr(h, "get_sizes") else h.get_markersize()) for h in ax.get_legend().legend_handles
               if hasattr(h, "get_sizes") or (hasattr(h, "get_marker") and h.get_marker() not in (None, "None"))]
    return scatter, marked, caps, plain, handles


class TestPointSize(unittest.TestCase):
    def seen_while_writing(self, fig, scale):
        seen = {}
        original = fig.savefig

        def spy(*args, **kwargs):
            seen["during"] = sizes_of(fig)
            return original(*args, **kwargs)

        with mock.patch.object(fig, "savefig", spy):
            render(fig, fmt="png", dpi=100, point_scale=scale)
        return seen["during"]

    def test_the_points_are_that_many_times_as_large_while_the_figure_is_written(self):
        fig = points_figure()
        before = sizes_of(fig)
        scatter, marked, caps, plain, handles = self.seen_while_writing(fig, 2.0)
        self.assertEqual(scatter, [120.0])                                                       # a scatter point's size is its area: twice as wide is four times
        self.assertEqual(marked, [10.0])
        self.assertEqual(plain, ["None"])                                                        # a line with no markers has none to resize
        self.assertEqual(caps, before[2])                                                        # the caps of an error bar are not points
        self.assertIn([120.0], handles)                                                          # the legend shows the points as they are written
        self.assertIn(10.0, handles)

    def test_afterwards_everything_is_as_it_was_drawn_on_screen(self):
        fig = points_figure()
        before = sizes_of(fig)
        render(fig, fmt="png", dpi=100, point_scale=3.0)
        self.assertEqual(sizes_of(fig), before)

    def test_even_if_writing_fails_they_are_put_back(self):
        fig = points_figure()
        before = sizes_of(fig)
        with mock.patch.object(fig, "savefig", side_effect=RuntimeError("disk full")):
            with self.assertRaises(RuntimeError):
                render(fig, fmt="png", dpi=100, point_scale=2.0)
        self.assertEqual(sizes_of(fig), before)

    def test_smaller_works_too_and_as_drawn_changes_nothing(self):
        fig = points_figure()
        scatter, marked, *_ = self.seen_while_writing(fig, 0.5)
        self.assertEqual((scatter, marked), ([7.5], [2.5]))
        self.assertEqual(render(fig, fmt="png", dpi=100, point_scale=1.0), render(fig, fmt="png", dpi=100))
        self.assertEqual(render(fig, fmt="png", dpi=100, point_scale=None), render(fig, fmt="png", dpi=100))

    def test_larger_points_make_a_different_picture(self):
        fig = points_figure()
        self.assertNotEqual(render(fig, fmt="png", dpi=100, point_scale=3.0), render(fig, fmt="png", dpi=100))
        self.assertNotEqual(render(fig, fmt="pdf", point_scale=3.0), render(fig, fmt="pdf"))

    def test_a_figure_says_whether_it_has_points(self):
        from physicsanalysis_qt import figures
        self.assertTrue(figures.has_points(points_figure()))
        self.assertFalse(figures.has_points(event_like_figure()))                                # a heatmap and a line: nothing to resize
        from matplotlib.figure import Figure
        plain = Figure()
        plain.subplots().plot([0, 1], [0, 1])
        self.assertFalse(figures.has_points(plain))
        self.assertEqual(len(fr.figure_points(points_figure())), 5)                             # the scatter, the marked line, the error bar's line, and the two the legend shows

    def test_a_size_that_is_not_a_sensible_one_is_refused_before_anything_is_written(self):
        for bad in (0.05, 11.0, float("nan"), "big", 0):
            with self.subTest(bad), self.assertRaisesRegex(ValueError, "point_scale"):
                fr.checked_point_scale(bad)
        self.assertIsNone(fr.checked_point_scale(None))
        self.assertEqual(fr.checked_point_scale("1.5"), 1.5)
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "f.png")
            with self.assertRaisesRegex(ValueError, "point_scale"):
                fr.save_figure(points_figure(), path, point_scale=99)
            self.assertFalse(os.path.exists(path))

    def test_the_provenance_notes_say_it(self):
        notes = fr.figure_notes({"format": "png", "dpi": 300, "transparent": False, "editable_text": True, "point_scale": 1.5}, {})
        self.assertEqual(notes[0], "Figure exported as PNG image at 300 dpi, points drawn at 150% of their size")
        self.assertNotIn("points", fr.figure_notes({"format": "png", "dpi": 300, "transparent": False, "editable_text": True}, {})[0])

    def test_save_figure_writes_what_the_dialog_does(self):
        with tempfile.TemporaryDirectory() as folder:
            a, b = os.path.join(folder, "a.png"), os.path.join(folder, "b.png")
            fr.save_figure(points_figure(), a, dpi=100, data=False, point_scale=2.5)
            fr.save_figure(points_figure(), b, dpi=100, data=False)
            self.assertNotEqual(Path(a).read_bytes(), Path(b).read_bytes())
            self.assertEqual(Path(a).read_bytes(), render(points_figure(), fmt="png", dpi=100, point_scale=2.5, software=f"PyAT {fr.__version__}"))


class TestSaveFigure(unittest.TestCase):
    """save_figure(): what Export Figure does around render_figure — the format from the file name, the data CSVs beside the
    figure, words renamed for the file only."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pyat-save-")
        self.addCleanup(__import__("shutil").rmtree, self.tmp, True)
        self.fig = event_like_figure()

    def path(self, name):
        return os.path.join(self.tmp, name)

    def test_it_writes_the_figure_and_the_data_behind_it_and_lists_both(self):
        written = fr.save_figure(self.fig, self.path("peth.png"))
        self.assertEqual([os.path.basename(p) for p in written], ["peth.png", "peth_data.csv", "peth_image_1.csv"])    # a heatmap has its own CSV
        self.assertTrue(all(os.path.isfile(p) for p in written))

    def test_the_data_can_be_left_out(self):
        written = fr.save_figure(self.fig, self.path("peth.png"), data=False)
        self.assertEqual([os.path.basename(p) for p in written], ["peth.png"])
        self.assertEqual(sorted(os.listdir(self.tmp)), ["peth.png"])

    def test_the_format_is_the_extensions(self):
        for name, magic in (("a.png", bytes([137, 80, 78, 71])), ("a.pdf", b"%PDF-"), ("a.svg", b"<?xml"), ("a.tif", b"II*\x00"), ("a.TIFF", b"II*\x00")):
            with self.subTest(name=name):
                fr.save_figure(self.fig, self.path(name), data=False)
                self.assertEqual(Path(self.path(name)).read_bytes()[:len(magic)], magic)

    def test_fmt_says_the_format_when_the_name_does_not(self):
        fr.save_figure(self.fig, self.path("figure"), fmt="pdf", data=False)
        self.assertEqual(Path(self.path("figure")).read_bytes()[:5], b"%PDF-")

    def test_a_format_the_dialog_does_not_offer_is_refused_before_anything_is_written(self):
        with self.assertRaisesRegex(ValueError, "formats are png, tiff .*pdf and svg"):
            fr.save_figure(self.fig, self.path("a.jpg"))
        self.assertEqual(os.listdir(self.tmp), [])

    def test_the_dpi_has_the_dialogs_limits(self):
        for dpi in (71, 1201):
            with self.assertRaisesRegex(ValueError, "dpi must be between 72 and 1200"):
                fr.save_figure(self.fig, self.path("a.png"), dpi=dpi)
        low = Image.open(io.BytesIO(Path(fr.save_figure(self.fig, self.path("low.png"), dpi=72, data=False)[0]).read_bytes()))
        self.assertAlmostEqual(low.info["dpi"][0], 72, delta=0.5)

    def test_the_folder_is_made_if_it_is_not_there(self):
        written = fr.save_figure(self.fig, self.path(os.path.join("figures", "fig2", "a.png")), data=False)
        self.assertTrue(os.path.isfile(written[0]))

    def test_it_is_the_file_render_figure_writes(self):
        out = self.path("a.png")
        fr.save_figure(self.fig, out, dpi=200, software="PyAT 9.9", data=False)
        self.assertEqual(Path(out).read_bytes(), render(self.fig, fmt="png", dpi=200, software="PyAT 9.9"))

    def test_words_are_renamed_in_the_file_and_in_its_data_and_not_in_the_figure(self):
        written = fr.save_figure(self.fig, self.path("a.svg"), labels={"Time from Event (s)": "Elapsed (s)", "Mean": "Average"})
        self.assertIn("Elapsed (s)", Path(written[0]).read_text(encoding="utf-8"))
        data = Path(written[1]).read_text(encoding="utf-8")
        self.assertIn("Average", data)
        self.assertNotIn("Mean", data)
        self.assertEqual(self.fig.axes[1].get_xlabel(), "Time from Event (s)")
        self.assertEqual([t.get_text() for t in self.fig.axes[1].get_legend().get_texts()], ["Mean", "SEM"])

    def test_a_word_the_figure_does_not_say_is_an_error_that_says_what_it_does(self):
        with self.assertRaisesRegex(ValueError, r"does not say 'Time frm Event'.*it says:.*'Time from Event \(s\)'"):
            fr.save_figure(self.fig, self.path("a.png"), labels={"Time frm Event": "x"})
        self.assertEqual(os.listdir(self.tmp), [])

    def test_a_size_is_the_files_size_and_a_bad_one_is_refused_before_anything_is_written(self):
        written = fr.save_figure(self.fig, self.path("sized.png"), dpi=200, size=(4.0, 2.5), data=False)
        with Image.open(written[0]) as image:
            self.assertEqual(image.size, (800, 500))
        with self.assertRaisesRegex(ValueError, "size must be"):
            fr.save_figure(self.fig, self.path("bad.png"), size=(40.0, 2.0))
        with self.assertRaisesRegex(ValueError, "megapixels"):
            fr.save_figure(self.fig, self.path("huge.png"), dpi=1200, size=(30.0, 30.0))
        self.assertEqual(sorted(os.listdir(self.tmp)), ["sized.png"])

    def test_a_word_said_twice_is_renamed_everywhere(self):
        fig = event_like_figure()
        fig.axes[0].set_xlabel("Time from Event (s)")
        written = fr.save_figure(fig, self.path("a.svg"), labels={"Time from Event (s)": "t"}, data=False)
        self.assertNotIn("Time from Event", Path(written[0]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
