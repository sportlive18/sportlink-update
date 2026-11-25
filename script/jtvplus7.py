import os
import json
import base64
import re
import requests
from typing import Dict, List, Set, Any, Optional
from datetime import datetime
from urllib.parse import urlparse, parse_qs, urlunparse


CHANNELS_URL = "https://sportlink-jtv.pages.dev/ztv.json"
COOKIE_URL = "https://sportlink-tv11.pages.dev/cookie.json"
SPORTS_COOKIE_URL = "https://sportlink-tv11.pages.dev/cookie2.json"

USER_AGENT = "Virat"
REFERER = "https://www.jiotv.com/"
ORIGIN = "https://www.jiotv.com/"
UPLOAD_TO_GITHUB = True

HEADER_LINE = (
    '#EXTM3U url-tvg="https://avkb.short.gy/jioepg.xml.gz" '
    'tvg-url="https://avkb.short.gy/jioepg.xml.gz" refresh="3600"'
)


def to_base64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def _try_repair_json(text: str) -> str:
    text = re.sub(r'}(\s*){', r'},\2{', text)
    text = re.sub(r'](\s*){', r'],\2{', text)
    text = re.sub(r'}(\s*)"', r'},\2"', text)
    text = re.sub(r',(\s*[}\]])', r'\1', text)
    return text


def get_json(url: str, repair: bool = True) -> Any:
    if not url:
        return None
    cache_buster = f"{'&' if '?' in url else '?'}t={int(datetime.now().timestamp() * 1000)}"
    fresh_url = url + cache_buster
    headers = {"Cache-Control": "no-cache", "Pragma": "no-cache"}
    resp = requests.get(fresh_url, headers=headers, timeout=30)
    resp.raise_for_status()

    text = resp.text

    cl = resp.headers.get("Content-Length")
    if cl is not None:
        try:
            expected = int(cl)
            if expected != len(resp.content):
                print(
                    f"⚠️  Truncated response for {url}: "
                    f"expected {expected} bytes, got {len(resp.content)}"
                )
        except ValueError:
            pass

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        print(f"⚠️  JSON parse failed for {url}: {e}")
        pos = getattr(e, "pos", 0) or 0
        print("---- raw around error ----")
        print(text[max(0, pos - 300):pos + 300])
        print("--------------------------")
        if not repair:
            raise

        repaired = _try_repair_json(text)
        try:
            data = json.loads(repaired)
            print("✅ JSON repaired successfully.")
            return data
        except json.JSONDecodeError as e2:
            print(f"❌ Repair failed: {e2}")
            raise


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
        # Old format: {"cookie": "__hdnea__=..."}
        if "cookie" in data:
            return data["cookie"]
        # New format: {"__hdnea__": "__hdnea__=st=...~exp=...~acl=...~hmac=..."}
        for val in data.values():
            if isinstance(val, str) and val.startswith("__hdnea__"):
                return val
        return ""

    return ""


# ---------------------------------------------------------------------------
# cookie2.json is a dict keyed by channel name, value is the __hdnea__ token.
# We need to map it to channel_id using the channel list fetched separately.
# Strategy: build a name→token lookup, then match against channel names.
# ---------------------------------------------------------------------------

def _normalize_name(name: str) -> str:
    """Lowercase, replace non-alphanumeric runs with a single space, strip."""
    return re.sub(r'[^a-z0-9]+', ' ', name.lower()).strip()


