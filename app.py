# app.py
# The main file for the Home Contents Scanner app.

import hashlib
import uuid
from datetime import datetime

import streamlit as st

from ai_scanner import scan_room, friendly_error
from auth import current_user, show_login_page, logout
from export import make_csv, make_pdf
from image_utils import prepare_image, has_metadata
from inventory import (
    COLUMNS,
    MONEY,
    items_to_table,
    clean_table,
    editor_column_config,
    combine_rooms,
)

# Most scans one visitor can do in one session (protects your API bill)
MAX_SCANS = 20

# Page settings: browser tab title, icon and layout
st.set_page_config(
    page_title="Home Contents Scanner",
    page_icon="🏠",
    layout="wide",
)

# --- Accounts: show the login screen until someone is logged in ---
if not current_user():
    show_login_page()
    st.stop()  # stop here: don't show the rest of the app

# --- Memory setup (runs once per visit) ---
if "house" not in st.session_state:
    st.session_state.house = []  # the list of saved rooms
if "form_id" not in st.session_state:
    st.session_state.form_id = 0  # goes up after each saved room, which clears the upload form
if "scans_used" not in st.session_state:
    st.session_state.scans_used = 0  # how many AI scans this visitor has done

form_id = st.session_state.form_id

# --- Header ---
st.title("🏠 Home Contents Scanner")
st.write("Snap a photo of each room and get a contents list ready for your insurer.")

# --- Disclaimer (always visible) ---
st.warning(
    "**Values are rough AI estimates, not official valuations.** "
    "Always check them yourself and confirm with your insurer before relying on them."
)

# --- Sidebar: how it works + privacy note ---
with st.sidebar:
    st.write(f"👤 Logged in as **{current_user()['email']}**")
    if st.button("Log out"):
        logout()
    st.divider()

    st.header("How it works")
    st.markdown(
        """
1. Upload or take a photo of a room
2. AI lists the items it can see
3. Fix anything it got wrong
4. Save the room, then repeat for each room
5. Export your list as PDF or CSV
"""
    )
    st.metric("Rooms saved", len(st.session_state.house))
    st.caption(
        "⚠️ Your list only lives in this browser tab. "
        "Refreshing or closing the page clears it, so export before you leave."
    )
    st.divider()

    with st.expander("🔒 Privacy: how your photos are used"):
        st.markdown(
            """
**What happens to your photo**
1. This app removes hidden location (GPS) data and shrinks the photo.
2. The photo is sent to **Anthropic**, the company behind the Claude AI, so it can identify the items.
3. The item list comes back to this page.

**What we keep:** nothing. Photos and lists only live in this browser tab and
disappear when you close or refresh it. Anthropic says it doesn't use API data to train
its models by default. See Anthropic's privacy policy for how long it keeps data.

**Tips for safer photos**
- Avoid capturing people, documents, letters with your address, ID cards or open laptop screens.
- Your exported list shows valuable things in your home. Store it somewhere safe and
  only share it with your insurer.
"""
        )

    if st.session_state.house:
        with st.expander("🗑️ Start over"):
            st.write("This removes every saved room. Download your export first if you want to keep it.")
            if st.button("Yes, clear all rooms"):
                st.session_state.house = []
                st.rerun()

# --- Message after a room is saved ---
if st.session_state.get("just_saved"):
    st.success(f"✅ {st.session_state.just_saved} saved! Add your next room below.")
    st.session_state.just_saved = None

# --- Step 1: Add a room photo ---
st.subheader("1. Add a room photo")

room_name = st.text_input(
    "Room name",
    placeholder="e.g. Lounge, Kitchen, Bedroom 1",
    key=f"room_name_{form_id}",
)

method = st.radio(
    "How do you want to add a photo?",
    ["Upload a photo", "Take a photo"],
    horizontal=True,
)

if method == "Upload a photo":
    photo = st.file_uploader(
        "Choose a photo of the room",
        type=["jpg", "jpeg", "png", "webp", "heic", "heif"],
        key=f"uploader_{form_id}",
    )
else:
    photo = st.camera_input("Take a photo of the room", key=f"camera_{form_id}")

