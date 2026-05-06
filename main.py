from flask import Flask
from threading import Thread
import requests
from bs4 import BeautifulSoup
import schedule
import time
import json
import os
import pytz
import random
from datetime import datetime

app = Flask(__name__)

# ============ CONFIG ============
BOT_TOKEN = "8751991442:AAEiC4uRBlpw1l8zJpV4IF-jAahw-cDFWuA"
GEMINI_KEY = "AIzaSyAQ4n57sXTOatFT7g_7jPtF4BdbjL1CZyQ"
FREE_CHANNEL_ID = "-1003721050699"
PAID_CHANNEL_ID = "-1003903983342"

TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
WAT = pytz.timezone("Africa/Lagos")

DIRECT_MANDATE_KEYWORDS = [
    "direct mandate", "owner direct", "landlord direct",
    "no agent", "direct from owner", "property owner",
    "mandate", "direct let", "direct sale"
]

SEEN_FILE = "seen_listings.json"
STATS_FILE = "stats.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Accept-Encoding": "identity"
}

# ============ STATS ============
def load_stats():
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    return {"total_leads": 0, "gold_leads": 0, "last_scan": "Never"}

def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)

# ============ HELPERS ============
def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, "r") as f:
            return json.load(f)
    return []

def save_seen(seen):
    with open(SEEN_FILE, "w") as f:
        json.dump(seen[-500:], f)

def send_telegram(chat_id, message):
    try:
        payload = {
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML"
        }
        r = requests.post(
            f"{TELEGRAM_URL}/sendMessage",
            json=payload,
            timeout=10
        )
        if r.status_code == 200:
            print(f"✅ Sent to {chat_id}")
        else:
            print(f"❌ Telegram error: {r.text}")
        return r.status_code == 200
    except Exception as e:
        print(f"Telegram error: {e}")
        return False

def is_direct_mandate(text):
    return any(k in text.lower() for k in DIRECT_MANDATE_KEYWORDS)

# ============ GEMINI ============
def analyze_with_gemini(listing):
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-pro:generateContent?key={GEMINI_KEY}"
        payload = {
            "contents": [{
                "parts": [{
                    "text": f"""You are a Nigerian real estate analyst. Analyze this property listing.

Property: {listing['title']}
Location: {listing['location']}
Price: {listing['price']}
Description: {listing.get('description', 'N/A')}

Respond in this exact JSON format only, no extra text:
{{
    "score": "HOT" or "FAIR" or "SKIP",
    "reason": "one sentence why this is a good or bad deal",
    "tip": "one actionable tip for Nigerian real estate agents"
}}"""
                }]
            }]
        }
        r = requests.post(url, json=payload, timeout=15)
        text = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        text = text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        print(f"Gemini error: {e}")
        return {
            "score": "HOT",
            "reason": "Fresh property listing in high demand Nigerian location",
            "tip": "Contact the agent quickly before other buyers do"
        }

# ============ SCRAPER — PROPERTYPRO ============
def scrape_propertypro():
    listings = []
    urls = [
        "https://www.propertypro.ng/property-for-sale/lagos",
        "https://www.propertypro.ng/property-for-rent/lagos",
        "https://www.propertypro.ng/property-for-sale/abuja",
        "https://www.propertypro.ng/property-for-rent/abuja",
    ]

    for url in urls:
        try:
            print(f"Scraping: {url}")
            r = requests.get(url, headers=HEADERS, timeout=20)
            print(f"Status: {r.status_code}")
            r.encoding = 'utf-8'
soup = BeautifulSoup(r.text, "lxml")

            cards = (
                soup.find_all("div", class_="listings-property") or
                soup.find_all("div", class_="single-room-sale") or
                soup.find_all("article") or
                soup.find_all("div", class_="col-md-4") or
                soup.find_all("div", attrs={"data-id": True})
            )

            print(f"Found {len(cards)} cards on {url}")

            for card in cards[:6]:
                try:
                    title_el = (
                        card.find("h4") or
                        card.find("h3") or
                        card.find("h2") or
                        card.find(class_="listings-property-title") or
                        card.find(class_="title")
                    )
                    title = title_el.get_text(strip=True) if title_el else ""
                    if not title or len(title) < 5:
                        continue

                    price_el = (
                        card.find(class_="listings-price") or
                        card.find(class_="price") or
                        card.find("h3") or
                        card.find(string=lambda t: t and "₦" in t)
                    )
                    price = price_el.get_text(strip=True) if price_el else "Price on request"

                    location_el = (
                        card.find("address") or
                        card.find(class_="lp-title") or
                        card.find(class_="location") or
                        card.find(class_="listings-property-location")
                    )
                    location = location_el.get_text(strip=True) if location_el else "Lagos"

                    link_el = card.find("a", href=True)
                    if link_el:
                        href = link_el["href"]
                        link = "https://www.propertypro.ng" + href if href.startswith("/") else href
                    else:
                        link = url

                    desc_el = card.find("p")
                    description = desc_el.get_text(strip=True) if desc_el else ""

                    listing_type = "For Sale" if "sale" in url else "For Rent"

                    listings.append({
                        "title": title,
                        "price": price,
                        "location": location,
                        "link": link,
                        "description": description,
                        "type": listing_type,
                        "source": "PropertyPro"
                    })
                    print(f"✅ Got: {title[:40]}")

                except Exception as e:
                    print(f"Card error: {e}")
                    continue

            time.sleep(3)

        except Exception as e:
            print(f"PropertyPro error: {e}")
            continue

    return listings

