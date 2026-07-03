import os

import streamlit as st

from scraper import scrape_topic

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "scraped_images")
IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".gif", ".webp")

st.set_page_config(page_title="Interior Design Image Scraper", page_icon="🛋️", layout="wide")

st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');

    html, body, [class*="css"] {
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Text", Inter, system-ui, sans-serif;
    }

    .stApp {
        background-color: #f5f5f7;
    }

    .hero-title {
        font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", Inter, system-ui, sans-serif;
        font-size: 40px;
        font-weight: 600;
        line-height: 1.10;
        color: #1d1d1f;
        margin-bottom: 4px;
    }

    .hero-sub {
        font-size: 17px;
        font-weight: 400;
        line-height: 1.47;
        letter-spacing: -0.374px;
        color: #7a7a7a;
        margin-bottom: 8px;
    }

    .fine-print {
        font-size: 12px;
        color: #7a7a7a;
        margin-bottom: 32px;
    }

    .gallery-title {
        font-size: 21px;
        font-weight: 600;
        letter-spacing: 0.231px;
        color: #1d1d1f;
        margin: 24px 0 12px 0;
    }

    .stButton > button, .stFormSubmitButton > button {
        background-color: #0066cc;
        color: #ffffff;
        border-radius: 9999px;
        border: none;
        padding: 11px 22px;
        font-size: 17px;
        transition: transform 0.1s ease;
    }
    .stButton > button:active, .stFormSubmitButton > button:active {
        transform: scale(0.95);
    }
    .stButton > button:focus, .stFormSubmitButton > button:focus {
        outline: 2px solid #0071e3;
    }

    .stTextInput input, .stNumberInput input {
        border-radius: 9999px;
        border: 1px solid #e0e0e0;
        padding: 12px 20px;
    }

    .stProgress > div > div > div {
        background-color: #0066cc;
    }

    div[data-testid="stImage"] img {
        border-radius: 18px;
    }

    .stTabs [data-baseweb="tab"] {
        font-size: 14px;
        font-weight: 600;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="hero-title">Interior Design Image Scraper</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="hero-sub">Live-search Bing Images for a topic and build a saved, source-linked gallery.</div>',
    unsafe_allow_html=True,
)
st.markdown(
    '<div class="fine-print">Unofficial scraper — results depend on Bing\'s current page markup and may be '
    "rate-limited on heavy use.</div>",
    unsafe_allow_html=True,
)

with st.form("scrape_form"):
    col1, col2 = st.columns([3, 1])
    with col1:
        topic = st.text_input("Search topic", placeholder="e.g. Scandinavian living room")
    with col2:
        num_images = st.number_input("Number of images", min_value=1, max_value=50, value=10, step=1)
    submitted = st.form_submit_button("Scrape Images")

if submitted:
    if not topic.strip():
        st.warning("Enter a search topic first.")
    else:
        progress_bar = st.progress(0.0)
        status_text = st.empty()

        def on_progress(attempted, total_candidates, saved, target):
            progress_bar.progress(attempted / total_candidates)
            status_text.markdown(f"Saved **{saved}/{target}** images — checked {attempted}/{total_candidates} candidates")

        with st.spinner(f"Scraping images for “{topic}”..."):
            folder, saved = scrape_topic(topic, int(num_images), BASE_DIR, progress_callback=on_progress)

        progress_bar.progress(1.0)
        if saved == 0:
            st.error("No images could be downloaded. Bing may be rate-limiting requests — try again shortly.")
        else:
            st.success(f"Saved {saved} image(s) to {folder}")

st.markdown("---")
st.markdown('<div class="gallery-title">Gallery</div>', unsafe_allow_html=True)

topics = []
if os.path.isdir(BASE_DIR):
    topics = sorted(d for d in os.listdir(BASE_DIR) if os.path.isdir(os.path.join(BASE_DIR, d)))

if not topics:
    st.info("No images scraped yet. Run a search above to populate the gallery.")
else:
    tabs = st.tabs(topics)
    for tab, topic_name in zip(tabs, topics):
        with tab:
            folder = os.path.join(BASE_DIR, topic_name)
            image_files = sorted(f for f in os.listdir(folder) if f.lower().endswith(IMAGE_EXTENSIONS))
            if not image_files:
                st.write("No images in this topic yet.")
                continue
            cols = st.columns(4)
            for i, filename in enumerate(image_files):
                img_path = os.path.join(folder, filename)
                txt_path = os.path.join(folder, os.path.splitext(filename)[0] + ".txt")
                source_url = ""
                if os.path.exists(txt_path):
                    with open(txt_path, "r", encoding="utf-8") as f:
                        source_url = f.read().strip()
                with cols[i % 4]:
                    st.image(img_path, use_container_width=True)
                    if source_url:
                        st.caption(f"[Source]({source_url})")
