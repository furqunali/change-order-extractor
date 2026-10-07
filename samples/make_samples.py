"""
Generate the two PDF samples (already committed; re-run to rebuild):

  co_215_digital_form.pdf  - clean digital PDF with a cost table (text layer)
  co_031_scanned.pdf       - image-only "scan": skewed, noisy, JPEG artefacts,
                             a handwritten-style note, NO text layer -> exercises
                             the vision path
"""

import io
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

HERE = Path(__file__).parent


def digital_form(path: Path):
    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(str(path), pagesize=letter, topMargin=48)
    meta = [
        ["Change Order No.", "CO-215", "Date", "08/12/2024"],
        ["Project", "Harbor View Medical Office Building", "", ""],
        ["Contractor", "Ironwood General Contractors", "Owner", "Harbor Health Systems"],
        ["Reason", "Owner Request", "Contract days", "+3"],
    ]
    costs = [
        ["Item", "Category", "Amount"],
        ["Install 2 additional exam-room sinks, Suite 210", "Labor", "$6,250.00"],
        ["Sinks, faucets, supply & waste piping", "Material", "$9,480.00"],
        ["Core drilling rig", "Equipment", "$1,100.00"],
        ["", "Subtotal", "$16,830.00"],
        ["", "OH&P 12%", "$2,019.60"],
        ["", "CHANGE ORDER TOTAL", "$18,849.60"],
    ]
    grid = TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                       ("FONTSIZE", (0, 0), (-1, -1), 9),
                       ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e8eef4"))])
    meta_t = Table(meta, colWidths=[95, 200, 85, 140])
    meta_t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                                ("FONTSIZE", (0, 0), (-1, -1), 9), ("SPAN", (1, 1), (3, 1))]))
    cost_t = Table(costs, colWidths=[290, 120, 110])
    cost_t.setStyle(grid)
    story = [
        Paragraph("CHANGE ORDER", styles["Title"]),
        meta_t, Spacer(1, 14),
        Paragraph("<b>Description of change:</b> Owner directs installation of two additional "
                  "hand-wash sinks in exam rooms 210-B and 210-C, including wall blocking, "
                  "supply and waste connections tied into existing risers.", styles["Normal"]),
        Spacer(1, 12), cost_t, Spacer(1, 14),
        Paragraph("Revised Substantial Completion: February 21, 2025", styles["Normal"]),
        Spacer(1, 24),
        Paragraph("Approved (Owner): Linda Cho &nbsp;&nbsp;&nbsp;&nbsp; "
                  "Contractor Representative: Marcus Bell", styles["Normal"]),
    ]
    doc.build(story)


SCAN_LINES = [
    ("CHANGE ORDER", 44),
    ("", 20),
    ("C.O. No: 031                         Date: 03/07/2025", 26),
    ("Project: Lakeside Apartments - Bldg C", 26),
    ("Contractor: Delgado & Sons Construction", 26),
    ("Owner: Lakeside Housing LLC", 26),
    ("", 20),
    ("Work: Replace 14 storm-damaged vinyl windows,", 26),
    ("units C-201 thru C-214, incl. flashing & trim.", 26),
    ("Cause: hail storm 02/26/25 (unforeseen damage)", 26),
    ("", 20),
    ("   Materials (windows, flashing) .... $ 7,840.00", 26),
    ("   Labor ............................ $ 3,960.00", 26),
    ("   ------------------------------------------", 26),
    ("   TOTAL ............................ $11,800.00", 26),
    ("", 20),
    ("Schedule: no time extension", 26),
    ("", 30),
    ("Approved by: R. Patel (Owner)", 26),
]


def scanned(path: Path, seed: int = 7):
    rng = random.Random(seed)
    w, h = 1275, 1650  # letter @ 150 dpi
    img = Image.new("L", (w, h), 250)
    draw = ImageDraw.Draw(img)

    def font(size, name):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            return ImageFont.load_default()

    y = 110
    for text, size in SCAN_LINES:
        draw.text((110 + rng.randint(-3, 3), y), text, fill=rng.randint(20, 60), font=font(size, "cour.ttf"))
        y += int(size * 1.55)
    # handwritten-style margin note
    draw.text((760, y + 10), "ok per RP - 3/7", fill=40, font=font(30, "segoesc.ttf"))

    for _ in range(9000):  # speckle noise
        draw.point((rng.randrange(w), rng.randrange(h)), fill=rng.randint(80, 200))
    img = img.filter(ImageFilter.GaussianBlur(0.8)).rotate(1.6, fillcolor=235, resample=Image.BICUBIC)

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=35)  # heavy compression artefacts
    Image.open(buf).convert("RGB").save(path, "PDF", resolution=150)


if __name__ == "__main__":
    digital_form(HERE / "co_215_digital_form.pdf")
    scanned(HERE / "co_031_scanned.pdf")
    print("wrote co_215_digital_form.pdf, co_031_scanned.pdf")
