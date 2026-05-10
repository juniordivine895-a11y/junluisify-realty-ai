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
from requests_oauthlib import OAuth1

app = Flask(__name__)

# ============ CONFIG ============
BOT_TOKEN = "8751991442:AAEiC4uRBlpw1l8zJpV4IF-jAahw-cDFWuA"
GEMINI_KEY = "AIzaSyAQ4n57sXTOatFT7g_7jPtF4BdbjL1CZyQ"
FREE_CHANNEL_ID = "-1003721050699"
PAID_CHANNEL_ID = "-1003903983342"
SCRAPER_KEY = "68f2fbe370a45e3ed3eed98d302a352a"
TWITTER_API_KEY = "g9QElOr2PsJ5t5cMN5TRJ0Nah"
TWITTER_API_SECRET = "3Ira093Lk5uGsPpsNwaPqjjvNehqlwZyMBVFN5H2Twab1nd6PG"
TWITTER_ACCESS_TOKEN = "2045128080134381568-V0JtTCcw1r4EjJl14QOUmZuHzdhD5S"
TWITTER_ACCESS_SECRET = "yVfqPhU7aTGn7LplZAua6fS78vos3DcFIcIZFncgPKlTY"
OWNER_CHAT_ID = "8689011113"

TELEGRAM_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
WAT = pytz.timezone("Africa/Lagos")

DIRECT_MANDATE_KEYWORDS = [
    "direct mandate", "owner direct", "landlord direct",
    "no agent", "direct from owner", "property owner",
    "mandate", "direct let", "direct sale"
]

SEEN_FILE = "seen_listings.json"
STATS_FILE = "stats.json"
LEADS_FILE = "captured_leads.json"

# Conversation context storage
context = {}

# ============ SCRAPER API FETCH ============
def fetch_url(url):
    try:
        api_url = f"http://api.scraperapi.com?api_key={SCRAPER_KEY}&url={url}&country_code=ng"
        r = requests.get(api_url, timeout=60)
        r.encoding = 'utf-8'
        print(f"✅ Fetch status: {r.status_code} | Length: {len(r.text)}")
        return r
    except Exception as e:
        print(f"Fetch error: {e}")
        return None

# ============ STATS ============
def load_stats():
    if os.path.exists(STATS_FILE):
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    return {"total_leads": 0, "gold_leads": 0, "last_scan": "Never", "tweets": 0}

def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)

# ============ CAPTURED LEADS ============
def load_leads():
    if os.path.exists(LEADS_FILE):
        with open(LEADS_FILE, "r") as f:
            return json.load(f)
    return []

def save_lead(lead):
    leads = load_leads()
    leads.append(lead)
    with open(LEADS_FILE, "w") as f:
        json.dump(leads, f)

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

