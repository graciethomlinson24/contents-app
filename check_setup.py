# check_setup.py
# Checks that your API key loads and that Claude responds.

import os
from dotenv import load_dotenv
import anthropic

# 1. Read the .env file and load the values inside it
load_dotenv()
api_key = os.getenv("ANTHROPIC_API_KEY")

# 2. Make sure the key was found
if not api_key:
    print("❌ No key found. Check your .env file name and contents.")
    raise SystemExit

# Only show the first few characters, never the whole key
print(f"Key loaded ✅  (starts with {api_key[:10]}...)")

# 3. Send Claude a tiny test message
client = anthropic.Anthropic(api_key=api_key)

response = client.messages.create(
    model="claude-sonnet-5-5",
    max_tokens=50,
    messages=[{"role": "user", "content": "Reply with exactly: Hello Gracie, setup works!"}],
)

print("Claude says:", response.content[0].text)
