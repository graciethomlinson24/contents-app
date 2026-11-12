# ai_scanner.py
# Sends a room photo to Claude and gets back a structured list of items.

import base64
import os

import anthropic
import streamlit as st
from dotenv import load_dotenv

# Which Claude model to use. Sonnet is accurate. "claude-haiku-5-5" is ~20x cheaper but rougher.
MODEL = "claude-sonnet-5-5"

# Price per million tokens in USD (Sonnet 5.5), used to show what each scan cost
PRICE_INPUT_PER_M = 2.00
PRICE_OUTPUT_PER_M = 10.00

CATEGORIES = [
    "Electronics",
    "Furniture",
    "Appliances",
    "Kitchenware",
    "Decor & Soft Furnishings",
    "Clothing & Accessories",
    "Jewellery & Valuables",
    "Books & Media",
    "Sports & Outdoors",
    "Tools & DIY",
    "Other",
]

# The "form" Claude must fill in. It has to answer using exactly these fields.
SCAN_TOOL = {
    "name": "record_items",
    "description": "Record the household contents items visible in a room photo.",
    "input_schema": {
        "type": "object",
        "properties": {
            "photo_note": {
                "type": "string",
                "description": "One short sentence describing the photo, e.g. 'A lounge with a couch and TV.' "
                "If it isn't a room inside a home, say so.",
            },
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Short, specific name, e.g. '3-seater fabric couch', '55-inch TV'.",
                        },
                        "quantity": {"type": "integer", "minimum": 1},
                        "category": {"type": "string", "enum": CATEGORIES},
                        "unit_value_nzd": {
                            "type": "number",
                            "description": "Rough cost to buy ONE of this item NEW in New Zealand, in NZD incl. GST.",
                        },
                        "confidence": {
                            "type": "string",
                            "enum": ["high", "medium", "low"],
                            "description": "How sure you are about what the item is and its value.",
                        },
                    },
                    "required": ["name", "quantity", "category", "unit_value_nzd", "confidence"],
                },
            },
        },
        "required": ["photo_note", "items"],
    },
}

# The instructions we give Claude along with the photo
PROMPT = """You are helping a New Zealander make a home contents inventory for their insurance company.

Look at this photo and list the household contents you can clearly see.

Rules:
- Only list movable contents (things you'd take with you when moving house).
  Skip parts of the building: walls, windows, doors, built-in cupboards, fixed light fittings, carpet.
- Ignore people and pets.
- Only list things you can actually see. Don't guess at things that might be hidden.
- Group identical items into one line with a quantity (e.g. 4 dining chairs = quantity 4).
- Be specific in names where you can (size, material, type), but don't invent brand names you can't see.
- For value, estimate the replacement cost NEW for ONE item at typical New Zealand retailers
  (e.g. Noel Leeming, Harvey Norman, Briscoes, Farmers, Kmart NZ), in NZD including GST.
  Use realistic mid-range prices unless the item clearly looks premium or budget.
- Small clutter (pens, mugs, ornaments) can be grouped, e.g. "Assorted decor items", or skipped.
- If the photo isn't of a room inside a home, return an empty items list and explain in photo_note.

Use the record_items tool to give your answer."""


def get_secret(name):
    """Find a secret: first in the .env file (on your Mac), then in Streamlit Secrets (once online)."""
    load_dotenv()
    value = os.getenv(name)
    if value:
        return value
    try:
        return st.secrets[name]
    except Exception:
        return None


def get_api_key():
    return get_secret("ANTHROPIC_API_KEY")


def scan_room(jpeg_bytes, room_name=""):
    """
    Sends the photo to Claude. Returns a dictionary like:
    {"photo_note": "...", "items": [ {...}, {...} ], "cost_usd": 0.012}
    """
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("No API key found. Check your .env file.")

    # max_retries: if Anthropic is briefly busy, try again automatically (up to 3 times)
    # timeout: give up after 90 seconds rather than spinning forever
    client = anthropic.Anthropic(api_key=api_key, max_retries=3, timeout=90)

    # Photos are sent as text using "base64" encoding
    image_b64 = base64.standard_b64encode(jpeg_bytes).decode("utf-8")

    response = client.messages.create(
        model=MODEL,
        max_tokens=4000,
        tools=[SCAN_TOOL],
        tool_choice={"type": "auto"},  # Claude decides; the prompt tells it to use the form
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64},
                    },
                    {
                        "type": "text",
                        "text": PROMPT + f"\n\nThe user says this room is: {room_name or 'not specified'}",
                    },
                ],
            }
        ],
    )

    # Find the filled-in form in Claude's reply
    for block in response.content:
        if block.type == "tool_use":
            result = dict(block.input)
            # Work out roughly what this scan cost
            usage = response.usage
            input_cost = usage.input_tokens * PRICE_INPUT_PER_M / 1_000_000
            output_cost = usage.output_tokens * PRICE_OUTPUT_PER_M / 1_000_000
            result["cost_usd"] = input_cost + output_cost
            return result

    raise RuntimeError("The AI didn't return an item list. Please try again.")


def friendly_error(error):
    """Turn a technical error into a message a normal person can understand."""
    # The order matters: the specific error types are checked before the general ones
    if isinstance(error, anthropic.AuthenticationError):
        return "The app's AI connection isn't set up correctly. (Developer: check the API key.)"
    if isinstance(error, anthropic.RateLimitError):
        return "Too many scans in a short time. Please wait a minute and try again."
    if isinstance(error, anthropic.APIConnectionError):
        return "Couldn't reach the AI service. Check your internet connection and try again."
    if isinstance(error, anthropic.APITimeoutError):
        return "The scan took too long. Please try again, or try a smaller photo."
    if isinstance(error, anthropic.APIStatusError):
        message = str(error).lower()
        if "credit balance" in message:
            return "The app has run out of AI credit. (Developer: top up in the Anthropic console.)"
        if error.status_code == 529 or "overloaded" in message or error.status_code >= 500:
            return "The AI service is very busy right now. Please wait a minute and try again."
        return "The AI couldn't process this photo. Please try a different photo."
    if isinstance(error, RuntimeError):
        return str(error)
    return "Something went wrong while scanning. Please try again."