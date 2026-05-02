import os
import asyncio
import random
import re
from dotenv import load_dotenv
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import User
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.errors import UserAlreadyParticipantError, InviteHashInvalidError, FloodWaitError
from anthropic import Anthropic

load_dotenv()

API_ID = int(os.getenv('TELEGRAM_API_ID') or os.getenv('API_ID'))
API_HASH = os.getenv('TELEGRAM_API_HASH') or os.getenv('API_HASH')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

SESSION_STRING = os.getenv('SESSION_STRING', '')
client = TelegramClient(StringSession(SESSION_STRING), API_ID, API_HASH)
anthropic = Anthropic(api_key=ANTHROPIC_API_KEY)

# ── System prompt for DMs and group replies ───────────────────────────────────
SYSTEM_PROMPT = """You are Mia, a real girl who works on CraveRooms and recruits other creators to join.

LANGUAGE RULE: Detect the language the person is writing in. If they write in Spanish, respond ENTIRELY in Spanish. If they write in French, respond in French. If in English, respond in English. Always match their language.

About CraveRooms:
- Creators post and sell content directly to clients
- Clients book paid private 1 on 1 live video calls with creators, paying upfront
- AI chat handles messages and sells content when the creator is offline, but every call is always the real creator
- Creators keep 80% of everything
- No fees for the first 3 months
- Featured on the homepage while spots are limited
- Runs alongside OnlyFans as extra income, does not replace it

How to handle conversations:
- If someone asks if you have a platform, say yes and pitch CraveRooms immediately
- If someone asks about sex calls or live calls, tell them clients book and pay upfront for private video calls, it is easy money
- If someone seems interested in money or content creation, pitch CraveRooms right away
- Always push toward getting them to sign up at craverooms.com
- If they want to sign up, tell them to go to craverooms.com and register as a performer
- If they ask for more info, explain and keep pushing naturally

Your personality:
- You are a real girl, casual and friendly
- Short messages like texting, never long paragraphs
- Never sound like a bot or use formal language
- If asked if you are a bot, deny it
- Be direct, do not waste time, get to the point fast

Rules:
- Max 3 sentences per message
- No bullet points or lists ever
- Sound human at all times
- Always bring the conversation back to CraveRooms and signing up"""

# ── System prompt for organic group posts ────────────────────────────────────
GROUP_POST_PROMPT = """You are Mia, a real girl in a creator community group on Telegram.

LANGUAGE RULE: You will be given the language to write in. Write ENTIRELY in that language.

Your goal: Post a casual message that naturally leads to mentioning CraveRooms without it looking like an ad.

Strategy — pick ONE of these approaches randomly:
1. Ask for advice: "does anyone know a good platform where clients can book private video calls directly? tired of OF taking so much"
2. Share a win: "okay so i just got paid for a booking before even getting on the call, the client paid upfront, this is the way"
3. Ask what others use: "what platforms are you girls using besides OF? looking for something with direct client bookings"
4. Drop a casual mention: "started using CraveRooms last month for direct bookings and honestly the clients there pay without drama"

Rules:
- Sound like a real girl texting in a group chat
- Never use hashtags or promotional language
- Keep it short, 1-2 sentences max
- If mentioning CraveRooms directly, do it casually not as an advertisement
- No bullet points, no lists, no formal language"""

TRIGGER_KEYWORDS = [
    # English
    'onlyfans', 'content creator', 'making money', 'earn money',
    'passive income', 'new platform', 'side income', 'looking for work',
    'how to make money', 'creator', 'monetize', 'sell content',
    'streaming', 'camgirl', 'cam girl', 'live stream', 'fansite',
    'fansly', 'chaturbate', 'stripchat', 'income', 'opportunity',
    # French
    'argent', 'gagner', 'plateforme', 'revenus', 'contenu',
    'createur', 'créateur', 'monetiser', 'monétiser',
    # Spanish
    'dinero', 'ganar', 'plataforma', 'ingresos', 'contenido',
    'creadora', 'creador', 'monetizar', 'trabajo', 'ganancias',
    'fans', 'suscriptores', 'videollamada', 'transmision', 'transmisión',
    'solo fans', 'modelo', 'webcam'
]

