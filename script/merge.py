#!/usr/bin/env python3
import requests
import re
import os
from datetime import datetime

# ------------------ CONFIGURATION ------------------
PLAYLISTS = [
    {"name": "FANCODE",     "icon": "🏏", "url": "https://raw.githubusercontent.com/doctor-8trange/zyphx8/refs/heads/main/data/fancode.m3u"},
    {"name": "SONYLIV",     "icon": "📺", "url": "https://raw.githubusercontent.com/drmlive/sliv-live-events/refs/heads/main/sonyliv.m3u"},
    {"name": "WILLOW",      "icon": "🏏", "url": "https://raw.githubusercontent.com/srhady/willow-event/refs/heads/main/live_sports.m3u"},
    {"name": "PRIMEVIDEO",  "icon": "📺", "url": "https://raw.githubusercontent.com/doctor-8trange/tekzya9/refs/heads/main/data/primevideoindia.m3u"},
    {"name": "VZY",         "icon": "🎬", "url": "https://premiumplugx.me/vzy/playlist.php"},
    {"name": "JIO-TV",      "icon": "📡", "url": "https://sportlink-playlist.pages.dev/zio.m3u"},
    {"name": "ZEE",         "icon": "📺", "url": "https://vk-playlist.pages.dev/zee3.m3u"},
    {"name": "SONY",        "icon": "📺", "url": "https://vk-playlist.pages.dev/sony.m3u"},
    {"name": "SUN",         "icon": "☀️", "url": "https://vk-playlist.pages.dev/sun.m3u"},
    {"name": "Jio Hotstar", "icon": "⭐", "url": "https://sportlink-playlist.pages.dev/tstar.m3u"},
]

OUTPUT_FILE = "Combined.m3u"
EPG_URL = "https://www.tsepg.cf/epg.xml.gz"

# ------------------ BRANDING SUFFIXES ------------------
SPORTLINK_SUFFIX = " | Sportlink"
VIRAT10_SUFFIX = " @virat10"

# ------------------ CATEGORY OVERRIDE PER SOURCE ------------------
# If a source is listed here, ALL its channels go into that single category.
# If NOT listed, the script will:
#   1. Use the channel's own group-title from the playlist (if present), OR
#   2. Fall back to keyword categorization (categorize_channel) if no group-title.
SOURCE_CATEGORY_OVERRIDE = {
    "FANCODE":     "Fancode",
    "SONYLIV":     "SonyLIV",
    "Jio Hotstar": "Jio Hotstar",
    "WILLOW":      "Willow",
    "PRIMEVIDEO":  "Prime Video",
    "HOTSTAR":     "Hotstar",
    "Sports Special": "Sports Special",
}

# ------------------ KEYWORD CATEGORY MAPPING (fallback only) ------------------
CATEGORY_MAP = {
    "Assamese":   ["assamese", "asomiya"],
    "Bengali":    ["bengali", "bangla", "bn"],
    "Bhojpuri":   ["bhojpuri", "bho"],
    "Gujarati":   ["gujarati", "guj"],
    "Haryanvi":   ["haryanvi"],
    "Kannada":    ["kannada", "kn"],
    "Malayalam":  ["malayalam", "ml"],
    "Marathi":    ["marathi", "mr"],
    "Odia":       ["odia", "oriya"],
    "Punjabi":    ["punjabi", "pa"],
    "Tamil":      ["tamil", "ta"],
    "Telugu":     ["telugu", "te"],
    "Urdu":       ["urdu"],
    "English":    ["english", "en"],
    "French":     ["french", "fr"],
    "Sun":        ["sun tv", "surya", "sun music", "sun news", "sun action", "sun life"],
    "Zee":        ["zee", "zee tv", "zee cinema", "zee news", "zee marathi", "zee bangla"],
    "Sony":       ["sony", "set", "sab", "sony liv", "sony max"],
    "Star":       ["star", "star plus", "star sports", "star movies", "star gold"],
    "Colors":     ["colors", "viacom", "mtv"],
    "Discovery":  ["discovery", "dci"],
    "Nat Geo":    ["nat geo", "national geographic"],
    "Cartoon":    ["cartoon", "cn", "pogo", "nick"],
    "News":       ["news", "ndtv", "republic", "times now", "cnn", "bbc"],
    "Cricket":    ["cricket"],
    "Football":   ["football", "soccer"],
    "Boxing":     ["boxing"],
    "Baseball":   ["baseball"],
    "Business":   ["business", "finance", "cnbc", "bloomberg"],
    "Devotional": ["devotional", "bhakti", "god"],
    "Entertainment": ["entertainment", "ent", "tv", "movies", "series"],
    "Infotainment":  ["infotainment", "documentary", "history", "discovery", "national geographic"],
    "Knowledge":     ["knowledge", "learning", "education"],
}
DEFAULT_CATEGORY = "Other"

# ------------------ CATEGORY ORDER (first = top) ------------------
CATEGORY_ORDER = [
    "Sports Special | Sportlink",
    "Live Events | Sportlink",
    "Fancode | Sportlink",
    "SonyLIV | Sportlink",
    "Willow | Sportlink",
    "Prime Video | Sportlink",
    "Hotstar | Sportlink",
    "Jio Hotstar | Sportlink",
    # VZY's own groups appear below (Movies, Entertainment, Music, News, Sports)
    "Movies | Sportlink",
    "Entertainment | Sportlink",
    "Music | Sportlink",
    "News | Sportlink",
    "Sports | Sportlink",
]