# ============ SCRAPER — JIJI ============
def scrape_jiji():
    listings = []
    urls = [
        "https://jiji.ng/lagos/houses-apartments-for-rent",
        "https://jiji.ng/lagos/houses-apartments-for-sale",
        "https://jiji.ng/abuja/houses-apartments-for-rent",
    ]

    for url in urls:
        try:
            print(f"Scraping Jiji: {url}")
            r = requests.get(url, headers=HEADERS, timeout=20)
            print(f"Jiji Status: {r.status_code}")
            r.encoding = 'utf-8'
soup = BeautifulSoup(r.text, "lxml")

            cards = (
                soup.find_all("div", class_="b-list-advert__item-wrapper") or
                soup.find_all("article", class_="b-list-advert-base") or
                soup.find_all("div", class_="qa-advert-list-item") or
                soup.find_all("li", class_="b-list-advert__item")
            )

            print(f"Jiji cards: {len(cards)}")

            for card in cards[:6]:
                try:
                    title_el = (
                        card.find(class_="b-advert-title-inner") or
                        card.find("h3") or
                        card.find("h2") or
                        card.find(class_="qa-advert-title")
                    )
                    title = title_el.get_text(strip=True) if title_el else ""
                    if not title or len(title) < 5:
                        continue

                    price_el = (
                        card.find(class_="b-advert-price__converted") or
                        card.find(class_="price") or
                        card.find(class_="b-advert-price")
                    )
                    price = price_el.get_text(strip=True) if price_el else "Price on request"

                    location_el = (
                        card.find(class_="b-list-advert__region__text") or
                        card.find(class_="region-name") or
                        card.find(class_="b-advert-location")
                    )
                    location = location_el.get_text(strip=True) if location_el else "Lagos"

                    link_el = card.find("a", href=True)
                    if link_el:
                        href = link_el["href"]
                        link = "https://jiji.ng" + href if href.startswith("/") else href
                    else:
                        link = url

                    listing_type = "For Sale" if "sale" in url else "For Rent"

                    listings.append({
                        "title": title,
                        "price": price,
                        "location": location,
                        "link": link,
                        "description": "",
                        "type": listing_type,
                        "source": "Jiji"
                    })
                    print(f"✅ Jiji: {title[:40]}")

                except Exception as e:
                    print(f"Jiji card error: {e}")
                    continue

            time.sleep(3)

        except Exception as e:
            print(f"Jiji error: {e}")
            continue

    return listings

# ============ DAILY POST IDEAS ============
def generate_post_ideas():
    posts = [
        """🔥 ATTENTION LAGOS REAL ESTATE AGENTS! 🔥

Are you tired of spending hours searching for property leads?

Our AI bot scans Lagos & Abuja every 3 hours and sends HOT deals straight to your Telegram!

✅ Fresh listings only — no ghost ads
✅ Direct Mandate GOLD leads
✅ AI scored deals
✅ Only ₦5,000/month

Join our FREE channel first 👇
{free_link}

Or subscribe directly 👇
💳 {pay_link}

#LagosRealEstate #NigeriaProperty #LagosBusiness""",

        """💰 MAKE MORE MONEY AS A LAGOS AGENT IN 2026! 💰

The secret? Let AI find your leads while you close deals!

JunLuisify Realty AI sends you:
🏠 Hot property deals every 3 hours
🥇 Direct Mandate leads (no commission sharing!)
📍 Lagos & Abuja coverage
🤖 AI validates every listing

1000s of agents are already using AI — don't get left behind!

👇 Join FREE today
{free_link}

#LagosProperty #AbujaRealEstate #NigeriaHomes""",

        """🏠 FRESH PROPERTY LEADS EVERY 3 HOURS! 🏠

Imagine waking up to HOT property leads already in your Telegram!

That's exactly what JunLuisify Realty AI does for Nigerian agents!

🔍 Scans PropertyPro & Jiji automatically
🤖 AI removes fake & stale listings
🥇 Flags Direct Mandate properties
💰 Only ₦5,000/month — less than one commission!

Try our FREE channel first 👇
{free_link}

Pay for full access 👇
💳 {pay_link}

#RealEstateNigeria #LagosHomes #PropertyAlert"""
    ]
    return random.choice(posts)

