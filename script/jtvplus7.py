import os
import json
import base64
import requests
from typing import Dict, List, Set, Any, Optional
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlunparse


CHANNELS_URL = "https://sportlink-jtv.pages.dev/ztv.json"
COOKIE_URL = "https://vk-playlist/cookie.json"
SPORTS_COOKIE_URL = "https://vk-playlist/sportcookie.json"

USER_AGENT = "Virat"
REFERER = "https://www.jiotv.com/"
ORIGIN = "https://www.jiotv.com/"
UPLOAD_TO_GITHUB = True


def to_base64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def get_json(url: str) -> Any:
    cache_buster = f"{'&' if '?' in url else '?'}t={int(datetime.now().timestamp() * 1000)}"
    fresh_url = url + cache_buster
    headers = {"Cache-Control": "no-cache", "Pragma": "no-cache"}
    resp = requests.get(fresh_url, headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json()


def split_url_query(url: str) -> tuple:
    parsed = urlparse(url)
    base = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, "", ""))
    query = parsed.query if parsed.query else None
    return base, query


def get_normal_cookie() -> str:
    try:
        data = get_json(COOKIE_URL)
    except Exception as e:
        print(f"⚠️  Could not fetch normal cookie: {e}")
        return ""

    if isinstance(data, str):
        return data
    if isinstance(data, list):
        for item in data:
            if isinstance(item, dict) and "cookie" in item:
                return item["cookie"]
        return ""
    if isinstance(data, dict):
        return data.get("cookie", "")
    return ""


def get_sports_data() -> Dict[str, Any]:
    try:
        data = get_json(SPORTS_COOKIE_URL)
    except Exception as e:
        print(f"⚠️  Could not fetch sports data: {e}")
        return {"sportsIds": set(), "sportsCookies": {}}

    sports_cookies = {}

    # Handle both list and dict shapes defensively
    if isinstance(data, list):
        results = data
    elif isinstance(data, dict):
        results = data.get("successful_results", []) + data.get("failed_results", [])
    else:
        results = []

    for item in results:
        if not isinstance(item, dict):
            continue
        channel_id = item.get("channel_id")
        if not channel_id:
            continue
        final_url = item.get("final_url") or item.get("error_details", {}).get("final_url", "")
        if not final_url:
            continue
        modified_url = final_url.replace("/output/", "/WDVLive/")
        sports_cookies[str(channel_id)] = modified_url

    return {
        "sportsIds": set(sports_cookies.keys()),
        "sportsCookies": sports_cookies,
    }


def _collect_clearkey_entries(channel: Dict[str, Any]) -> List[tuple]:
    """
    Returns an ordered list of (keyId, key) tuples.
    Handles:
      - single top-level keyId + key
      - keys: [ {keyId, key}, ... ]   (multiple pairs)
      - clearkey: { "kid": "key", ... }
    NOTE: Does NOT deduplicate — duplicates are kept as-is.
    """
    entries: List[tuple] = []

    # 1. Top-level keyId + key
    if channel.get("keyId") and channel.get("key"):
        entries.append((str(channel["keyId"]), str(channel["key"])))

    # 2. keys array (multiple pairs) — keep all entries including duplicates
    keys_arr = channel.get("keys")
    if isinstance(keys_arr, list):
        for k in keys_arr:
            if isinstance(k, dict) and k.get("keyId") and k.get("key"):
                entries.append((str(k["keyId"]), str(k["key"])))

    # 3. clearkey dict fallback
    ck = channel.get("clearkey")
    if isinstance(ck, dict):
        for kid, key in ck.items():
            entries.append((str(kid), str(key)))

    return entries


