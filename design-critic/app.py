import os

import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import types
from PIL import Image, ImageDraw
from pydantic import BaseModel, ValidationError

# Tried in order; if the primary model's free-tier quota is exhausted (429),
# we fall back to the lighter model, which has its own separate quota pool.
CRITIQUE_MODELS = ["gemini-flash-latest", "gemini-flash-lite-latest"]

PRINCIPLES = [
    (
        "Visual Hierarchy",
        "Is there one clear focal point that draws the eye first, achieved through "
        "size, weight, color, or isolation from surrounding elements?",
    ),
    (
        "Hick's Law",
        "Does the viewer face too many competing options (overwhelming), or is "
        "there no single clear message/action at all (unfocused)?",
    ),
    (
        "Gestalt Grouping",
        "Are related elements visually grouped (via proximity, shared background, "
        "or borders), and unrelated elements clearly separated?",
    ),
    (
        "Cognitive Load",
        "Is there enough white space/negative space, or does the layout feel dense "
        "and crowded regardless of hierarchy?",
    ),
    (
        "Color Contrast",
        "Is text legible against its background (sufficient contrast), and is "
        "meaning conveyed by more than color alone?",
    ),
    (
        "Jakob's Law",
        "Does the layout follow conventions users already expect from other "
        "websites/posters/ads (e.g. nav placement, logo behavior, familiar CTA "
        "styling), or does it break familiar patterns in ways that add friction?",
    ),
]


# All fields are always present (rather than Optional) because Gemini's
# structured-output schema doesn't handle Optional/Union cleanly; the prompt
# tells the model to leave the non-applicable side (violation+suggestion, or
# reason_it_works) as an empty string, and region as an empty list, instead.
class PrincipleResult(BaseModel):
    principle: str
    violated: bool
    severity: str
    violation: str
    suggestion: str
    reason_it_works: str
    region: list[int]


class CritiqueResult(BaseModel):
    results: list[PrincipleResult]


def get_gemini_client() -> genai.Client | None:
    api_key = st.secrets.get("GEMINI_API_KEY", os.environ.get("GEMINI_API_KEY", ""))
    if not api_key:
        return None
    return genai.Client(api_key=api_key)


def build_rubric_text() -> str:
    lines = [f"- {name}: {desc}" for name, desc in PRINCIPLES]
    return "\n".join(lines)


def analyze_image(client: genai.Client, image: Image.Image) -> CritiqueResult:
    prompt = f"""You are critiquing a screenshot of a website homepage, poster, or
advertisement using these design/psychology principles:

{build_rubric_text()}

If the image is not a designed layout at all — e.g. a plain photo, a selfie,
a screenshot of code or plain text, or anything with no intentional visual
design to critique — return an empty "results" list rather than forcing any
of the principles onto it.

Otherwise, first determine which of the 6 principles actually apply — e.g.
Jakob's Law (navigation/CTA conventions) doesn't apply if the image has no
navigation or interactive elements at all. Skip irrelevant principles
entirely; do not include them in your results.

For each principle that IS relevant, evaluate it and include one result. Only
mark "violated" true if the principle is SIGNIFICANTLY violated in this
specific image — not for minor/marginal issues.

For each principle:
- If violated: set "violated" to true. Fill "violation" — name the specific
element(s) involved and describe exactly what about them violates the
principle, being concrete about what you observe, not just the principle
name. Fill "suggestion" — explain the direction the design should move in and
why, grounded in the principle (e.g. "reduce the number of equally-weighted
buttons so one action is unambiguous" or "increase the contrast between this
text and its background so it doesn't blend in"). Do not prescribe exact hex
codes, pixel values, or a specific implementation — the goal is to teach the
underlying design reasoning, not to hand them a spec to copy. Leave
"reason_it_works" as an empty string.
  Set "severity" to exactly "major" or "minor": "major" if the violation
substantially undermines the design's core communication or usability (a
first-time viewer would struggle or be misled), "minor" if it adds noticeable
friction but the design still works.
  Additionally, IF AND ONLY IF the violation is anchored to one specific
visual area that would genuinely help the user to see circled (e.g. a cluster
of competing buttons, one low-contrast text block, a misgrouped set of
elements), fill "region" with that area's bounding box as [ymin, xmin, ymax,
xmax], each value normalized to a 0-1000 scale of the image dimensions.
If the violation is about the overall layout with no single locus (e.g. a
page-wide lack of white space or a general absence of hierarchy), leave
"region" as an empty list — do not force a box that circles most of the
image.
- If not violated: set "violated" to false. Leave "violation", "suggestion",
and "severity" as empty strings and "region" as an empty list. Fill
"reason_it_works" with
ONE direct sentence stating what the design does right for this principle —
no filler, no praise words like "effectively" or "nicely", just the concrete
fact (e.g. "Dark text on a white background keeps all copy legible.")."""

    for i, model in enumerate(CRITIQUE_MODELS):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[prompt, image],
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=CritiqueResult,
                ),
            )
            return CritiqueResult.model_validate_json(response.text)
        except genai.errors.ClientError as e:
            # Quota exhausted (429): fall through to the next model, which
            # has its own separate free-tier quota pool.
            is_last = i == len(CRITIQUE_MODELS) - 1
            if e.code != 429 or is_last:
                raise
        except genai.errors.ServerError:
            # Transient Google-side failure (e.g. 503 "high demand") — the
            # other model is usually unaffected, so try it too.
            if i == len(CRITIQUE_MODELS) - 1:
                raise
        except ValidationError:
            # Model returned JSON that doesn't match our schema — rare, but
            # happens occasionally with any structured-output call. Retry on
            # the other model rather than crashing.
            if i == len(CRITIQUE_MODELS) - 1:
                raise
    raise AssertionError("unreachable")


