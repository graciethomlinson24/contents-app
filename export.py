# export.py
# Turns the house list into files people can send to their insurer: CSV and PDF.

import io
from datetime import datetime

from fpdf import FPDF
from PIL import Image

DISCLAIMER = (
    "Values are rough AI-generated estimates of replacement cost new in New Zealand, "
    "reviewed and edited by the person who made this list. "
    "They are not an official or professional valuation."
)

# The PDF's built-in font can't show some "fancy" characters, so we swap them for plain ones
REPLACEMENTS = {
    "–": "-",   # en dash
    "—": "-",   # em dash
    "‘": "'",   # curly quotes
    "’": "'",
    "“": '"',
    "”": '"',
    "•": "-",   # bullet
    "×": "x",   # multiplication sign
    "…": "...", # ellipsis
    "′": "'",   # prime (feet)
    "″": '"',   # double prime (inches)
}


def safe(text):
    """Make text safe for the PDF font (anything it can't show becomes '?')."""
    text = str(text)
    for fancy, plain in REPLACEMENTS.items():
        text = text.replace(fancy, plain)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def money(value):
    """Format a number as money, e.g. 1234.5 -> $1,235"""
    return f"${value:,.0f}"


# ---------- CSV ----------

def make_csv(all_items):
    """Turn the combined table into CSV bytes (opens nicely in Excel and Google Sheets)."""
    return all_items.to_csv(index=False).encode("utf-8-sig")


# ---------- PDF ----------

class InventoryPDF(FPDF):
    """A PDF with a footer on every page."""

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120)
        self.cell(0, 5, f"Rough AI estimates - not an official valuation.     Page {self.page_no()} of {{nb}}", align="C")
        self.set_text_color(0)


def add_photo(pdf, jpeg_bytes, max_w=120, max_h=85):
    """Add a photo, centred and scaled to fit inside max_w x max_h millimetres."""
    width_px, height_px = Image.open(io.BytesIO(jpeg_bytes)).size
    scale = min(max_w / width_px, max_h / height_px)
    w, h = width_px * scale, height_px * scale
    x = (pdf.w - w) / 2
    pdf.image(io.BytesIO(jpeg_bytes), x=x, w=w, h=h)
    pdf.ln(4)


def heading(pdf, text, size=14):
    pdf.set_font("Helvetica", "B", size)
    pdf.cell(0, 9, safe(text), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)


def make_pdf(rooms, owner_name=""):
    """
    rooms is a list of dictionaries: {"room": name, "photo": jpeg bytes, "items": cleaned table}
    Returns the finished PDF as bytes.
    """
    pdf = InventoryPDF(format="A4")
    pdf.set_auto_page_break(auto=True, margin=18)

    # ----- Page 1: title, disclaimer and summary -----
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 22)
    pdf.cell(0, 12, "Home Contents Inventory", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 10)
    if owner_name.strip():
        pdf.cell(0, 6, safe(f"Prepared by: {owner_name.strip()}"), new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Date: {datetime.now():%d %B %Y}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Disclaimer in a yellow box
    pdf.set_fill_color(255, 243, 205)
    pdf.set_font("Helvetica", "B", 9)
    pdf.multi_cell(0, 5, safe("IMPORTANT: " + DISCLAIMER), border=1, fill=True,
                   padding=2, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Summary numbers
    grand_total = sum(r["items"]["Total (NZD)"].sum() for r in rooms)
    item_count = sum(int(r["items"]["Qty"].sum()) for r in rooms)

    heading(pdf, "Summary")
    pdf.cell(0, 6, f"Rooms: {len(rooms)}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Items: {item_count}", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "B", 11)
    pdf.cell(0, 7, f"Estimated total replacement value: {money(grand_total)} NZD", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    # Totals by room
    pdf.set_font("Helvetica", "", 10)
    with pdf.table(col_widths=(100, 30, 60), text_align=("LEFT", "CENTER", "RIGHT"), line_height=7) as table:
        row = table.row()
        for title in ("Room", "Items", "Estimated value (NZD)"):
            row.cell(title)
        for r in rooms:
            row = table.row()
            row.cell(safe(r["room"]))
            row.cell(str(int(r["items"]["Qty"].sum())))
            row.cell(money(r["items"]["Total (NZD)"].sum()))

    # ----- One page per room: photo + item table -----
    for r in rooms:
        pdf.add_page()
        heading(pdf, r["room"], size=16)
        if r["photo"]:
            add_photo(pdf, r["photo"])
        else:
            pdf.cell(0, 6, "(Photo unavailable)", new_x="LMARGIN", new_y="NEXT")
            pdf.ln(2)

        items = r["items"]
        if items.empty:
            pdf.cell(0, 6, "No items listed for this room.", new_x="LMARGIN", new_y="NEXT")
            continue

        pdf.set_font("Helvetica", "", 9)
        with pdf.table(
            col_widths=(70, 12, 42, 30, 30),
            text_align=("LEFT", "CENTER", "LEFT", "RIGHT", "RIGHT"),
            line_height=6,
        ) as table:
            row = table.row()
            for title in ("Item", "Qty", "Category", "Value each", "Total"):
                row.cell(title)
            for _, item in items.iterrows():
                row = table.row()
                row.cell(safe(item["Item"]))
                row.cell(str(int(item["Qty"])))
                row.cell(safe(item["Category"]))
                row.cell(money(item["Value each (NZD)"]))
                row.cell(money(item["Total (NZD)"]))

        pdf.ln(3)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, f"Room total: {money(items['Total (NZD)'].sum())} NZD", align="R",
                 new_x="LMARGIN", new_y="NEXT")

    return bytes(pdf.output())
