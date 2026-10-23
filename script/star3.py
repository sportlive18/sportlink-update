import urllib.request
import urllib.parse
import json
import re

# ---------- CONFIG ----------
JSON_URL   = "https://sportlink-jtv.pages.dev/hstar.json"
OUTPUT     = "tstar.m3u"


COOKIE     = "hdntl=exp=1792850105~acl=%2f*~id=17f4efad3eaf4916ce22ceda62f3c484~data=hdntl~hmac=d3a06d3cce344555daf10c63d8313ae7ce53f153eae492204eb1f44034acec87"

USER_AGENT = "Virat"
REFERER    = "https://www.hotstar.com/"
ORIGIN     = "https://www.hotstar.com"
TIMEOUT    = 15

# Order matters: first match wins
PRIORITY = [
    ["bigboss", "big boss", "bigg boss"],          # 1. Bigg Boss channels
    ["tata ipl"],                                   # 2. TATA IPL LIVE TV
    ["savdhaan india"],                             # 3. Savdhaan India: Crime 24/7
]
# ----------------------------


def http_get(url, headers=None, timeout=TIMEOUT):
    req = urllib.request.Request(
        url, headers=headers or {"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="ignore")


def fetch_json(url):
    return json.loads(http_get(url))


def is_mpd(url):
    """Return True if the URL path ends with .mpd (ignores query string)."""
    try:
        path = urllib.parse.urlparse(url).path
    except Exception:
        path = url
    return path.lower().endswith(".mpd")


def get_clearkey(item):
    """Extract (key_id, key) from an item using several possible field names."""
    key_id = (
        item.get("keyId")
        or item.get("key_id")
        or item.get("kid")
        or item.get("clearkey_id")
    )
    key = (
        item.get("key")
        or item.get("clearkey")
        or item.get("ck")
    )

    # Sometimes keys come as a single "kid:key" string
    if not key_id and not key:
        combined = item.get("clearkey") or item.get("license_key") or ""
        if isinstance(combined, str) and ":" in combined:
            a, b = combined.split(":", 1)
            return a.strip(), b.strip()

    if key_id and key:
        return str(key_id).strip(), str(key).strip()
    return None, None


def sort_items(items):
    """Order: Bigg Boss -> TATA IPL -> Savdhaan India -> rest."""
    buckets = [[] for _ in PRIORITY]
    rest = []

    for it in items:
        name = (it.get("name") or "").lower()
        placed = False
        for i, keys in enumerate(PRIORITY):
            if any(k in name for k in keys):
                buckets[i].append(it)
                placed = True
                break
        if not placed:
            rest.append(it)

    ordered = []
    for b in buckets:
        ordered.extend(b)
    ordered.extend(rest)
    return ordered


def generate_m3u(items, cookie, out_file):
    items = sort_items(items)
    lines = [
        "#EXTM3U",
        "#DATE:- 07-10-2026 23:25",
        "# Written and Directed by sayan",
        "# Join us on Telegram: t.me/sportlink10",
    ]
    written = 0

    for item in items:
        url = (item.get("url") or item.get("mpd_url") or "").strip()
        if not url:
            continue

        name     = item.get("name", "Unknown")
        logo     = item.get("logo", "")
        category = item.get("group") or item.get("category") or "Other"

        lines.append(
            f'#EXTINF:-1 tvg-name="{name}" tvg-logo="{logo}" '
            f'group-title="{category}", {name}'
        )

        # ---- DRM / manifest type props (always for MPD) ----
        if is_mpd(url):
            key_id, key = get_clearkey(item)

            lines.append("#KODIPROP:inputstream=inputstream.adaptive")
            lines.append("#KODIPROP:inputstream.adaptive.manifest_type=mpd")
            # Headers for the manifest + segments (needed by Kodi's adaptive addon)
            lines.append(
                "#KODIPROP:inputstream.adaptive.stream_headers="
                f"User-Agent={USER_AGENT}&Referer={REFERER}&Origin={ORIGIN}"
            )
            lines.append(
                f"#KODIPROP:inputstream.adaptive.license_key={key_id or ''}:{key or ''}"
            )
            if key_id and key:
                lines.append(
                    "#KODIPROP:inputstream.adaptive.license_type=clearkey"
                )

        lines.append(f"#EXTVLCOPT:http-user-agent={USER_AGENT}")
        lines.append(f"#EXTVLCOPT:http-referrer={REFERER}")
        lines.append(f"#EXTVLCOPT:http-extra-headers=Origin: {ORIGIN}")
        lines.append(f"#EXTVLCOPT:http-cookie={cookie}")
        lines.append(
            '#EXTHTTP:{"Origin":"%s","Referer":"%s","User-Agent":"%s","Cookie":"%s"}'
            % (ORIGIN, REFERER, USER_AGENT, cookie)
        )

        # Plain manifest URL (no query params appended)
        lines.append(url)
        lines.append("")
        written += 1

    with open(out_file, "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")

    return written


def main():
    try:
        cookie = COOKIE
        print(f"-> Using hardcoded cookie ({len(cookie)} chars)")

        print("-> Fetching JSON ...")
        data = fetch_json(JSON_URL)
        if isinstance(data, dict):
            data = data.get("items") or data.get("channels") or []
        print(f"   OK ({len(data)} entries)")

        print("-> Writing M3U ...")
        total = generate_m3u(data, cookie, OUTPUT)
        print(f"[OK] {OUTPUT} written ({total} channels)")
    except Exception as e:
        print(f"[FAIL] {e}")


if __name__ == "__main__":
    main()
