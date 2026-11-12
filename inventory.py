# inventory.py
# Helpers for the item tables: building them, tidying them, and combining rooms.

import pandas as pd
import streamlit as st

from ai_scanner import CATEGORIES

# The columns in each room's editable table, in order
COLUMNS = ["Item", "Qty", "Category", "Value each (NZD)", "AI confidence"]

# Show money as $1,234
MONEY = st.column_config.NumberColumn(format="$%.0f")


def items_to_table(items):
    """Turn the AI's list of items into a table (DataFrame)."""
    rows = [
        {
            "Item": item["name"],
            "Qty": item["quantity"],
            "Category": item["category"],
            "Value each (NZD)": item["unit_value_nzd"],
            "AI confidence": item["confidence"],
        }
        for item in items
    ]
    return pd.DataFrame(rows, columns=COLUMNS)


def clean_table(df):
    """Tidy up the user's edits: remove blank rows, fill gaps, and work out totals."""
    df = df.copy()

    # Drop rows with no item name (e.g. a new row the user started but left empty)
    df = df.dropna(subset=["Item"])
    df = df[df["Item"].astype(str).str.strip() != ""]

    # Make sure numbers are sensible numbers
    df["Qty"] = pd.to_numeric(df["Qty"], errors="coerce").fillna(1).clip(lower=1).astype(int)
    df["Value each (NZD)"] = pd.to_numeric(df["Value each (NZD)"], errors="coerce").fillna(0).clip(lower=0)

    # Fill in blanks for rows the user added themselves
    df["Category"] = df["Category"].fillna("Other")
    df["AI confidence"] = df["AI confidence"].fillna("added by you")

    # Work out the total for each row
    df["Total (NZD)"] = df["Qty"] * df["Value each (NZD)"]
    return df.reset_index(drop=True)


def editor_column_config():
    """The rules for each column in an editable item table."""
    return {
        "Item": st.column_config.TextColumn("Item", required=True),
        "Qty": st.column_config.NumberColumn("Qty", min_value=1, step=1, default=1),
        "Category": st.column_config.SelectboxColumn(
            "Category", options=CATEGORIES, default="Other", required=True
        ),
        "Value each (NZD)": st.column_config.NumberColumn(
            "Value each (NZD)", min_value=0, step=10, format="$%.0f", default=0
        ),
        "AI confidence": st.column_config.TextColumn("AI confidence", disabled=True),
    }


def combine_rooms(rooms):
    """
    Takes a list of (room name, cleaned table) pairs and stacks them
    into one big table with a 'Room' column at the front.
    """
    frames = []
    for name, df in rooms:
        df = df.copy()
        df.insert(0, "Room", name)
        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["Room"] + COLUMNS + ["Total (NZD)"])
    return pd.concat(frames, ignore_index=True)