# ============ FORMATTERS ============
def format_free_message(listing, ai_result, is_gold):
    now = datetime.now(WAT).strftime("%H:%M WAT | %b %d, %Y")
    badge = "🔥🔥 PREMIUM GOLD" if is_gold else ("🔥 HOT DEAL" if ai_result["score"] == "HOT" else "📊 FAIR DEAL")
    header = "🥇 GOLD LEAD PREVIEW — DIRECT MANDATE" if is_gold else "🏠 PROPERTY LEAD — JunLuisify Realty AI"

    return f"""<b>{header}</b>

📍 <b>Location:</b> {listing['location']}
🏡 <b>Type:</b> {listing['title'][:60]}
💰 <b>Price:</b> {listing['price']}
🏷️ <b>Listing:</b> {listing['type']}
📊 <b>AI Score:</b> {badge}
🌐 <b>Source:</b> {listing['source']}

💡 {ai_result['reason']}

🔒 <b>Full contact details in PRO group only!</b>
💳 Subscribe: https://flutterwave.com/pay/sec3jwuetm6l

⏰ {now}
<i>— JunLuisify Real Estate AI 🏠</i>"""

def format_paid_message(listing, ai_result, is_gold):
    now = datetime.now(WAT).strftime("%H:%M WAT | %b %d, %Y")
    badge = "🔥🔥 PREMIUM DEAL" if is_gold else ("🔥 HOT DEAL" if ai_result["score"] == "HOT" else "📊 FAIR DEAL")
    header = "🥇 GOLD LEAD — DIRECT MANDATE ⭐" if is_gold else "🏠 HOT PROPERTY LEAD — FULL ACCESS"
    gold_line = "\n⭐ <b>DIRECT FROM OWNER — No agent commission!</b>" if is_gold else ""

    return f"""<b>{header}</b>

📍 <b>Location:</b> {listing['location']}
🏡 <b>Property:</b> {listing['title'][:80]}
💰 <b>Price:</b> {listing['price']}
🏷️ <b>Listing Type:</b> {listing['type']}
🌐 <b>Source:</b> {listing['source']}
📊 <b>AI Score:</b> {badge}{gold_line}

✅ <b>Why it's hot:</b>
{ai_result['reason']}

💡 <b>Agent Tip:</b>
{ai_result['tip']}

🔗 <b>Full Listing:</b> {listing['link']}

⏰ {now}
<i>— JunLuisify Real Estate AI 🏠</i>"""

# ============ MAIN BOT LOGIC ============
def run_bot():
    now = datetime.now(WAT).strftime("%H:%M WAT")
    print(f"\n🔍 Starting scan... {now}")

    stats = load_stats()
    seen = load_seen()

    listings = scrape_propertypro()
    print(f"PropertyPro: {len(listings)} listings")

    jiji_listings = scrape_jiji()
    print(f"Jiji: {len(jiji_listings)} listings")

    listings.extend(jiji_listings)
    print(f"📦 Total: {len(listings)} listings found")

    if not listings:
        print("⚠️ No listings found this run")
        return

    new_count = 0
    free_posted = 0

    for listing in listings:
        listing_id = listing["link"]

        if listing_id in seen:
            print(f"Already seen: {listing_id[:50]}")
            continue

        seen.append(listing_id)
        ai_result = analyze_with_gemini(listing)
        print(f"AI Score: {ai_result['score']} — {listing['title'][:40]}")

        if ai_result["score"] == "SKIP":
            continue

        gold = is_direct_mandate(listing["title"] + " " + listing.get("description", ""))

        paid_msg = format_paid_message(listing, ai_result, gold)
        send_telegram(PAID_CHANNEL_ID, paid_msg)

        if free_posted < 2:
            free_msg = format_free_message(listing, ai_result, gold)
            send_telegram(FREE_CHANNEL_ID, free_msg)
            free_posted += 1

        stats["total_leads"] += 1
        if gold:
            stats["gold_leads"] += 1

        new_count += 1
        time.sleep(3)

    stats["last_scan"] = datetime.now(WAT).strftime("%H:%M WAT | %b %d, %Y")
    save_seen(seen)
    save_stats(stats)
    print(f"✅ Done! {new_count} new leads posted\n")