def create_channel_entry(channel: Dict[str, Any],
                         normal_cookie: str = "",
                         sports_cookies: Dict[str, str] = {}) -> str:
    name = channel.get("name", "")
    logo = channel.get("logo", "")

    raw_group = channel.get("group") or channel.get("category") or "Other"
    group = raw_group

    url = channel.get("url", "")
    channel_id = str(channel.get("id", ""))

    lines = []
    lines.append(
        f'#EXTINF:-1 tvg-id="{channel_id}" tvg-name="{name}" '
        f'tvg-logo="{logo}" group-title="{group}",{name}'
    )

    is_mpd = (channel.get("type") == "dash") or (".mpd" in url.lower())

    if is_mpd:
        lines.append("#KODIPROP:inputstream=inputstream.adaptive")
        lines.append("#KODIPROP:inputstream.adaptive.manifest_type=mpd")

        # Clearkey handling (ALL pairs on a single comma-separated line)
        clearkey_entries = _collect_clearkey_entries(channel)
        if clearkey_entries:
            lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
            pairs = ",".join(f"{kid}:{key}" for kid, key in clearkey_entries)
            lines.append(
                f"#KODIPROP:inputstream.adaptive.license_key={pairs}"
            )
        elif channel.get("license_url"):
            lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
            lines.append(
                f"#KODIPROP:inputstream.adaptive.license_key={channel['license_url']}"
            )

    # Resolve final URL
    sports_url = sports_cookies.get(channel_id)
    if sports_url:
        final_url_with_query = sports_url
    else:
        if normal_cookie:
            sep = "&" if "?" in url else "?"
            final_url_with_query = f"{url}{sep}{normal_cookie}"
        else:
            final_url_with_query = url

    base_url, cookie_query = split_url_query(final_url_with_query)

    # KODIPROP stream_headers
    if cookie_query:
        stream_headers = (
            f"User-Agent={USER_AGENT}"
            f"&Referer={REFERER}"
            f"&Origin={ORIGIN}"
            f"&Cookie={cookie_query}"
        )
        lines.append(
            "#KODIPROP:inputstream.adaptive.stream_headers=" + stream_headers
        )

    # VLC-style options
    lines.append(f"#EXTVLCOPT:http-user-agent={USER_AGENT}")
    lines.append(f"#EXTVLCOPT:http-referrer={REFERER}")
    if cookie_query:
        lines.append(f"#EXTVLCOPT:http-cookie={cookie_query}")

    # EXTHTTP JSON blob
    if cookie_query:
        exthttp = {
            "User-Agent": USER_AGENT,
            "Referer": REFERER,
            "Origin": ORIGIN,
            "Cookie": cookie_query,
        }
        lines.append(f"#EXTHTTP:{json.dumps(exthttp)}")

    lines.append(base_url)
    return "\n".join(lines)


def generate_m3u() -> str:
    try:
        channels = get_json(CHANNELS_URL)
    except Exception as e:
        print(f"❌ Failed to fetch channels: {e}")
        raise

    normal_cookie = get_normal_cookie()
    sports_data = get_sports_data()

    print(f"Channels loaded: {len(channels)}")
    print(f"Sports-specific URLs loaded: {len(sports_data['sportsIds'])}")

    entries = []
    for ch in channels:
        entries.append(create_channel_entry(ch, normal_cookie, sports_data["sportsCookies"]))

    print(f"Channels generated: {len(entries)}")
    return "#EXTM3U\n\n" + "\n\n".join(entries)


def upload_to_github(content: str) -> bool:
    repo_owner = os.environ.get("GITHUB_OWNER")
    repo_name = os.environ.get("GITHUB_REPO")
    token = os.environ.get("GITHUB_TOKEN")

    if not all([repo_owner, repo_name, token]):
        print("⚠️  GitHub credentials missing. Skipping upload.")
        return False
    if not UPLOAD_TO_GITHUB:
        print("⚠️  Upload disabled by UPLOAD_TO_GITHUB flag. Skipping.")
        return False

    path = "jtvplus3.m3u"
    api_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Python-Script",
        "Accept": "application/vnd.github.v3+json",
    }

    existing_resp = requests.get(api_url, headers=headers, timeout=30)
    sha = None
    existing_content = ""
    if existing_resp.status_code == 200:
        existing_json = existing_resp.json()
        sha = existing_json.get("sha")
        if existing_json.get("content"):
            existing_content = base64.b64decode(existing_json["content"]).decode("utf-8")

    def normalize(s: str) -> str:
        return s.strip().replace("\r", "")

    if sha and normalize(existing_content) == normalize(content):
        print("No changes detected. Skipping commit.")
        return True

    payload = {
        "message": f"Auto update playlist {datetime.now().isoformat()}",
        "content": to_base64(content),
        "sha": sha,
    }
    put_resp = requests.put(api_url, headers=headers, json=payload, timeout=30)
    if not put_resp.ok:
        print(f"❌ GitHub upload failed: {put_resp.status_code} - {put_resp.text}")
        return False
    print(f"✅ GitHub upload successful ({put_resp.status_code})")
    return True


def main(output_file: str = "zio.m3u"):
    try:
        m3u = generate_m3u()
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(m3u)
        print(f"📁 Playlist saved locally as '{output_file}'")
        upload_to_github(m3u)
        print("✅ Playlist updated successfully")
    except Exception as e:
        print(f"❌ Error: {e}")
        raise


if __name__ == "__main__":
    main()