conversation_history = {}
conversation_count: dict[int, int] = {}
processed_message_ids: set[int] = set()
MAX_MESSAGES_PER_USER = 10
cooldown_groups = {}
group_post_history: dict[int, float] = {}
joined_today = 0
joined_today_reset = 0.0
dmed_users: set[int] = set()
dms_sent_today = 0
dms_reset_time = 0.0

GROUP_REPLY_COOLDOWN = 120
GROUP_POST_INTERVAL = 10800
GROUP_POST_VARIANCE = 3600
MAX_JOINS_PER_DAY = 5
MAX_DMS_PER_DAY = 20

INVITE_PATTERN = re.compile(r'(?:https?://)?t\.me/(?:joinchat/|\+)([a-zA-Z0-9_-]+)|(?:https?://)?t\.me/([a-zA-Z0-9_]+)')


def has_trigger(text: str) -> bool:
    text_lower = text.lower()
    return any(kw in text_lower for kw in TRIGGER_KEYWORDS)


def detect_language(text: str) -> str:
    """Simple language detection based on common words."""
    text_lower = text.lower()
    spanish_words = ['hola', 'como', 'que', 'una', 'para', 'con', 'por', 'pero', 'estoy', 'quiero', 'gracias', 'dinero', 'trabajo']
    french_words = ['bonjour', 'salut', 'comment', 'pour', 'avec', 'mais', 'est', 'les', 'des', 'une', 'argent', 'merci']
    spanish_count = sum(1 for w in spanish_words if w in text_lower)
    french_count = sum(1 for w in french_words if w in text_lower)
    if spanish_count > french_count and spanish_count > 0:
        return 'Spanish'
    if french_count > 0:
        return 'French'
    return 'English'


async def get_ai_response(user_id: int, message: str) -> str | None:
    if user_id not in conversation_history:
        conversation_history[user_id] = []

    conversation_history[user_id].append({"role": "user", "content": message})

    if len(conversation_history[user_id]) > 20:
        conversation_history[user_id] = conversation_history[user_id][-20:]

    try:
        response = anthropic.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=150,
            system=SYSTEM_PROMPT,
            messages=conversation_history[user_id]
        )
        reply = response.content[0].text
    except Exception as e:
        print(f"Claude API error: {e}")
        return None

    conversation_history[user_id].append({"role": "assistant", "content": reply})
    return reply


async def generate_group_post(language: str) -> str | None:
    """Generate an organic-sounding group post in the detected language."""
    try:
        response = anthropic.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system=GROUP_POST_PROMPT,
            messages=[{"role": "user", "content": f"Write a casual group message in {language}."}]
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"Post generation error: {e}")
        return None


async def try_join_from_link(link: str):
    """Attempt to join a group from an invite link found in a message."""
    global joined_today, joined_today_reset

    now = asyncio.get_event_loop().time()

    # Reset daily counter every 24h
    if now - joined_today_reset > 86400:
        joined_today = 0
        joined_today_reset = now

    if joined_today >= MAX_JOINS_PER_DAY:
        print(f"[JOIN] Daily limit reached ({MAX_JOINS_PER_DAY}), skipping {link}")
        return

    # Random delay so it looks human
    await asyncio.sleep(random.uniform(30, 120))

    try:
        match = INVITE_PATTERN.search(link)
        if not match:
            return

        invite_hash = match.group(1)
        username = match.group(2)

        if invite_hash:
            await client(ImportChatInviteRequest(invite_hash))
            joined_today += 1
            print(f"[JOIN] Joined via invite hash: {invite_hash} (today: {joined_today}/{MAX_JOINS_PER_DAY})")
        elif username:
            entity = await client.get_entity(username)
            await client(JoinChannelRequest(entity))
            joined_today += 1
            print(f"[JOIN] Joined @{username} (today: {joined_today}/{MAX_JOINS_PER_DAY})")

    except UserAlreadyParticipantError:
        pass  # already in group, no problem
    except InviteHashInvalidError:
        print(f"[JOIN] Invalid invite link: {link}")
    except FloodWaitError as e:
        print(f"[JOIN] FloodWait — sleeping {e.seconds}s")
        await asyncio.sleep(e.seconds)
    except Exception as e:
        print(f"[JOIN] Failed to join {link}: {e}")