def prepare_image(image: Image.Image, max_dim: int = 1600) -> Image.Image:
    # Caps both the API payload (slow/unreliable on large phone screenshots)
    # and the fullscreen dialog size — 1600px is already sharper than any
    # screen will render it at.
    if max(image.size) <= max_dim:
        return image
    resized = image.copy()
    resized.thumbnail((max_dim, max_dim), Image.LANCZOS)
    return resized


def has_usable_region(r: PrincipleResult) -> bool:
    return (
        len(r.region) == 4
        and r.region[0] < r.region[2]
        and r.region[1] < r.region[3]
    )


def draw_annotation(image: Image.Image, region: list[int]) -> Image.Image:
    # Region comes back as [ymin, xmin, ymax, xmax] on a 0-1000 scale.
    w, h = image.size
    ymin, xmin, ymax, xmax = region
    x0 = max(0, xmin / 1000 * w)
    y0 = max(0, ymin / 1000 * h)
    x1 = min(w, xmax / 1000 * w)
    y1 = min(h, ymax / 1000 * h)

    # Pad the ellipse outward so the stroke rings the region instead of
    # cutting through its corners.
    pad_x = (x1 - x0) * 0.1 + w * 0.01
    pad_y = (y1 - y0) * 0.1 + h * 0.01

    annotated = image.copy()
    draw = ImageDraw.Draw(annotated)
    draw.ellipse(
        [x0 - pad_x, y0 - pad_y, x1 + pad_x, y1 + pad_y],
        outline="#e02020",
        width=max(3, w // 250),
    )
    return annotated


st.set_page_config(page_title="Design Audit", layout="wide")

st.markdown(
    """
    <style>
    [data-testid="stMain"] .block-container {
        max-width: 700px;
        margin: 0 auto;
        padding-top: 4rem;
    }
    /* background-color and box-shadow are !important and unconditional
    (not tied to a drag-active class) because Streamlit re-renders this
    element's className on every drag event, which would wipe out any class
    we toggle via JS — a permanent override is the reliable way to prevent
    its jarring dark+red drag-over style. */
    [data-testid="stFileUploaderDropzone"] {
        min-height: 220px;
        border: 2px dashed #8a8a8a;
        border-radius: 12px;
        background-color: #fafafa !important;
        box-shadow: none !important;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 10px;
    }
    [data-testid="stFileUploaderDropzone"]::before {
        content: "Drag and drop image here, or browse";
        font-size: 15px;
        color: #444;
    }
    [data-testid="stFileUploaderDropzoneInstructions"] span {
        color: #444 !important;
    }
    [data-testid="stFileUploaderDropzoneInstructions"] {
        flex-grow: 0 !important;
    }
    [data-testid="stFileUploaderDropzone"] [data-testid="stBaseButton-borderlessIcon"] {
        display: none;
    }
    /* Mirror the expander header's hover (a rgba(172,177,195,0.15) wash
    fading in) by layering the same wash over the button's solid dark base —
    the base must stay opaque or the button washes out against the light
    dropzone behind it. */
    [data-testid="stFileUploaderDropzone"] button {
        transition: background-image 0.15s ease;
    }
    [data-testid="stFileUploaderDropzone"] button:hover {
        background-color: #131720 !important;
        background-image: linear-gradient(rgba(172, 177, 195, 0.15), rgba(172, 177, 195, 0.15)) !important;
        color: #fff !important;
        border-color: rgba(250, 250, 250, 0.2) !important;
    }
    /* Streamlit renders a separate dark overlay div with red text over the
    dropzone while a file is being dragged over it; neutralize it the same
    way (it has no stable class, so exclude the one stable sibling by
    data-testid instead). */
    [data-testid="stFileUploaderDropzone"] > div:not([data-testid="stFileUploaderDropzoneInstructions"]) {
        background-color: #eef2f7 !important;
    }
    [data-testid="stFileUploaderDropzone"] > div:not([data-testid="stFileUploaderDropzoneInstructions"]) span {
        color: #3a5a8a !important;
    }
    [data-testid="stCaptionContainer"] {
        opacity: 0.85 !important;
    }
    .st-key-hidden_view_button, .st-key-hidden_view_original {
        display: none;
    }
    /* The findings thumbnail opens the full-quality dialog on click (script
    below), so hide its hover toolbar (fullscreen button) and show a
    pointer cursor instead. */
    .st-key-findings_thumb [data-testid="stElementToolbar"] {
        display: none;
    }
    .st-key-findings_thumb img {
        cursor: pointer;
    }
    /* Cap dialog images to the viewport so the whole image is visible
    without scrolling the dialog. */
    [data-testid="stDialog"] img {
        max-height: 65vh;
        width: auto;
        max-width: 100%;
        object-fit: contain;
    }
    /* The image's element container shrinks to the rendered image width and
    left-aligns inside the dialog's column — center the column's children
    instead (centering the img itself does nothing, it fills its own
    container). */
    [data-testid="stDialog"] [data-testid="stVerticalBlock"] {
        align-items: center;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

st.title("Design Audit", anchor=False)
st.caption(
    "Upload a homepage, poster, or ad screenshot. The AI checks it against 6 "
    "design/psychology principles, offering suggestions when they are violated."
)

gemini_client = get_gemini_client()
if gemini_client is None:
    st.error(
        "No Gemini API key found. Add GEMINI_API_KEY to "
        ".streamlit/secrets.toml (or set it as an environment variable) and restart."
    )
    st.stop()

@st.dialog("Uploaded Image")
def show_image_dialog(image: Image.Image) -> None:
    st.image(image)


# Slightly larger variant used by the Findings section (thumbnail and View
# on image); the upload-chip preview keeps the small one.
@st.dialog("Uploaded Image", width="medium")
def show_image_dialog_large(image: Image.Image) -> None:
    st.image(image)


uploaded = st.file_uploader("Upload a screenshot", type=["png", "jpg", "jpeg", "webp"])

with st.expander("What do we check?"):
    for name, desc in PRINCIPLES:
        st.markdown(f"**{name}** — {desc}")

# Runs unconditionally (not just after upload) so the calmer drag-over style
# is bound as soon as the empty dropzone is rendered.
components.html(
    """
    <script>
    setInterval(function () {
        const doc = window.parent.document;
        const chip = doc.querySelector('[data-testid="stFileChip"]');
        const viewBtn = [...doc.querySelectorAll('button')]
            .find(b => b.textContent.includes('View Image'));
        if (chip && viewBtn && !chip.dataset.clickBound) {
            chip.style.cursor = 'pointer';
            chip.addEventListener('click', function (e) {
                if (e.target.closest('[data-testid="stFileChipDeleteBtn"]')) {
                    return;
                }
                e.stopPropagation();
                e.preventDefault();
                viewBtn.click();
            });
            chip.dataset.clickBound = 'true';
        }

        const thumb = doc.querySelector('.st-key-findings_thumb img');
        const viewOrigBtn = [...doc.querySelectorAll('button')]
            .find(b => b.textContent.includes('View Original'));
        if (thumb && viewOrigBtn && !thumb.dataset.clickBound) {
            thumb.addEventListener('click', function (e) {
                e.stopPropagation();
                e.preventDefault();
                viewOrigBtn.click();
            });
            thumb.dataset.clickBound = 'true';
        }
    }, 500);
    </script>
    """,
    height=0,
)

if uploaded:
    image = prepare_image(Image.open(uploaded).convert("RGB"))

    if st.session_state.get("uploaded_file_id") != uploaded.file_id:
        st.session_state.uploaded_file_id = uploaded.file_id
        st.session_state.pop("result", None)
        st.session_state.pop("analyzed_image", None)

    if st.button("Analyze Design", type="primary"):
        with st.spinner("Analyzing against design principles..."):
            try:
                st.session_state.result = analyze_image(gemini_client, image)
                st.session_state.analyzed_image = image
            except genai.errors.ServerError:
                st.error(
                    "Gemini is experiencing high demand right now — this is "
                    "temporary on Google's side. Click Analyze Design again "
                    "in a moment."
                )
            except genai.errors.ClientError as e:
                if e.code == 429:
                    st.error(
                        "Gemini's free-tier daily quota is used up for now. "
                        "It resets on a rolling daily basis — try again later."
                    )
                else:
                    st.error(f"Gemini API error: {e}")
            except ValidationError:
                st.error(
                    "Got an unexpected response from Gemini — this happens "
                    "occasionally. Click Analyze Design again."
                )

    # Hidden (not removed) because the click-forwarding script below needs a
    # real Streamlit button to trigger — Streamlit exposes no click hook on
    # the file-chip icon itself, so we forward icon clicks to this button.
    with st.container(key="hidden_view_button"):
        if st.button("View Image"):
            show_image_dialog(image)

if "result" in st.session_state:
    result = st.session_state.result
    analyzed = st.session_state.get("analyzed_image")
    st.subheader("Findings", anchor=False)
    if analyzed is not None:
        # Same (prepared) image the fullscreen dialog shows, just displayed
        # small — the browser does the downscaling.
        with st.container(key="findings_thumb"):
            st.image(analyzed, width=260)
        # Hidden click target for the thumbnail (same forwarding pattern as
        # the file-chip's View Image button).
        with st.container(key="hidden_view_original"):
            if st.button("View Original"):
                show_image_dialog_large(analyzed)

    if not result.results:
        st.info(
            "This doesn't look like a homepage, poster, or ad — try "
            "uploading a screenshot with an actual design/layout to critique."
        )
        st.stop()

    violations = [r for r in result.results if r.violated]
    passes = [r for r in result.results if not r.violated]

    total = len(result.results)
    majors = sum(1 for r in violations if r.severity == "major")
    scoreline = f"**{len(passes)} of {total}** relevant principles upheld"
    if majors:
        scoreline += f" · {majors} major violation{'s' if majors > 1 else ''}"
    st.markdown(scoreline)

    for r in passes:
        with st.container(border=True):
            st.markdown(f"✅ **{r.principle}** — {r.reason_it_works}")

    # Major violations listed before minor ones. Major is the implied
    # default, so severity is only called out on minor findings.
    for r in sorted(violations, key=lambda r: r.severity != "major"):
        with st.expander(f"⚠️ {r.principle}"):
            if r.severity == "minor":
                st.caption("Minor severity")
            st.markdown(f"**Violation:** {r.violation}")
            st.markdown(f"**Suggestion:** {r.suggestion}")
            if analyzed is not None and has_usable_region(r):
                if st.button("View on image", key=f"annot_{r.principle}"):
                    show_image_dialog_large(draw_annotation(analyzed, r.region))