def get_sports_data(channels: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Fetches cookie2.json and maps its per-channel tokens to channel IDs.

    cookie2.json can be in two shapes:
      A) Old shape — list of result dicts with channel_id + final_url/error_details.
      B) New shape — plain dict keyed by channel name, value is the __hdnea__ token string.
    """
    if not SPORTS_COOKIE_URL:
        return {"sportsIds": set(), "sportsCookies": {}}

    try:
        data = get_json(SPORTS_COOKIE_URL)
    except Exception as e:
        print(f"⚠️  Could not fetch sports data: {e}")
        return {"sportsIds": set(), "sportsCookies": {}}

    sports_cookies: Dict[str, str] = {}

    # --- Shape A: list (old format) or dict with successful_results/failed_results ---
    if isinstance(data, list):
        results = data
        _parse_results_list(results, sports_cookies)

    elif isinstance(data, dict):
        # Check if it looks like shape A (has result-list keys)
        if "successful_results" in data or "failed_results" in data:
            results = data.get("successful_results", []) + data.get("failed_results", [])
            _parse_results_list(results, sports_cookies)

        else:
            # Shape B: {"Channel_Name": "__hdnea__=st=...~exp=..."}
            # Build a lookup from channel_id to token using the channel list
            _parse_name_token_dict(data, channels, sports_cookies)

    print(f"Sports-specific cookies loaded: {len(sports_cookies)}")
    return {
        "sportsIds": set(sports_cookies.keys()),
        "sportsCookies": sports_cookies,
    }


def _parse_results_list(results: list, out: Dict[str, str]) -> None:
    """Shape A parser — populates out dict with channel_id → full URL."""
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
        out[str(channel_id)] = modified_url


def _build_url_from_token(channel_url: str, token: str) -> str:
    """
    Given a channel's base .mpd URL and a __hdnea__ token string, return
    the full URL with the token appended as a query parameter.
    e.g.  https://.../index.mpd  +  __hdnea__=st=...  →  https://.../index.mpd?__hdnea__=st=...
    """
    sep = "&" if "?" in channel_url else "?"
    return f"{channel_url}{sep}{token}"


def _parse_name_token_dict(
    data: Dict[str, str],
    channels: List[Dict[str, Any]],
    out: Dict[str, str],
) -> None:
    """
    Shape B parser.
    data  = {"Star_Sports_1_HD": "__hdnea__=st=...", ...}
    Match each key to a channel by normalised name, then build the full URL.
    """
    # Build normalised-name → (channel_id, channel_url) map
    name_to_channel: Dict[str, tuple] = {}
    for ch in channels:
        ch_id = str(ch.get("id", ""))
        ch_name = ch.get("name", "")
        ch_url = ch.get("url", "")
        if ch_id and ch_name:
            norm = _normalize_name(ch_name)
            name_to_channel[norm] = (ch_id, ch_url)

    unmatched = []
    for key, token in data.items():
        if not isinstance(token, str) or not token.startswith("__hdnea__"):
            continue

        norm_key = _normalize_name(key)
        match = name_to_channel.get(norm_key)

        if match:
            ch_id, ch_url = match
            out[ch_id] = _build_url_from_token(ch_url, token)
        else:
            # Try partial / fuzzy match: key words all present in channel name
            key_words = set(norm_key.split())
            best = None
            for norm_ch, (ch_id, ch_url) in name_to_channel.items():
                ch_words = set(norm_ch.split())
                if key_words and key_words.issubset(ch_words):
                    best = (ch_id, ch_url)
                    break
            if best:
                out[best[0]] = _build_url_from_token(best[1], token)
            else:
                unmatched.append(key)

    if unmatched:
        print(f"⚠️  {len(unmatched)} cookie2 keys had no channel match: {unmatched[:10]}")


def _collect_clearkey_entries(channel: Dict[str, Any]) -> List[tuple]:
    entries: List[tuple] = []

    if channel.get("keyId") and channel.get("key"):
        entries.append((str(channel["keyId"]), str(channel["key"])))

    keys_arr = channel.get("keys")
    if isinstance(keys_arr, list):
        for k in keys_arr:
            if isinstance(k, dict) and k.get("keyId") and k.get("key"):
                entries.append((str(k["keyId"]), str(k["key"])))

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
    group = channel.get("group") or channel.get("category") or "Other"
    url = channel.get("url", "")
    channel_id = str(channel.get("id", ""))

    lines = []
    lines.append(
        f'#EXTINF:-1 tvg-id="{channel_id}" tvg-name="{name}" '
        f'tvg-logo="{logo}" group-title="{group}", {name}'
    )

    is_mpd = (channel.get("type") == "dash") or (".mpd" in url.lower())

    if is_mpd:
        lines.append("#KODIPROP:inputstream.adaptive.manifest_type=mpd")

        clearkey_entries = _collect_clearkey_entries(channel)
        if clearkey_entries:
            lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
            pairs = ",".join(f"{kid}:{key}" for kid, key in clearkey_entries)
            lines.append(f"#KODIPROP:inputstream.adaptive.license_key={pairs}")
        elif channel.get("license_url"):
            lines.append("#KODIPROP:inputstream.adaptive.license_type=clearkey")
            lines.append(
                f"#KODIPROP:inputstream.adaptive.license_key={channel['license_url']}"
            )

    # Resolve final URL: sports override → normal cookie → plain url
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

    lines.append(f"#EXTVLCOPT:http-user-agent={USER_AGENT}")

    if cookie_query:
        exthttp = {"cookie": cookie_query}
        lines.append("#EXTHTTP:" + json.dumps(exthttp, separators=(",", ":")))

    lines.append(base_url)
    return "\n".join(lines)


def generate_m3u() -> str:
    try:
        channels = get_json(CHANNELS_URL)
    except Exception as e:
        print(f"❌ Failed to fetch channels: {e}")
        raise

    if not isinstance(channels, list):
        raise ValueError(f"Expected list of channels, got {type(channels).__name__}")

    normal_cookie = get_normal_cookie()
    print(f"Normal cookie loaded: {'yes' if normal_cookie else 'NO - missing!'}")

    # Pass channels to get_sports_data so it can do name→id matching (shape B)
    sports_data = get_sports_data(channels)

    print(f"Channels loaded: {len(channels)}")
    print(f"Sports-specific URLs loaded: {len(sports_data['sportsIds'])}")

    entries = []
    for ch in channels:
        if not isinstance(ch, dict):
            print(f"⚠️  Skipping non-dict channel entry: {type(ch).__name__}")
            continue
        entries.append(create_channel_entry(ch, normal_cookie, sports_data["sportsCookies"]))

    print(f"Channels generated: {len(entries)}")
    return HEADER_LINE + "\n\n" + "\n\n".join(entries)


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