# ============ TELEGRAM COMMANDS ============
def handle_commands():
    offset = None
    while True:
        try:
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset

            r = requests.get(f"{TELEGRAM_URL}/getUpdates", params=params, timeout=35)
            updates = r.json().get("result", [])

            for update in updates:
                offset = update["update_id"] + 1
                msg = update.get("message", {})
                text = msg.get("text", "")
                chat_id = msg.get("chat", {}).get("id")

                if not chat_id:
                    continue

                if text == "/start":
                    send_telegram(chat_id, """🏠 <b>Welcome to JunLuisify Realty AI!</b>

I scan PropertyPro.ng and Jiji.ng every 3 hours and find the hottest property deals in Lagos and Abuja automatically!

<b>Commands:</b>
/start — Show this message
/status — Check if bot is running
/leads — Force scan right now
/stats — Lead statistics
/post — Get daily Facebook post ideas
/subscribe — Get full access info

💳 Subscribe for full leads:
https://flutterwave.com/pay/sec3jwuetm6l

<i>— JunLuisify Real Estate AI 🏠</i>""")

                elif text == "/status":
                    stats = load_stats()
                    send_telegram(chat_id, f"""✅ <b>Bot Status — RUNNING</b>

🤖 Scanner: Active
⏰ Last Scan: {stats['last_scan']}
📡 Scanning every 3 hours
🌍 Covering: Lagos & Abuja
🌐 Sources: PropertyPro + Jiji

<i>— JunLuisify Real Estate AI 🏠</i>""")

                elif text == "/leads":
                    send_telegram(chat_id, "🔍 <b>Forcing a scan now...</b> Please wait 2 minutes!")
                    Thread(target=run_bot).start()

                elif text == "/stats":
                    stats = load_stats()
                    send_telegram(chat_id, f"""📊 <b>JunLuisify Realty AI Stats</b>

🏠 Total Leads Found: {stats['total_leads']}
🥇 Gold Leads Found: {stats['gold_leads']}
⏰ Last Scan: {stats['last_scan']}
📡 Next Scan: Every 3 hours
🌐 Sources: PropertyPro + Jiji

<i>— JunLuisify Real Estate AI 🏠</i>""")

                elif text == "/post":
                    free_link = "https://t.me/junluisifyrealtyai"
                    pay_link = "https://flutterwave.com/pay/sec3jwuetm6l"
                    post = generate_post_ideas()
                    post = post.replace("{free_link}", free_link).replace("{pay_link}", pay_link)
                    send_telegram(chat_id, f"""📣 <b>Today's Facebook Post Idea:</b>

{post}

<i>Copy and post this on Facebook groups now! 🚀</i>""")

                elif text == "/subscribe":
                    send_telegram(chat_id, """💎 <b>JunLuisify Realty PRO</b>

✅ Fresh Lagos & Abuja leads daily
✅ Full owner/agent contact details
✅ Direct Mandate GOLD leads
✅ AI scored — HOT deals only
✅ Sources: PropertyPro + Jiji
✅ Posted every 3 hours automatically

💰 <b>₦5,000/month only!</b>

💳 Pay here:
https://flutterwave.com/pay/sec3jwuetm6l

📩 After payment WhatsApp me for access!

<i>— JunLuisify Real Estate AI 🏠</i>""")

        except Exception as e:
            print(f"Command error: {e}")
            time.sleep(5)

# ============ FLASK ============
@app.route('/')
def home():
    stats = load_stats()
    return f"""
    <h1>🏠 JunLuisify Realty AI</h1>
    <p>✅ Bot is running!</p>
    <p>📊 Total Leads: {stats['total_leads']}</p>
    <p>🥇 Gold Leads: {stats['gold_leads']}</p>
    <p>⏰ Last Scan: {stats['last_scan']}</p>
    """

# ============ START ============
def start_scheduler():
    run_bot()
    schedule.every(3).hours.do(run_bot)
    while True:
        schedule.run_pending()
        time.sleep(60)

print("🏠 JunLuisify Realty AI Bot Starting...")
print("✅ Scraping PropertyPro + Jiji!")
print("✅ Commands active!")

Thread(target=start_scheduler).start()
Thread(target=handle_commands).start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)
