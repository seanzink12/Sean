import os
import re
import time

import requests

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
}

IMAGE_EXT_RE = re.compile(r"\.(jpg|jpeg|png|gif|webp)(?:$|\?)", re.IGNORECASE)
SKIP_DOMAINS = ("bing.com", "microsoft.com", "gstatic.com", "google.com")


def sanitize_folder_name(topic: str) -> str:
    name = re.sub(r"[^\w\-]+", "_", topic.strip().lower())
    return name.strip("_") or "topic"


def fetch_image_urls(query: str, limit: int) -> list:
    """Scrape live image URLs from a Bing Images search results page."""
    resp = requests.get(
        "https://www.bing.com/images/search",
        params={"q": query, "form": "HDRSC2"},
        headers=HEADERS,
        timeout=10,
    )
    resp.raise_for_status()
    html = resp.text

    urls = re.findall(r"murl&quot;:&quot;(https?://[^&]+)&quot;", html)
    if not urls:
        urls = re.findall(r'https?://[^\s"\'<>]+?\.(?:jpg|jpeg|png|webp)', html, re.IGNORECASE)

    seen = set()
    unique_urls = []
    for url in urls:
        if url in seen or any(domain in url for domain in SKIP_DOMAINS):
            continue
        seen.add(url)
        unique_urls.append(url)
        if len(unique_urls) >= limit * 3:
            break
    return unique_urls


def guess_extension(url: str, content_type: str) -> str:
    match = IMAGE_EXT_RE.search(url)
    if match:
        ext = match.group(1).lower()
        return "jpg" if ext == "jpeg" else ext
    if "png" in content_type:
        return "png"
    if "gif" in content_type:
        return "gif"
    if "webp" in content_type:
        return "webp"
    return "jpg"


def download_image(url: str, folder: str, index: int) -> bool:
    """Download one image and write a matching .txt file with its source URL."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=8)
        resp.raise_for_status()
        content_type = resp.headers.get("Content-Type", "")
        if "image" not in content_type and not IMAGE_EXT_RE.search(url):
            return False
        ext = guess_extension(url, content_type)
        with open(os.path.join(folder, f"{index}.{ext}"), "wb") as f:
            f.write(resp.content)
        with open(os.path.join(folder, f"{index}.txt"), "w", encoding="utf-8") as f:
            f.write(url)
        return True
    except requests.RequestException:
        return False


def next_start_index(folder: str) -> int:
    if not os.path.isdir(folder):
        return 1
    existing = [f.split(".")[0] for f in os.listdir(folder) if f.split(".")[0].isdigit()]
    return max((int(n) for n in existing), default=0) + 1


def scrape_topic(query: str, num_images: int, base_dir: str, progress_callback=None):
    """Scrape num_images images for query into base_dir/<topic>/.

    Calls progress_callback(attempted, total_candidates, saved, target) after each
    download attempt. Returns (folder_path, saved_count).
    """
    folder = os.path.join(base_dir, sanitize_folder_name(query))
    os.makedirs(folder, exist_ok=True)

    candidates = fetch_image_urls(query, num_images)
    total_candidates = max(len(candidates), 1)
    start_index = next_start_index(folder)

    saved = 0
    for attempted, url in enumerate(candidates, start=1):
        if saved >= num_images:
            break
        if download_image(url, folder, start_index + saved):
            saved += 1
        if progress_callback:
            progress_callback(attempted, total_candidates, saved, num_images)
        time.sleep(0.15)

    return folder, saved