# ------------------ HELPER FUNCTIONS ------------------
def fetch_playlist(url):
    try:
        print(f"  📥 Fetching: {url}")
        resp = requests.get(url, timeout=20)
        resp.raise_for_status()
        lines = resp.text.replace('\r\n', '\n').split('\n')
        print(f"  ✅ Fetched {len(lines)} lines")
        return lines
    except Exception as e:
        print(f"  ❌ Failed: {e}")
        return []

def clean_line(line):
    return line.strip()

def extract_channel_blocks(lines):
    block = []
    for line in lines:
        line = clean_line(line)
        if not line:
            continue
        if line.startswith('#EXTM3U'):
            continue
        if line.startswith('#EXTINF') and block:
            yield block
            block = []
        block.append(line)
    if block:
        yield block

def get_channel_title(block):
    for line in block:
        if line.startswith('#EXTINF'):
            parts = line.rsplit(',', 1)
            if len(parts) > 1:
                return parts[1].strip()
    return None

def get_group_title(block):
    """Extract the existing group-title="..." value from the #EXTINF line."""
    for line in block:
        if line.startswith('#EXTINF'):
            m = re.search(r'group-title="([^"]*)"', line)
            if m:
                val = m.group(1).strip()
                return val if val else None
    return None

def categorize_channel(title):
    if not title:
        return DEFAULT_CATEGORY
    title_lower = title.lower()
    for category, keywords in CATEGORY_MAP.items():
        for kw in keywords:
            if kw in title_lower:
                return category
    return DEFAULT_CATEGORY

def fix_channel_block(block, category):
    """Apply branding suffixes and set correct group-title."""
    new_block = []
    for line in block:
        if line.startswith('#EXTINF'):
            # --- 1. Append @virat10 to tvg-name (or add it if missing) ---
            if 'tvg-name=' in line:
                line = re.sub(
                    r'tvg-name="([^"]*)"',
                    lambda m: f'tvg-name="{m.group(1).strip()}{VIRAT10_SUFFIX}"',
                    line
                )
            else:
                # No tvg-name — create one from the channel title
                parts = line.rsplit(',', 1)
                if len(parts) > 1:
                    title = parts[1].strip()
                    if line.startswith('#EXTINF:-1 '):
                        line = line.replace(
                            '#EXTINF:-1 ',
                            f'#EXTINF:-1 tvg-name="{title}{VIRAT10_SUFFIX}" ',
                            1
                        )

            # --- 2. Set group-title to the category (which already has | Sportlink) ---
            if 'group-title=' in line:
                line = re.sub(r'group-title="[^"]*"', f'group-title="{category}"', line)
            else:
                line = re.sub(r'(#EXTINF:[^,]+)', r'\1 group-title="' + category + '"', line)

            new_block.append(line)
        else:
            new_block.append(line)
    return new_block

# ------------------ MAIN ------------------
def main():
    print("🚀 Starting playlist merge with category grouping...")
    print("=" * 50)

    all_channels = []

    for playlist in PLAYLISTS:
        name = playlist["name"]
        icon = playlist["icon"]
        url = playlist["url"]
        print(f"\n📺 Processing: {icon} {name}")
        lines = fetch_playlist(url)
        if not lines:
            continue

        override_cat = SOURCE_CATEGORY_OVERRIDE.get(name)

        for block in extract_channel_blocks(lines):
            if override_cat:
                # Hard override — all channels go into one category
                base_category = override_cat
            else:
                # Prefer the channel's own group-title from the playlist
                own_group = get_group_title(block)
                if own_group:
                    base_category = own_group
                else:
                    # Fall back to keyword categorization
                    title = get_channel_title(block)
                    base_category = categorize_channel(title)

            # Append Sportlink suffix to every category
            category = f"{base_category}{SPORTLINK_SUFFIX}"
            all_channels.append((category, block))

    # Group by category
    groups = {}
    for cat, block in all_channels:
        groups.setdefault(cat, []).append(block)

    # Order categories
    ordered_cats = []
    for cat in CATEGORY_ORDER:
        if cat in groups:
            ordered_cats.append(cat)
    remaining = sorted([cat for cat in groups.keys() if cat not in CATEGORY_ORDER])
    ordered_cats.extend(remaining)

    # Build output
    out_lines = [f'#EXTM3U x-tvg-url="{EPG_URL}"']

    total = 0
    for cat in ordered_cats:
        blocks = groups[cat]
        count = len(blocks)
        total += count
        out_lines.append(f'#===== {cat} ({count} channels) =====')
        for block in blocks:
            fixed = fix_channel_block(block, cat)
            out_lines.extend(fixed)
            out_lines.append('')   # one blank line after each channel

    # Remove trailing blank lines
    while out_lines and out_lines[-1] == '':
        out_lines.pop()

    # Write file
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            f.write('\n'.join(out_lines))
            f.write('\n')  # final newline
        print("\n" + "=" * 50)
        print(f"✅ Successfully created {OUTPUT_FILE}")
        print(f"📊 Total channels: {total}")
        print(f"📅 Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"📁 File size: {os.path.getsize(OUTPUT_FILE)} bytes")
        print(f"\n📂 Categories (in order): {', '.join(ordered_cats)}")
    except Exception as e:
        print(f"❌ Error writing file: {e}")

if __name__ == "__main__":
    main()
