# storage.py
# Saves and loads each user's rooms and photos in Supabase.
# Row Level Security (set up in setup.sql) makes sure people only ever touch their own data.

import json
import uuid
from datetime import datetime, timedelta, timezone

import pandas as pd

from auth import get_client, current_user
from inventory import COLUMNS

BUCKET = "room-photos"

# Most AI scans one account can do in any 30 days (protects your API bill)
MAX_SCANS_PER_30_DAYS = 30


def df_to_json(df):
    """Turn a table into plain JSON-friendly data (lists of dictionaries)."""
    return json.loads(df[COLUMNS].to_json(orient="records"))


# ---------- Rooms ----------

def load_rooms():
    """Load all of this user's saved rooms, including photos."""
    client = get_client()
    rows = client.table("rooms").select("*").order("created_at").execute().data

    rooms = []
    for row in rows:
        try:
            photo = client.storage.from_(BUCKET).download(row["photo_path"])
        except Exception as e:
            print(f"[photo download error] {e!r}")
            photo = None
        rooms.append(_row_to_room(row, photo))
    return rooms


def save_room(room_name, jpeg_bytes, items_df):
    """Upload the photo, save the room, and return it in the same shape the app uses."""
    client = get_client()
    user_id = current_user()["id"]
    room_id = str(uuid.uuid4())
    photo_path = f"{user_id}/{room_id}.jpg"  # the folder name = the owner's ID

    client.storage.from_(BUCKET).upload(photo_path, jpeg_bytes, {"content-type": "image/jpeg"})

    row = (
        client.table("rooms")
        .insert(
            {
                "id": room_id,
                "user_id": user_id,
                "room_name": room_name,
                "photo_path": photo_path,
                "items": df_to_json(items_df),
            }
        )
        .execute()
        .data[0]
    )
    return _row_to_room(row, jpeg_bytes)


def update_room_items(room_id, items_json):
    get_client().table("rooms").update({"items": items_json}).eq("id", room_id).execute()


def delete_room(room):
    client = get_client()
    client.storage.from_(BUCKET).remove([room["photo_path"]])
    client.table("rooms").delete().eq("id", room["id"]).execute()


def delete_account(rooms):
    """Delete every photo, then the account itself (which also deletes rooms and scans)."""
    client = get_client()
    paths = [r["photo_path"] for r in rooms]
    if paths:
        client.storage.from_(BUCKET).remove(paths)
    client.rpc("delete_my_account").execute()


def _row_to_room(row, photo):
    return {
        "id": row["id"],
        "room": row["room_name"],
        "photo": photo,
        "photo_path": row["photo_path"],
        "items": pd.DataFrame(row["items"], columns=COLUMNS),  # what the editor starts with
        "saved_json": row["items"],  # what's currently saved, to spot new edits
        "created_at": row["created_at"],
    }


# ---------- Scan log ----------

def count_recent_scans():
    """How many AI scans this user has done in the last 30 days."""
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    result = (
        get_client()
        .table("scans")
        .select("id", count="exact")
        .gte("created_at", since)
        .execute()
    )
    return result.count or 0


def record_scan(cost_usd):
    get_client().table("scans").insert({"user_id": current_user()["id"], "cost_usd": cost_usd}).execute()
    