# --- When a photo has been added ---
if photo is not None:
    jpeg_bytes, had_location = prepare_image(photo)

    # Give this photo a unique fingerprint. If the photo changes, forget the old scan.
    photo_id = hashlib.md5(jpeg_bytes).hexdigest()
    if st.session_state.get("photo_id") != photo_id:
        st.session_state.photo_id = photo_id
        st.session_state.scan_result = None
        st.session_state.items_table = None

    st.image(jpeg_bytes, caption=room_name or "Your room", width=600)

    if had_location:
        st.success("🔒 Hidden GPS location was found in this photo and removed.")
    else:
        st.success("🔒 Photo cleaned. No location data will be sent.")

    if has_metadata(jpeg_bytes):
        st.error("⚠️ Some hidden data is still in the photo. Please tell the developer!")

    # --- Step 2: Scan with AI ---
    st.subheader("2. Scan with AI")

    agreed = st.checkbox(
        "I understand this photo will be sent to Anthropic's AI service to identify the items in it.",
        key="consent",
    )

    scans_left = MAX_SCANS - st.session_state.scans_used
    if scans_left <= 0:
        st.error(f"You've reached the limit of {MAX_SCANS} scans for this session. You can still edit and add items by hand.")

    if st.button("🔍 Scan this room", type="primary", disabled=not agreed or scans_left <= 0):
        with st.spinner("Scanning... this usually takes 10–30 seconds"):
            try:
                result = scan_room(jpeg_bytes, room_name)
                st.session_state.scan_result = result
                st.session_state.items_table = items_to_table(result["items"])
                st.session_state.scans_used += 1
                # Count scans so each new scan gets a fresh editable table
                st.session_state.scan_count = st.session_state.get("scan_count", 0) + 1
            except Exception as e:
                print(f"[scan error] {e!r}")  # full details go to the Terminal, for you
                st.error(f"😕 {friendly_error(e)}")  # a friendly version goes to the user

    if not agreed:
        st.caption("Tick the box above to enable scanning.")
    elif 0 < scans_left <= 5:
        st.caption(f"{scans_left} scans left this session.")

    # --- Step 3: Check and fix the list ---
    result = st.session_state.get("scan_result")
    if result:
        st.write(f"**AI says:** {result['photo_note']}")

        if not result["items"]:
            st.info("The AI didn't find any household items. You can still add items yourself below.")

        st.subheader("3. Check and fix the list")
        st.caption(
            "✏️ **Edit:** double-click any cell.  "
            "➕ **Add something it missed:** click the + below the table.  "
            "🗑️ **Delete:** tick the box at the left of a row, then click the bin icon above the table."
        )
        st.caption(
            "💡 **Tip:** the AI doesn't guess brands. If you know an item's brand or model "
            "(e.g. a KitchenAid mixer or a Samsung TV), add it to the name and adjust the value. "
            "That makes your list much more accurate."
        )

        edited = st.data_editor(
            st.session_state.items_table,
            key=f"editor_{st.session_state.get('scan_count', 0)}",
            num_rows="dynamic",
            hide_index=True,
            column_config=editor_column_config(),
        )

        # Tidy the edits and work out totals
        final = clean_table(edited)

        col1, col2 = st.columns(2)
        col1.metric("Number of items", int(final["Qty"].sum()))
        col2.metric("Estimated room total (NZD)", f"${final['Total (NZD)'].sum():,.0f}")

        low_count = int((final["AI confidence"] == "low").sum())
        if low_count:
            st.warning(f"⚠️ The AI was unsure about {low_count} item(s) marked 'low'. Please double-check those.")

        st.caption(f"This scan cost about US${result['cost_usd']:.3f}.")

        # --- Step 4: Save this room ---
        st.subheader("4. Save this room")
        if st.button("✅ Add this room to my house list", type="primary"):
            # Tidy the room name: remove extra spaces and capitalise the first letter
            room_name = room_name.strip()
            room_name = room_name[:1].upper() + room_name[1:]

            if not room_name:
                st.error("Please give this room a name first (in the box at the top).")
            elif final.empty:
                st.error("There are no items to save. Add some items first.")
            else:
                st.session_state.house.append(
                    {
                        "id": uuid.uuid4().hex,  # a unique ID for this room
                        "room": room_name.strip(),
                        "photo": jpeg_bytes,
                        "items": final[COLUMNS].reset_index(drop=True),
                    }
                )
                # Reset everything for the next room
                st.session_state.form_id += 1
                st.session_state.photo_id = None
                st.session_state.scan_result = None
                st.session_state.items_table = None
                st.session_state.just_saved = room_name.strip()
                st.rerun()

