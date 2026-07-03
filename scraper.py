import os
import re

import requests
import streamlit as st

PEXELS_SEARCH_URL = "https://api.pexels.com/v1/search"


def sanitize_folder_name(topic: str) -> str:
    name = re.sub(r"[^\w\-]+", "_", topic.strip().lower())
    return name.strip("_") or "topic"


def fetch_image_results(query: str, limit: int) -> list:
    """Search Pexels for query, returning up to `limit` results.

    Each result is a dict with download_url (the actual image), source_page (the
    Pexels photo page, for attribution), and photographer name.
    """
    resp = requests.get(
        PEXELS_SEARCH_URL,
        params={"query": query, "per_page": min(limit, 80)},
        headers={"Authorization": st.secrets["PEXELS_API_KEY"]},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return [
        {
            "download_url": photo["src"]["large"],
            "source_page": photo["url"],
            "photographer": photo.get("photographer", ""),
        }
        for photo in data.get("photos", [])
    ]


def download_image(result: dict, folder: str, index: int) -> bool:
    """Download one image and write a matching .txt file with its Pexels source page."""
    try:
        resp = requests.get(result["download_url"], timeout=8)
        resp.raise_for_status()
        with open(os.path.join(folder, f"{index}.jpg"), "wb") as f:
            f.write(resp.content)
        with open(os.path.join(folder, f"{index}.txt"), "w", encoding="utf-8") as f:
            f.write(result["source_page"])
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

    candidates = fetch_image_results(query, num_images)
    total_candidates = max(len(candidates), 1)
    start_index = next_start_index(folder)

    saved = 0
    for attempted, result in enumerate(candidates, start=1):
        if saved >= num_images:
            break
        if download_image(result, folder, start_index + saved):
            saved += 1
        if progress_callback:
            progress_callback(attempted, total_candidates, saved, num_images)

    return folder, saved
