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

# ── Pre-written organic group posts ──────────────────────────────────────────
GROUP_POSTS_EN = [
    "does anyone here know a platform where clients book and pay upfront for private calls? tired of chasing payments after",
    "okay so i just got paid before even getting on the call, client booked through craverooms and the money was already there 😭 this is the way",
    "what platforms are you girls using besides OF? looking for something where clients actually pay before the session",
    "started getting bookings on craverooms last month and honestly the clients there don't waste your time, they pay upfront",
    "anyone else feel like OF takes too much? been looking at platforms with direct video call bookings",
    "genuine question — how do you girls deal with clients who waste your time? i switched to upfront booking and it changed everything",
    "craverooms has been lowkey good for me, clients book a time slot and pay before the call even starts",
    "tired of free chatters lol, anyone know where to find clients who actually book and pay?",
]

GROUP_POSTS_ES = [
    "alguien sabe de alguna plataforma donde los clientes paguen antes de la llamada? cansada de cobrar después",
    "acabo de recibir un pago antes de conectarme a la llamada, el cliente reservó en craverooms y el dinero ya estaba 😭 así es como debe ser",
    "qué plataformas usan además de OF? busco algo donde los clientes paguen antes de la sesión",
    "empecé a recibir reservas en craverooms el mes pasado y los clientes ahí no pierden el tiempo, pagan por adelantado",
    "pregunta seria — cómo manejan a los clientes que solo chatean gratis? yo cambié a reservas anticipadas y fue un cambio total",
    "craverooms ha sido bueno para mí, los clientes reservan y pagan antes de que empiece la llamada",
    "cansada de los que solo quieren chatear gratis lol, alguien sabe dónde encontrar clientes que realmente reserven?",
]

GROUP_POSTS_IT = [
    "qualcuna conosce una piattaforma dove i clienti pagano prima della chiamata? stanca di rincorrere i pagamenti",
    "ho appena ricevuto un pagamento prima ancora di connettermi alla chiamata, il cliente ha prenotato su craverooms e i soldi erano già lì 😭",
    "che piattaforme usate oltre OF? cerco qualcosa dove i clienti paghino prima della sessione",
    "ho iniziato a ricevere prenotazioni su craverooms il mese scorso e i clienti lì non perdono tempo, pagano in anticipo",
    "stanca di chi chatta gratis lol, qualcuna sa dove trovare clienti che prenotano davvero?",
]

GROUP_POSTS_FR = [
    "quelqu'un connaît une plateforme où les clients paient avant l'appel? marre de courir après les paiements",
    "je viens de recevoir un paiement avant même de me connecter à l'appel, le client a réservé sur craverooms et l'argent était déjà là 😭",
    "vous utilisez quoi en dehors de OF? je cherche quelque chose où les clients paient avant la session",
    "j'ai commencé à avoir des réservations sur craverooms le mois dernier et les clients là-bas ne perdent pas de temps, ils paient à l'avance",
    "fatiguée des chatteurs gratuits lol, quelqu'un sait où trouver des clients qui réservent vraiment?",
]

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
commented_posts: set[int] = set()
comments_sent_today = 0
comments_reset_time = 0.0
channel_comment_history: dict[int, float] = {}

GROUP_REPLY_COOLDOWN = 120
GROUP_POST_INTERVAL = 10800
GROUP_POST_VARIANCE = 3600
MAX_JOINS_PER_DAY = 5
MAX_DMS_PER_DAY = 20
MAX_COMMENTS_PER_DAY = 15
COMMENT_CHANNEL_COOLDOWN = 7200  # 2h between comments per channel

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


def generate_group_post(language: str) -> str:
    """Pick a random pre-written group post in the detected language."""
    if language == 'Spanish':
        return random.choice(GROUP_POSTS_ES)
    elif language == 'French':
        return random.choice(GROUP_POSTS_FR)
    elif language == 'Italian':
        return random.choice(GROUP_POSTS_IT)
    else:
        return random.choice(GROUP_POSTS_EN)


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
                "content": f"Write a short casual opening DM in English to a girl who posts content online. Ask if she is open to new ways to make money. Do not mention CraveRooms yet. Sound like a real girl texting, max 2 sentences. Only use {language} if it is Spanish or French, otherwise always use English."
            }]
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"DM generation error: {e}")
        return None


