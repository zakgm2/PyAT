"""Writing a figure for a manuscript (figures/render.py): PNG/TIFF at the dpi asked, vector PDF/SVG with text that stays
text, no clock in a vector file, edits for the export only."""

import io
import os
import tempfile
import unittest
from pathlib import Path

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

    def test_a_word_said_twice_is_renamed_everywhere(self):
        fig = event_like_figure()
        fig.axes[0].set_xlabel("Time from Event (s)")
        written = fr.save_figure(fig, self.path("a.svg"), labels={"Time from Event (s)": "t"}, data=False)
        self.assertNotIn("Time from Event", Path(written[0]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