async def generate_opening_dm(language: str) -> str | None:
    """Generate a natural opening DM to send to a girl in a group."""
    try:
        response = anthropic.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=100,
            system=SYSTEM_PROMPT,
            messages=[{
                "role": "user",
                "content": f"Write a short casual opening DM in {language} to a girl who posts content online. Ask if she is open to new ways to make money. Do not mention CraveRooms yet. Sound like a real girl texting, max 2 sentences."
            }]
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"DM generation error: {e}")
        return None


async def targeted_dm_sender():
    """Scans active posters in joined groups and sends them opening DMs."""
    global dms_sent_today, dms_reset_time

    await asyncio.sleep(300)  # wait 5 min after start

    while True:
        try:
            now = asyncio.get_event_loop().time()

            # Reset daily DM counter every 24h
            if now - dms_reset_time > 86400:
                dms_sent_today = 0
                dms_reset_time = now

            if dms_sent_today >= MAX_DMS_PER_DAY:
                print(f"[DM] Daily limit reached ({MAX_DMS_PER_DAY}), waiting...")
                await asyncio.sleep(3600)
                continue

            me = await client.get_me()

            async for dialog in client.iter_dialogs():
                if not dialog.is_group and not dialog.is_channel:
                    continue
                if dms_sent_today >= MAX_DMS_PER_DAY:
                    break

                try:
                    # Collect recent active posters
                    recent_posters: list[tuple] = []
                    async for msg in client.iter_messages(dialog.entity, limit=50):
                        if not msg.sender_id or msg.sender_id == me.id:
                            continue
                        sender = await msg.get_sender()
                        if not isinstance(sender, User):
                            continue
                        if sender.bot or sender.id in dmed_users:
                            continue
                        if not msg.text:
                            continue
                        lang = detect_language(msg.text)
                        recent_posters.append((sender, lang))

                    # Deduplicate by user id
                    seen = set()
                    unique_posters = []
                    for poster, lang in recent_posters:
                        if poster.id not in seen:
                            seen.add(poster.id)
                            unique_posters.append((poster, lang))

                    for user, language in unique_posters[:3]:  # max 3 per group per cycle
                        if dms_sent_today >= MAX_DMS_PER_DAY:
                            break

                        opening = await generate_opening_dm(language)
                        if not opening:
                            continue

                        await asyncio.sleep(random.uniform(60, 180))  # 1-3 min between DMs

                        await client.send_message(user, opening)
                        dmed_users.add(user.id)
                        dms_sent_today += 1
                        print(f"[DM-OUT] Sent to {user.first_name} from '{dialog.name}' in {language} ({dms_sent_today}/{MAX_DMS_PER_DAY}): {opening[:50]}...")

                except FloodWaitError as e:
                    print(f"[DM-OUT] FloodWait {e.seconds}s")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    print(f"[DM-OUT] Error in group {dialog.name}: {e}")

                await asyncio.sleep(random.uniform(20, 60))

        except Exception as e:
            print(f"[DM-OUT] Outer error: {e}")

        await asyncio.sleep(3600)  # run cycle every hour