# --- The whole house ---
st.divider()
st.header("🏡 Your whole house")

house = st.session_state.house

if not house:
    st.info("No rooms saved yet. Scan a room and click 'Add this room to my house list' to start.")
else:
    # Show each saved room. You can still edit it or remove it.
    edited_rooms = []   # (room name, cleaned table) pairs for the combined table
    export_rooms = []   # room name + photo + cleaned table, for the PDF
    for room in house:
        with st.expander(f"🚪 {room['room']}"):
            left, right = st.columns([1, 2])
            left.image(room["photo"], width=250)
            with right:
                room_edited = st.data_editor(
                    room["items"],
                    key=f"saved_{room['id']}",
                    num_rows="dynamic",
                    hide_index=True,
                    column_config=editor_column_config(),
                )
                if st.button("🗑️ Remove this room", key=f"remove_{room['id']}"):
                    st.session_state.house = [r for r in house if r["id"] != room["id"]]
                    st.rerun()
        cleaned = clean_table(room_edited)
        edited_rooms.append((room["room"], cleaned))
        export_rooms.append({"room": room["room"], "photo": room["photo"], "items": cleaned})

    # Combine every room into one big table
    all_items = combine_rooms(edited_rooms)
    st.session_state.all_items = all_items  # kept for the export stage

    # Headline numbers
    c1, c2, c3 = st.columns(3)
    c1.metric("Rooms", len(house))
    c2.metric("Items", int(all_items["Qty"].sum()))
    c3.metric("Estimated total (NZD)", f"${all_items['Total (NZD)'].sum():,.0f}")

    # Three views of the same data
    tab_all, tab_room, tab_cat = st.tabs(["All items", "By room", "By category"])

    with tab_all:
        st.dataframe(
            all_items,
            hide_index=True,
            column_config={"Value each (NZD)": MONEY, "Total (NZD)": MONEY},
        )

    with tab_room:
        by_room = all_items.groupby("Room", sort=False)["Total (NZD)"].sum().reset_index()
        st.dataframe(by_room, hide_index=True, column_config={"Total (NZD)": MONEY})
        st.bar_chart(by_room, x="Room", y="Total (NZD)")

    with tab_cat:
        by_cat = (
            all_items.groupby("Category")["Total (NZD)"]
            .sum()
            .sort_values(ascending=False)
            .reset_index()
        )
        st.dataframe(by_cat, hide_index=True, column_config={"Total (NZD)": MONEY})
        st.bar_chart(by_cat, x="Category", y="Total (NZD)")

    st.caption(
        "All values are rough AI estimates of replacement cost new in NZ, not official valuations. "
        "Check them before using this list with your insurer."
    )

    # --- Export ---
    st.divider()
    st.header("📤 Export for your insurer")
    st.write(
        "Download your list to keep it or send it to your insurer. "
        "**The PDF** includes each room's photo. **The CSV** opens in Excel or Google Sheets."
    )

    owner_name = st.text_input("Name to show on the PDF (optional)", placeholder="e.g. Gracie Smith")

    today = f"{datetime.now():%Y-%m-%d}"
    col_csv, col_pdf = st.columns(2)

    col_csv.download_button(
        "⬇️ Download CSV",
        data=make_csv(all_items),
        file_name=f"home-contents-{today}.csv",
        mime="text/csv",
    )

    try:
        pdf_bytes = make_pdf(export_rooms, owner_name)
        col_pdf.download_button(
            "⬇️ Download PDF (with photos)",
            data=pdf_bytes,
            file_name=f"home-contents-{today}.pdf",
            mime="application/pdf",
            type="primary",
        )
    except Exception as e:
        col_pdf.error(f"Couldn't make the PDF: {e}")

    st.caption(
        "🔒 Your files are created in your browser session and aren't stored by this app. "
        "Keep them somewhere safe: they list valuable things in your home."
    )