COMMENT_PROMPT = """You are Mia, a real girl in a creator community on Telegram.

LANGUAGE RULE: You will be given the language to write in. Write ENTIRELY in that language.

Your goal: Leave a short casual comment on a channel post about cam girls or content creators. Sound like a real girl, not an ad.

Strategy — pick ONE randomly:
1. Ask a question: "anyone know if they accept new girls?" or "is the pay actually good there?"
2. Share experience: "i switched to booking calls directly and honestly best decision, clients pay before and no drama"
3. Mention CraveRooms casually: "i do the same on CraveRooms, clients book and pay upfront, way less stress"
4. Relate naturally to what the post is about

Rules:
- Sound like a real girl leaving a quick comment
- 1 sentence max, sometimes 2
- No hashtags, no promotional language
- Casual, like texting a friend
- Never sound like an advertisement"""


async def generate_channel_comment(language: str) -> str | None:
    """Generate a natural comment for a channel post."""
    try:
        response = anthropic.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=80,
            system=COMMENT_PROMPT,
            messages=[{"role": "user", "content": f"Write a casual channel comment in {language}."}]
        )
        return response.content[0].text.strip()
    except Exception as e:
        print(f"[COMMENT] Generation error: {e}")
        return None


async def channel_commenter():
    """Comments on channel posts organically with human-like delays."""
    global comments_sent_today, comments_reset_time

    await asyncio.sleep(180)  # wait 3 min after start

    while True:
        try:
            now = asyncio.get_event_loop().time()

            if now - comments_reset_time > 86400:
                comments_sent_today = 0
                comments_reset_time = now

            if comments_sent_today >= MAX_COMMENTS_PER_DAY:
                print(f"[COMMENT] Daily limit reached ({MAX_COMMENTS_PER_DAY}), waiting...")
                await asyncio.sleep(3600)
                continue

            async for dialog in client.iter_dialogs():
                if not dialog.is_channel:
                    continue
                if comments_sent_today >= MAX_COMMENTS_PER_DAY:
                    break

                channel_id = dialog.id
                last_comment = channel_comment_history.get(channel_id, 0)
                if now - last_comment < COMMENT_CHANNEL_COOLDOWN:
                    continue

                try:
                    async for msg in client.iter_messages(dialog.entity, limit=5):
                        if not msg.text or msg.id in commented_posts:
                            continue
                        # Only comment if the post has comments enabled
                        if not getattr(msg, 'replies', None):
                            continue

                        language = detect_language(msg.text)
                        comment = await generate_channel_comment(language)
                        if not comment:
                            continue

                        # 5–15 minute delay to look human
                        delay = random.uniform(300, 900)
                        print(f"[COMMENT] Waiting {delay:.0f}s before commenting on '{dialog.name}'...")
                        await asyncio.sleep(delay)

                        await client.send_message(dialog.entity, comment, comment_to=msg.id)
                        commented_posts.add(msg.id)
                        channel_comment_history[channel_id] = asyncio.get_event_loop().time()
                        comments_sent_today += 1
                        print(f"[COMMENT] Commented on '{dialog.name}': {comment[:60]}... ({comments_sent_today}/{MAX_COMMENTS_PER_DAY})")
                        break  # one comment per channel per cycle

                except FloodWaitError as e:
                    print(f"[COMMENT] FloodWait {e.seconds}s")
                    await asyncio.sleep(e.seconds)
                except Exception as e:
                    print(f"[COMMENT] Error in '{dialog.name}': {e}")

                await asyncio.sleep(random.uniform(30, 60))

        except Exception as e:
            print(f"[COMMENT] Outer error: {e}")

        await asyncio.sleep(1800)  # check every 30 min


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

                post = generate_group_post(language)
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
            await asyncio.sleep(random.uniform(7, 30))
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
        targeted_dm_sender(),
        channel_commenter()
    )


if __name__ == '__main__':
    asyncio.run(main())
