"""
Run this ONCE locally to export your session as a string.
It will print a SESSION_STRING you can paste into Render.com as an env var.

Usage:
  python export_session.py
"""
import os
import asyncio
from dotenv import load_dotenv
from telethon import TelegramClient
from telethon.sessions import StringSession

load_dotenv()

API_ID   = int(os.getenv('TELEGRAM_API_ID'))
API_HASH = os.getenv('TELEGRAM_API_HASH')

async def main():
    # Connect using the existing file session
    async with TelegramClient('craverooms_session', API_ID, API_HASH) as client:
        # Export auth data into a StringSession
        string_session = StringSession.save(client.session)
        print("\n✅ SESSION_STRING (copy this into Render env vars):\n")
        print(string_session)
        print()

asyncio.run(main())