# ============ TWITTER ============
def post_to_twitter(listing, ai_result, is_gold):
    try:
        badge = "🔥🔥 GOLD DEAL" if is_gold else "🔥 HOT DEAL"
        gold_line = "⭐ DIRECT FROM OWNER!\n" if is_gold else ""

        tweet = f"""🏠 FRESH PROPERTY LEAD — Lagos!

📍 {listing['location']}
🏡 {listing['title'][:50]}
💰 {listing['price']}
📊 {badge}
{gold_line}
🔒 Full details for subscribers!
💳 https://flutterwave.com/pay/sec3jwuetm6l

#LagosRealEstate #NigeriaProperty
#LagosHomes #NaijaRealEstate

— @JLuisify68780 🤖🏠"""

        tweet = tweet[:280]

        auth = OAuth1(
            TWITTER_API_KEY,
            TWITTER_API_SECRET,
            TWITTER_ACCESS_TOKEN,
            TWITTER_ACCESS_SECRET
        )

        response = requests.post(
            "https://api.twitter.com/2/tweets",
            json={"text": tweet},
            auth=auth
        )

        print(f"Twitter response: {response.status_code} | {response.text}")

        if response.status_code == 201:
            print(f"✅ Tweeted successfully!")
            return True
        else:
            print(f"❌ Twitter failed: {response.text}")
            return False

    except Exception as e:
        print(f"Twitter error: {e}")
        return False

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
            print(f"Scraping PropertyPro: {url}")
            r = fetch_url(url)
            if not r:
                continue

            soup = BeautifulSoup(r.text, "lxml")

            cards = (
                soup.find_all("div", class_="property-listing") or
                soup.find_all("div", class_="property-listing-grid") or
                soup.find_all("div", class_="listings-property")
            )

            print(f"PropertyPro cards: {len(cards)}")

            for card in cards[:8]:
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
                        card.find(class_="amount") or
                        card.find(class_="property-price") or
                        card.find(string=lambda t: t and "₦" in str(t))
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
                    print(f"✅ PropertyPro: {title[:40]}")

                except Exception as e:
                    print(f"Card error: {e}")
                    continue

            time.sleep(2)

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
    ]

    for url in urls:
        try:
            print(f"Scraping Jiji: {url}")
            r = fetch_url(url)
            if not r:
                continue

            soup = BeautifulSoup(r.text, "lxml")

            cards = (
                soup.find_all("div", class_="b-list-advert__item-wrapper") or
                soup.find_all("article") or
                soup.find_all("li", class_="b-list-advert__item") or
                soup.find_all("div", attrs={"data-qa": "advert"})
            )

            print(f"Jiji cards: {len(cards)}")

            for card in cards[:8]:
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
                        card.find(class_="b-advert-price") or
                        card.find(class_="price")
                    )
                    price = price_el.get_text(strip=True) if price_el else "Price on request"

                    location_el = (
                        card.find(class_="b-list-advert__region__text") or
                        card.find(class_="b-advert-location") or
                        card.find(class_="region-name")
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

            time.sleep(2)

        except Exception as e:
            print(f"Jiji error: {e}")
            continue

    return listings

# ============ DAILY POST IDEAS ============
def generate_post_ideas():
    posts = [
        """🔥 ATTENTION LAGOS REAL ESTATE AGENTS! 🔥

Are you tired of spending hours searching for property leads?

Our AI bot scans Lagos & Abuja every 6 hours and sends HOT deals straight to your Telegram!

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
🏠 Hot property deals every 6 hours
🥇 Direct Mandate leads (no commission sharing!)
📍 Lagos & Abuja coverage
🤖 AI validates every listing

Don't get left behind!

👇 Join FREE today
{free_link}

#LagosProperty #AbujaRealEstate #NigeriaHomes""",

        """🏠 FRESH PROPERTY LEADS EVERY 6 HOURS! 🏠

Imagine waking up to HOT property leads already in your Telegram!

That's exactly what JunLuisify Realty AI does for Nigerian agents!

🔍 Scans PropertyPro & Jiji automatically
🤖 AI removes fake listings
🥇 Flags Direct Mandate properties
💰 Only ₦5,000/month

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
    print(f"PropertyPro: {len(listings)}")

    jiji = scrape_jiji()
    print(f"Jiji: {len(jiji)}")

    listings.extend(jiji)
    print(f"📦 Total: {len(listings)}")

    if not listings:
        print("⚠️ No listings found")
        return

    new_count = 0
    free_posted = 0
    twitter_posted = 0

    for listing in listings:
        listing_id = listing["link"]
        if listing_id in seen:
            continue

        seen.append(listing_id)
        ai_result = analyze_with_gemini(listing)
        print(f"AI: {ai_result['score']} — {listing['title'][:40]}")

        if ai_result["score"] == "SKIP":
            continue

        gold = is_direct_mandate(listing["title"] + " " + listing.get("description", ""))

        send_telegram(PAID_CHANNEL_ID, format_paid_message(listing, ai_result, gold))

        if free_posted < 2:
            send_telegram(FREE_CHANNEL_ID, format_free_message(listing, ai_result, gold))
            free_posted += 1

        if twitter_posted < 3:
            post_to_twitter(listing, ai_result, gold)
            twitter_posted += 1
            stats["tweets"] = stats.get("tweets", 0) + 1

        stats["total_leads"] += 1
        if gold:
            stats["gold_leads"] += 1

        new_count += 1
        time.sleep(3)

    stats["last_scan"] = datetime.now(WAT).strftime("%H:%M WAT | %b %d, %Y")
    save_seen(seen)
    save_stats(stats)
    print(f"✅ Done! {new_count} leads | {twitter_posted} tweets\n")

# ============ AI QUALIFIER — AGENT ============
def handle_agent_flow(chat_id, text, user_name):
    global context

    if chat_id not in context:
        context[chat_id] = {}

    step = context[chat_id].get("step", "")

    if text == "/agent" or step == "":
        context[chat_id] = {"type": "agent", "step": "agent_type"}
        send_telegram(chat_id, f"""🏠 <b>Welcome to JunLuisify Realty AI!</b>

Hi {user_name}! I help real estate agents get fresh Lagos & Abuja property leads automatically!

Let's get you started! 😊

<b>What type of agent are you?</b>

1️⃣ Independent Agent
2️⃣ Agency/Company
3️⃣ Property Developer

Reply with <b>1, 2 or 3</b> 👇""")
        return True

    if step == "agent_type" and text in ["1", "2", "3"]:
        types = {"1": "Independent Agent", "2": "Agency/Company", "3": "Property Developer"}
        context[chat_id]["agent_type"] = types[text]
        context[chat_id]["step"] = "agent_location"
        send_telegram(chat_id, """📍 <b>Which area do you cover?</b>

1️⃣ Lagos Island
2️⃣ Lagos Mainland
3️⃣ Abuja
4️⃣ Both Lagos & Abuja

Reply with <b>1, 2, 3 or 4</b> 👇""")
        return True

    if step == "agent_location" and text in ["1", "2", "3", "4"]:
        locations = {"1": "Lagos Island", "2": "Lagos Mainland", "3": "Abuja", "4": "Lagos & Abuja"}
        context[chat_id]["location"] = locations[text]
        context[chat_id]["step"] = "agent_experience"
        send_telegram(chat_id, """📅 <b>How long have you been an agent?</b>

1️⃣ Less than 1 year
2️⃣ 1 - 3 years
3️⃣ 3 - 5 years
4️⃣ 5+ years

Reply with <b>1, 2, 3 or 4</b> 👇""")
        return True

    if step == "agent_experience" and text in ["1", "2", "3", "4"]:
        experience = {"1": "Less than 1 year", "2": "1-3 years", "3": "3-5 years", "4": "5+ years"}
        context[chat_id]["experience"] = experience[text]
        context[chat_id]["step"] = "agent_ready"
        send_telegram(chat_id, """💰 <b>Are you ready to get more leads?</b>

1️⃣ Yes — I want more leads now!
2️⃣ Just looking for now

Reply with <b>1 or 2</b> 👇""")
        return True

    if step == "agent_ready" and text in ["1", "2"]:
        if text == "1":
            context[chat_id]["step"] = "done"
            agent_type = context[chat_id].get("agent_type", "Agent")
            location = context[chat_id].get("location", "Lagos")
            experience = context[chat_id].get("experience", "N/A")

            # Alert owner
            send_telegram(OWNER_CHAT_ID, f"""🔥 <b>NEW SERIOUS AGENT DETECTED!</b>

👤 Name: {user_name}
🏢 Type: {agent_type}
📍 Location: {location}
📅 Experience: {experience}
💬 Chat ID: {chat_id}
⏰ Time: {datetime.now(WAT).strftime("%H:%M WAT | %b %d, %Y")}

<b>Action: Contact them immediately!</b>""")

            # Save lead
            save_lead({
                "type": "agent",
                "name": user_name,
                "chat_id": chat_id,
                "agent_type": agent_type,
                "location": location,
                "experience": experience,
                "status": "HOT",
                "date": datetime.now(WAT).strftime("%H:%M WAT | %b %d, %Y")
            })

            send_telegram(chat_id, f"""🎉 <b>Excellent! You're exactly who we help!</b>

Here's what you get with JunLuisify Realty AI PRO:

✅ 100+ fresh Lagos & Abuja leads daily
✅ Direct Mandate GOLD leads
✅ AI scored HOT deals only
✅ Instant Telegram delivery
✅ Cancel anytime

💰 <b>Only ₦5,000/month!</b>

🎁 <b>Special offer: 3 days FREE trial!</b>
No payment needed to start!

👇 Join our FREE channel first and see leads dropping:
t.me/junluisifyrealtyai

💳 Ready to subscribe?
flutterwave.com/pay/sec3jwuetm6l

📩 WhatsApp after payment for instant PRO access:
wa.me/2349138643885

<i>— JunLuisify Real Estate AI 🏠</i>""")
        else:
            context[chat_id] = {}
            send_telegram(chat_id, """No problem! 😊

Join our FREE channel to see leads dropping daily:
👉 t.me/junluisifyrealtyai

Come back anytime when you're ready! 🏠""")
        return True

    return False

# ============ AI QUALIFIER — BUYER ============
def handle_buyer_flow(chat_id, text, user_name):
    global context

    if chat_id not in context:
        context[chat_id] = {}

    step = context[chat_id].get("step", "")

    if text == "/buyer" or step == "":
        context[chat_id] = {"type": "buyer", "step": "buyer_intent"}
        send_telegram(chat_id, f"""🏠 <b>Welcome to JunLuisify Realty AI!</b>

Hi {user_name}! I help connect serious buyers with the best Lagos & Abuja properties!

<b>What are you looking for?</b>

1️⃣ Buy a property
2️⃣ Rent a property

Reply with <b>1 or 2</b> 👇""")
        return True

    if step == "buyer_intent" and text in ["1", "2"]:
        intents = {"1": "Buy", "2": "Rent"}
        context[chat_id]["intent"] = intents[text]
        context[chat_id]["step"] = "buyer_location"
        send_telegram(chat_id, """📍 <b>Which location interests you?</b>

1️⃣ Lagos Island (Lekki, VI, Ikoyi)
2️⃣ Lagos Mainland (Ikeja, Surulere)
3️⃣ Abuja (Maitama, Wuse, Gwarinpa)
4️⃣ Open to any location

Reply with <b>1, 2, 3 or 4</b> 👇""")
        return True

    if step == "buyer_location" and text in ["1", "2", "3", "4"]:
        locations = {
            "1": "Lagos Island",
            "2": "Lagos Mainland",
            "3": "Abuja",
            "4": "Any Location"
        }
        context[chat_id]["location"] = locations[text]
        context[chat_id]["step"] = "buyer_budget"
        send_telegram(chat_id, """💰 <b>What is your budget?</b>

1️⃣ Under ₦20,000,000
2️⃣ ₦20M - ₦50M
3️⃣ ₦50M - ₦100M
4️⃣ Above ₦100M

Reply with <b>1, 2, 3 or 4</b> 👇""")
        return True

    if step == "buyer_budget" and text in ["1", "2", "3", "4"]:
        budgets = {
            "1": "Under ₦20M",
            "2": "₦20M - ₦50M",
            "3": "₦50M - ₦100M",
            "4": "Above ₦100M"
        }
        context[chat_id]["budget"] = budgets[text]
        context[chat_id]["step"] = "buyer_timeline"
        send_telegram(chat_id, """⏰ <b>When are you ready to buy/rent?</b>

1️⃣ Immediately — ready now!
2️⃣ Within 1 month
3️⃣ Within 3 months
4️⃣ Just looking for now

Reply with <b>1, 2, 3 or 4</b> 👇""")
        return True

    if step == "buyer_timeline" and text in ["1", "2", "3", "4"]:
        timelines = {
            "1": "Immediately",
            "2": "Within 1 month",
            "3": "Within 3 months",
            "4": "Just looking"
        }
        timeline = timelines[text]
        context[chat_id]["timeline"] = timeline
        context[chat_id]["step"] = "done"

        intent = context[chat_id].get("intent", "Buy")
        location = context[chat_id].get("location", "Lagos")
        budget = context[chat_id].get("budget", "N/A")
        is_hot = text in ["1", "2"]

        # Alert owner
        hot_badge = "🔥 HOT BUYER" if is_hot else "👤 New Buyer"
        send_telegram(OWNER_CHAT_ID, f"""🏠 <b>{hot_badge} DETECTED!</b>

👤 Name: {user_name}
🎯 Intent: {intent}
📍 Location: {location}
💰 Budget: {budget}
⏰ Timeline: {timeline}
💬 Chat ID: {chat_id}
🕐 Time: {datetime.now(WAT).strftime("%H:%M WAT | %b %d, %Y")}

{"<b>⚡ SERIOUS BUYER — Contact immediately!</b>" if is_hot else "Warm lead — follow up soon"}""")

        # Save lead
        save_lead({
            "type": "buyer",
            "name": user_name,
            "chat_id": chat_id,
            "intent": intent,
            "location": location,
            "budget": budget,
            "timeline": timeline,
            "status": "HOT" if is_hot else "WARM",
            "date": datetime.now(WAT).strftime("%H:%M WAT | %b %d, %Y")
        })

        if is_hot:
            send_telegram(chat_id, f"""🎉 <b>Great news! We have properties matching your needs!</b>

📍 Location: {location}
💰 Budget: {budget}
🎯 Looking to: {intent}

Our AI is scanning for the best matches right now!

A property specialist will contact you shortly on WhatsApp to share the best options!

📩 Or reach us directly:
wa.me/2349138643885

🌐 View our listings:
junluisify-realty-ai-mnrd.onrender.com

<i>— JunLuisify Real Estate AI 🏠</i>""")
        else:
            send_telegram(chat_id, """No problem! 😊

Join our FREE channel to see fresh Lagos & Abuja properties daily:
👉 t.me/junluisifyrealtyai

When you're ready to buy/rent — we're here! 🏠

📩 WhatsApp us anytime:
wa.me/2349138643885""")

        context[chat_id] = {}
        return True

    return False

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
                chat_id = str(msg.get("chat", {}).get("id"))
                user = msg.get("from", {})
                user_name = user.get("first_name", "Friend")

                if not chat_id or not text:
                    continue

                # Check if in agent flow
                if chat_id in context and context[chat_id].get("type") == "agent":
                    if handle_agent_flow(chat_id, text, user_name):
                        continue

                # Check if in buyer flow
                if chat_id in context and context[chat_id].get("type") == "buyer":
                    if handle_buyer_flow(chat_id, text, user_name):
                        continue

                if text == "/start":
                    send_telegram(chat_id, f"""🏠 <b>Welcome to JunLuisify Realty AI!</b>

Hi {user_name}! I'm Nigeria's #1 AI-powered real estate lead bot!

<b>What would you like to do?</b>

🏘️ /agent — I'm a real estate agent
🏠 /buyer — I'm looking to buy/rent
📊 /leads — Force a property scan
📈 /stats — View bot statistics
📣 /post — Get Facebook post ideas
💎 /subscribe — View subscription plans
✅ /status — Check bot status

<i>— JunLuisify Real Estate AI 🏠</i>""")

                elif text == "/agent":
                    context[chat_id] = {}
                    handle_agent_flow(chat_id, text, user_name)

                elif text == "/buyer":
                    context[chat_id] = {}
                    handle_buyer_flow(chat_id, text, user_name)

                elif text == "/status":
                    stats = load_stats()
                    send_telegram(chat_id, f"""✅ <b>Bot Status — RUNNING</b>

🤖 Scanner: Active
⏰ Last Scan: {stats['last_scan']}
📡 Scanning every 6 hours
🌍 Covering: Lagos & Abuja
🌐 Sources: PropertyPro + Jiji

<i>— JunLuisify Real Estate AI 🏠</i>""")

                elif text == "/leads":
                    send_telegram(chat_id, "🔍 <b>Forcing a scan now...</b> Please wait!")
                    Thread(target=run_bot).start()

                elif text == "/stats":
                    stats = load_stats()
                    leads = load_leads()
                    agents = [l for l in leads if l["type"] == "agent"]
                    buyers = [l for l in leads if l["type"] == "buyer"]
                    send_telegram(chat_id, f"""📊 <b>JunLuisify Realty AI Stats</b>

🏠 Total Leads Found: {stats['total_leads']}
🥇 Gold Leads Found: {stats['gold_leads']}
🐦 Total Tweets: {stats.get('tweets', 0)}
👔 Agents Captured: {len(agents)}
🏠 Buyers Captured: {len(buyers)}
⏰ Last Scan: {stats['last_scan']}
📡 Next Scan: Every 6 hours

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

✅ 100+ fresh Lagos & Abuja leads daily
✅ Full owner/agent contact details
✅ Direct Mandate GOLD leads
✅ AI scored — HOT deals only
✅ Posted every 6 hours automatically

💰 <b>Only ₦5,000/month!</b>

💳 Pay here:
https://flutterwave.com/pay/sec3jwuetm6l

📩 WhatsApp after payment:
wa.me/2349138643885

<i>— JunLuisify Real Estate AI 🏠</i>""")

                elif text == "/myagents":
                    if chat_id == OWNER_CHAT_ID:
                        leads = load_leads()
                        agents = [l for l in leads if l["type"] == "agent"]
                        if not agents:
                            send_telegram(chat_id, "No agents captured yet!")
                        else:
                            msg = "<b>👔 Captured Agents:</b>\n\n"
                            for a in agents[-10:]:
                                msg += f"👤 {a['name']} | {a.get('agent_type','N/A')} | {a.get('location','N/A')} | {a.get('status','N/A')}\n"
                            send_telegram(chat_id, msg)

                elif text == "/mybuyers":
                    if chat_id == OWNER_CHAT_ID:
                        leads = load_leads()
                        buyers = [l for l in leads if l["type"] == "buyer"]
                        if not buyers:
                            send_telegram(chat_id, "No buyers captured yet!")
                        else:
                            msg = "<b>🏠 Captured Buyers:</b>\n\n"
                            for b in buyers[-10:]:
                                msg += f"👤 {b['name']} | {b.get('intent','N/A')} | {b.get('location','N/A')} | {b.get('budget','N/A')} | {b.get('status','N/A')}\n"
                            send_telegram(chat_id, msg)

                else:
                    # Handle ongoing conversations
                    if chat_id in context:
                        if context[chat_id].get("type") == "agent":
                            handle_agent_flow(chat_id, text, user_name)
                        elif context[chat_id].get("type") == "buyer":
                            handle_buyer_flow(chat_id, text, user_name)

        except Exception as e:
            print(f"Command error: {e}")
            time.sleep(5)

# ============ FLASK ============
@app.route('/test-twitter')
def test_twitter():
    try:
        auth = OAuth1(
            TWITTER_API_KEY,
            TWITTER_API_SECRET,
            TWITTER_ACCESS_TOKEN,
            TWITTER_ACCESS_SECRET
        )
        tweet = "🏠 Test tweet from JunLuisify Realty AI bot! Lagos property leads 24/7 🤖 #LagosRealEstate"
        response = requests.post(
            "https://api.twitter.com/2/tweets",
            json={"text": tweet},
            auth=auth
        )
        return f"Status: {response.status_code} | Response: {response.text}"
    except Exception as e:
        return f"Error: {e}"

@app.route('/')
def home():
    stats = load_stats()
    leads = load_leads()
    agents = len([l for l in leads if l["type"] == "agent"])
    buyers = len([l for l in leads if l["type"] == "buyer"])
    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>JunLuisify Realty AI — Nigeria's #1 Property Lead Bot</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Segoe UI', sans-serif; background: #fff; color: #333; }}
        nav {{
            background: linear-gradient(135deg, #1a7a3c, #25a55a);
            padding: 15px 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            position: sticky;
            top: 0;
            z-index: 100;
            box-shadow: 0 2px 10px rgba(0,0,0,0.2);
        }}
        .logo {{ color: white; font-size: 20px; font-weight: bold; }}
        .logo span {{ color: #ffb6c1; }}
        .nav-btn {{
            background: #ffb6c1;
            color: #1a7a3c;
            padding: 8px 16px;
            border-radius: 20px;
            text-decoration: none;
            font-weight: bold;
            font-size: 14px;
        }}
        .hero {{
            background: linear-gradient(135deg, #1a7a3c 0%, #25a55a 50%, #ffb6c1 100%);
            padding: 60px 20px;
            text-align: center;
            color: white;
        }}
        .hero h1 {{ font-size: 28px; margin-bottom: 15px; line-height: 1.3; }}
        .hero h1 span {{ color: #ffb6c1; }}
        .hero p {{ font-size: 16px; margin-bottom: 30px; opacity: 0.95; line-height: 1.6; }}
        .hero-btns {{ display: flex; gap: 15px; justify-content: center; flex-wrap: wrap; }}
        .btn-primary {{
            background: white;
            color: #1a7a3c;
            padding: 14px 28px;
            border-radius: 25px;
            text-decoration: none;
            font-weight: bold;
            font-size: 16px;
            box-shadow: 0 4px 15px rgba(0,0,0,0.2);
        }}
        .btn-secondary {{
            background: #ffb6c1;
            color: #1a7a3c;
            padding: 14px 28px;
            border-radius: 25px;
            text-decoration: none;
            font-weight: bold;
            font-size: 16px;
        }}
        .stats {{
            background: #f9f9f9;
            padding: 40px 20px;
            text-align: center;
        }}
        .stats h2 {{ color: #1a7a3c; font-size: 22px; margin-bottom: 25px; }}
        .stats-grid {{ display: flex; gap: 15px; justify-content: center; flex-wrap: wrap; }}
        .stat-card {{
            background: white;
            border-radius: 15px;
            padding: 20px 25px;
            box-shadow: 0 3px 15px rgba(0,0,0,0.1);
            border-top: 4px solid #1a7a3c;
            min-width: 130px;
        }}
        .stat-number {{ font-size: 32px; font-weight: bold; color: #1a7a3c; }}
        .stat-label {{ font-size: 13px; color: #666; margin-top: 5px; }}
        .features {{ padding: 50px 20px; text-align: center; background: white; }}
        .features h2 {{ color: #1a7a3c; font-size: 24px; margin-bottom: 30px; }}
        .features-grid {{ display: flex; gap: 20px; justify-content: center; flex-wrap: wrap; max-width: 900px; margin: 0 auto; }}
        .feature-card {{
            background: linear-gradient(135deg, #f0fff4, #fff);
            border-radius: 15px;
            padding: 25px 20px;
            width: 250px;
            box-shadow: 0 3px 15px rgba(0,0,0,0.08);
            border: 1px solid #e0f0e8;
        }}
        .feature-icon {{ font-size: 35px; margin-bottom: 12px; }}
        .feature-card h3 {{ color: #1a7a3c; margin-bottom: 8px; font-size: 16px; }}
        .feature-card p {{ color: #666; font-size: 14px; line-height: 1.5; }}
        .pricing {{
            background: linear-gradient(135deg, #fff0f3, #fff);
            padding: 50px 20px;
            text-align: center;
        }}
        .pricing h2 {{ color: #1a7a3c; font-size: 24px; margin-bottom: 30px; }}
        .pricing-cards {{ display: flex; gap: 20px; justify-content: center; flex-wrap: wrap; }}
        .pricing-card {{
            background: white;
            border-radius: 20px;
            padding: 35px 30px;
            max-width: 300px;
            box-shadow: 0 5px 25px rgba(0,0,0,0.12);
            border: 3px solid #ffb6c1;
        }}
        .pricing-badge {{
            background: #ffb6c1;
            color: #1a7a3c;
            padding: 5px 15px;
            border-radius: 15px;
            font-size: 13px;
            font-weight: bold;
            display: inline-block;
            margin-bottom: 15px;
        }}
        .price {{ font-size: 42px; font-weight: bold; color: #1a7a3c; }}
        .price span {{ font-size: 18px; color: #666; }}
        .pricing-features {{ list-style: none; margin: 20px 0; text-align: left; }}
        .pricing-features li {{ padding: 8px 0; color: #555; font-size: 15px; border-bottom: 1px solid #f0f0f0; }}
        .pricing-features li::before {{ content: "✅ "; }}
        .btn-pay {{
            background: linear-gradient(135deg, #1a7a3c, #25a55a);
            color: white;
            padding: 15px 35px;
            border-radius: 25px;
            text-decoration: none;
            font-weight: bold;
            font-size: 16px;
            display: inline-block;
            margin-top: 10px;
            box-shadow: 0 4px 15px rgba(26,122,60,0.3);
        }}
        .how {{ padding: 50px 20px; background: white; text-align: center; }}
        .how h2 {{ color: #1a7a3c; font-size: 24px; margin-bottom: 30px; }}
        .steps {{ display: flex; gap: 20px; justify-content: center; flex-wrap: wrap; max-width: 800px; margin: 0 auto; }}
        .step {{ background: #f9f9f9; border-radius: 15px; padding: 25px 20px; width: 180px; }}
        .step-num {{
            background: #1a7a3c;
            color: white;
            width: 35px;
            height: 35px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-weight: bold;
            margin: 0 auto 12px;
        }}
        .step h3 {{ color: #1a7a3c; font-size: 15px; margin-bottom: 8px; }}
        .step p {{ color: #666; font-size: 13px; line-height: 1.5; }}
        .cta {{
            background: linear-gradient(135deg, #1a7a3c, #25a55a);
            padding: 50px 20px;
            text-align: center;
            color: white;
        }}
        .cta h2 {{ font-size: 24px; margin-bottom: 15px; }}
        .cta p {{ font-size: 16px; margin-bottom: 25px; opacity: 0.9; }}
        .cta-btns {{ display: flex; gap: 15px; justify-content: center; flex-wrap: wrap; }}
        .btn-whatsapp {{
            background: #25D366;
            color: white;
            padding: 14px 28px;
            border-radius: 25px;
            text-decoration: none;
            font-weight: bold;
            font-size: 16px;
        }}
        .btn-telegram {{
            background: #0088cc;
            color: white;
            padding: 14px 28px;
            border-radius: 25px;
            text-decoration: none;
            font-weight: bold;
            font-size: 16px;
        }}
        footer {{
            background: #1a1a1a;
            color: #aaa;
            padding: 25px 20px;
            text-align: center;
            font-size: 13px;
        }}
        footer span {{ color: #ffb6c1; }}
        .float-wa {{
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: #25D366;
            color: white;
            width: 55px;
            height: 55px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 28px;
            text-decoration: none;
            box-shadow: 0 4px 15px rgba(0,0,0,0.3);
            z-index: 999;
        }}
        .ticker {{
            background: #ffb6c1;
            color: #1a7a3c;
            padding: 10px 0;
            overflow: hidden;
            white-space: nowrap;
        }}
        .ticker-content {{
            display: inline-block;
            animation: ticker 20s linear infinite;
            font-weight: bold;
            font-size: 14px;
        }}
        @keyframes ticker {{
            0% {{ transform: translateX(100vw); }}
            100% {{ transform: translateX(-100%); }}
        }}
    </style>
</head>
<body>

<nav>
    <div class="logo">🏠 JunLuisify <span>Realty AI</span></div>
    <a href="https://flutterwave.com/pay/sec3jwuetm6l" class="nav-btn">Subscribe ₦5,000</a>
</nav>

<div class="ticker">
    <div class="ticker-content">
        🏠 Fresh Lagos property leads every 6 hours! &nbsp;&nbsp;&nbsp;
        🥇 Direct Mandate GOLD leads available! &nbsp;&nbsp;&nbsp;
        📍 Covering Lagos & Abuja 24/7! &nbsp;&nbsp;&nbsp;
        🤖 AI-powered property scanning! &nbsp;&nbsp;&nbsp;
        💰 Only ₦5,000/month for full access! &nbsp;&nbsp;&nbsp;
        🔥 {stats['total_leads']}+ leads found so far! &nbsp;&nbsp;&nbsp;
        👔 {agents} agents captured! &nbsp;&nbsp;&nbsp;
        🏠 {buyers} buyers captured!
    </div>
</div>

<div class="hero">
    <h1>Nigeria's #1 <span>AI-Powered</span><br>Real Estate Lead Bot 🏠</h1>
    <p>Get fresh Lagos & Abuja property leads<br>delivered to your Telegram every 6 hours — automatically!</p>
    <div class="hero-btns">
        <a href="https://flutterwave.com/pay/sec3jwuetm6l" class="btn-primary">💳 Subscribe Now — ₦5,000/month</a>
        <a href="https://t.me/junluisifyrealtyai" class="btn-secondary">📱 Join Free Channel</a>
    </div>
</div>

<div class="stats">
    <h2>📊 Live Bot Statistics</h2>
    <div class="stats-grid">
        <div class="stat-card">
            <div class="stat-number">{stats['total_leads']}+</div>
            <div class="stat-label">Total Leads Found</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{stats['gold_leads']}+</div>
            <div class="stat-label">Gold Leads</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{agents}+</div>
            <div class="stat-label">Agents Captured</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">{buyers}+</div>
            <div class="stat-label">Buyers Captured</div>
        </div>
        <div class="stat-card">
            <div class="stat-number">24/7</div>
            <div class="stat-label">Always Running</div>
        </div>
    </div>
    <p style="margin-top:20px;color:#666;font-size:14px;">Last scan: {stats['last_scan']}</p>
</div>

<div class="features">
    <h2>🚀 Why Choose JunLuisify Realty AI?</h2>
    <div class="features-grid">
        <div class="feature-card">
            <div class="feature-icon">🤖</div>
            <h3>AI-Powered Analysis</h3>
            <p>Every listing analysed by Gemini AI — only HOT deals reach you!</p>
        </div>
        <div class="feature-card">
            <div class="feature-icon">⚡</div>
            <h3>Real-Time Alerts</h3>
            <p>Fresh leads posted to your Telegram every 6 hours automatically!</p>
        </div>
        <div class="feature-card">
            <div class="feature-icon">🥇</div>
            <h3>Gold Mandate Leads</h3>
            <p>Direct owner listings flagged separately — no agent commission!</p>
        </div>
        <div class="feature-card">
            <div class="feature-icon">👥</div>
            <h3>Buyer Matching</h3>
            <p>AI qualifies buyers automatically and matches them with properties!</p>
        </div>
        <div class="feature-card">
            <div class="feature-icon">📍</div>
            <h3>Lagos & Abuja</h3>
            <p>Covering Nigeria's two biggest property markets simultaneously!</p>
        </div>
        <div class="feature-card">
            <div class="feature-icon">💰</div>
            <h3>Affordable Price</h3>
            <p>Only ₦5,000/month — less than one property commission!</p>
        </div>
    </div>
</div>

<div class="pricing">
    <h2>💎 Simple Pricing</h2>
    <div class="pricing-cards">
        <div class="pricing-card">
            <div class="pricing-badge">✅ BASIC</div>
            <div class="price">₦5,000<span>/month</span></div>
            <ul class="pricing-features">
                <li>100+ fresh leads daily</li>
                <li>Full contact details</li>
                <li>Direct Mandate GOLD leads</li>
                <li>Lagos & Abuja coverage</li>
                <li>Instant Telegram delivery</li>
                <li>Cancel anytime</li>
            </ul>
            <a href="https://flutterwave.com/pay/sec3jwuetm6l" class="btn-pay">💳 Subscribe Now</a>
        </div>
        <div class="pricing-card" style="border-color: #1a7a3c;">
            <div class="pricing-badge" style="background:#1a7a3c;color:white;">🔥 PREMIUM</div>
            <div class="price">₦15,000<span>/month</span></div>
            <ul class="pricing-features">
                <li>Everything in Basic</li>
                <li>AI buyer matching</li>
                <li>Serious buyer alerts</li>
                <li>Priority support</li>
                <li>First access to Gold leads</li>
                <li>Cancel anytime</li>
            </ul>
            <a href="https://wa.me/2349138643885" class="btn-pay" style="background:linear-gradient(135deg,#ffb6c1,#ff69b4);color:#1a7a3c;">💬 WhatsApp Us</a>
        </div>
    </div>
</div>

<div class="how">
    <h2>⚙️ How It Works</h2>
    <div class="steps">
        <div class="step">
            <div class="step-num">1</div>
            <h3>Subscribe</h3>
            <p>Pay ₦5,000/month via Flutterwave!</p>
        </div>
        <div class="step">
            <div class="step-num">2</div>
            <h3>Get Access</h3>
            <p>WhatsApp us after payment for instant PRO access!</p>
        </div>
        <div class="step">
            <div class="step-num">3</div>
            <h3>Receive Leads</h3>
            <p>Bot posts fresh leads every 6 hours automatically!</p>
        </div>
        <div class="step">
            <div class="step-num">4</div>
            <h3>Close Deals</h3>
            <p>Contact owners directly and close deals faster!</p>
        </div>
    </div>
</div>

<div class="cta">
    <h2>🚀 Ready To Get Fresh Leads Daily?</h2>
    <p>Join Lagos & Abuja agents already using JunLuisify Realty AI!</p>
    <div class="cta-btns">
        <a href="https://flutterwave.com/pay/sec3jwuetm6l" class="btn-primary">💳 Subscribe — ₦5,000/month</a>
        <a href="https://wa.me/2349138643885" class="btn-whatsapp">💬 WhatsApp Us</a>
        <a href="https://t.me/junluisifyrealtyai" class="btn-telegram">📱 Free Channel</a>
    </div>
</div>

<footer>
    <p>🏠 <span>JunLuisify Realty AI</span> — Nigeria's #1 AI Property Lead Bot</p>
    <p style="margin-top:8px;">📍 Covering Lagos & Abuja | 🤖 Powered by Gemini AI | ⚡ 24/7 Automated</p>
    <p style="margin-top:8px;">© 2026 JunLuisify Realty AI. All rights reserved.</p>
</footer>

<a href="https://wa.me/2349138643885" class="float-wa">💬</a>

</body>
</html>
"""

# ============ START ============
def start_scheduler():
    run_bot()
    schedule.every(6).hours.do(run_bot)
    while True:
        schedule.run_pending()
        time.sleep(60)

print("🏠 JunLuisify Realty AI Bot Starting...")
print("✅ ScraperAPI enabled!")
print("✅ Scraping PropertyPro + Jiji!")
print("✅ Twitter auto-posting active!")
print("✅ AI Agent & Buyer Qualifier active!")
print("✅ Commands active!")

Thread(target=start_scheduler).start()
Thread(target=handle_commands).start()

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=8080)