async def organic_group_poster():
    """Periodically posts in joined groups to spark conversation."""
    await asyncio.sleep(60)  # wait 1 min after start before first post
    while True:
        try:
            async for dialog in client.iter_dialogs():
                if not dialog.is_group and not dialog.is_channel:
                    continue

                group_id = dialog.id
                now = asyncio.get_event_loop().time()
                last_post = group_post_history.get(group_id, 0)
                interval = GROUP_POST_INTERVAL + random.uniform(-GROUP_POST_VARIANCE, GROUP_POST_VARIANCE)

                if now - last_post < interval:
                    continue

                # Detect language from recent group messages
                language = 'English'
                try:
                    recent_msgs = []
                    async for msg in client.iter_messages(dialog.entity, limit=10):
                        if msg.text:
                            recent_msgs.append(msg.text)
                    if recent_msgs:
                        combined = ' '.join(recent_msgs)
                        language = detect_language(combined)
                except Exception:
                    pass

                post = await generate_group_post(language)
                if post:
                    await asyncio.sleep(random.uniform(5, 20))
                    await client.send_message(dialog.entity, post)
                    group_post_history[group_id] = now
                    print(f"[POST] Sent organic post to '{dialog.name}' in {language}: {post[:60]}...")

                await asyncio.sleep(random.uniform(30, 90))  # gap between groups

        except Exception as e:
            print(f"Poster error: {e}")

        await asyncio.sleep(1800)  # check every 30 min


@client.on(events.NewMessage(incoming=True))
async def handle_message(event):
    try:
        sender = await event.get_sender()
        if not isinstance(sender, User):
            return

        me = await client.get_me()
        if sender.id == me.id:
            return

        if sender.bot:
            return

        message_text = event.message.message
        if not message_text or len(message_text.strip()) < 3:
            return

        if event.message.id in processed_message_ids:
            return
        processed_message_ids.add(event.message.id)

        is_dm = event.is_private

        # Auto-join: scan every group message for Telegram invite links
        if not is_dm:
            links = INVITE_PATTERN.findall(message_text)
            for match in links:
                full_link = f"https://t.me/{match[0] or match[1]}"
                asyncio.create_task(try_join_from_link(full_link))

        if is_dm:
            count = conversation_count.get(sender.id, 0)
            if count >= MAX_MESSAGES_PER_USER:
                print(f"[DM] Limit reached for {sender.first_name}, ignoring.")
                return
            conversation_count[sender.id] = count + 1
            await asyncio.sleep(random.uniform(3, 8))
            async with client.action(event.chat_id, 'typing'):
                reply = await get_ai_response(sender.id, message_text)
                await asyncio.sleep(random.uniform(2, 5))
            if reply:
                await event.reply(reply)
                print(f"[DM] Replied to {sender.first_name} ({count+1}/{MAX_MESSAGES_PER_USER}): {reply[:60]}...")

        else:
            if not has_trigger(message_text):
                return

            chat_id = event.chat_id
            now = asyncio.get_event_loop().time()

            if chat_id in cooldown_groups:
                if now - cooldown_groups[chat_id] < GROUP_REPLY_COOLDOWN:
                    return

            cooldown_groups[chat_id] = now
            await asyncio.sleep(random.uniform(30, 90))

            reply = await get_ai_response(sender.id, message_text)
            if reply:
                await event.reply(reply)
                print(f"[GROUP] Replied in '{event.chat.title}': {reply[:60]}...")

    except Exception as e:
        print(f"Error: {e}")


async def main():
    print("Starting CraveRooms recruitment bot...")
    await client.start()
    me = await client.get_me()
    print(f"Logged in as: {me.first_name} (@{me.username})")
    print("Bot is running — listening for messages + posting in groups every 3h...")
    print("Press Ctrl+C to stop.")

    await asyncio.gather(
        client.run_until_disconnected(),
        organic_group_poster(),
        targeted_dm_sender()
    )


if __name__ == '__main__':
    asyncio.run(main())
