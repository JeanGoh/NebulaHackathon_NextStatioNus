"""The look: one neon palette, two modes, and the moving trains.

Every colour the app draws with comes from here, so switching mode is one
variable rather than a hunt through the page. The map gets the same tokens, so
the 3-D network and the page around it can never disagree about what dark is.
"""
from __future__ import annotations

# --------------------------------------------------------------- the palette
# Taken off the Nebula X mark: deep space behind, neon running through it.
DARK = {
    "mode": "dark",
    "bg": "#04070e",
    "bg2": "#070d18",
    "panel": "#0b1424",
    "panel2": "#0e1b2e",
    "line": "#1b2b45",
    "ink": "#e9f4ff",
    "muted": "#8098b6",
    "faint": "#4a6182",
    "cyan": "#2ff3d0",
    "blue": "#3d7bff",
    "orange": "#ff7a3d",
    "red": "#ff4d5e",
    "lime": "#c6e84f",
    "violet": "#7c6cff",
    "amber": "#ffb23d",
    "good": "#2ff3a0",
    "action_start": "#087d81",
    "action_end": "#2859c7",
    "action_ink": "#ffffff",
    "glow": "rgba(47,243,208,.35)",
    "shadow": "rgba(0,0,0,.55)",
    "free": "#16243a",
    "hub": "#7c6cff",
    "locked": "#5b7292",
}
LIGHT = {
    "mode": "light",
    "bg": "#eef4fb",
    "bg2": "#e4edf7",
    "panel": "#ffffff",
    "panel2": "#f5f9fd",
    "line": "#cfdcec",
    "ink": "#061020",
    "muted": "#4b5f79",
    "faint": "#8296ae",
    # Neon reads as mud on white, so each hue is taken down to where it still
    # carries but stops vibrating.
    "cyan": "#00937c",
    "blue": "#2154d6",
    "orange": "#d4551b",
    "red": "#d31f33",
    "lime": "#6f8c12",
    "violet": "#5a46e0",
    "amber": "#b7770a",
    "good": "#0a8a55",
    "action_start": "#08777a",
    "action_end": "#2857bd",
    "action_ink": "#ffffff",
    "glow": "rgba(0,147,124,.22)",
    "shadow": "rgba(20,40,70,.16)",
    "free": "#dbe6f3",
    "hub": "#5a46e0",
    "locked": "#5e738d",
}


def tokens(mode: str) -> dict:
    return DARK if str(mode).lower() != "light" else LIGHT


def priority_colours(mode: str) -> dict[int, str]:
    """P1 / P2 / P3, in the mode's neon."""
    t = tokens(mode)
    return {1: t["blue"], 2: t["orange"], 3: t["cyan"]}


# ------------------------------------------------------------------ the CSS
_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&display=swap');

:root {
  --bg: __bg__;  --bg2: __bg2__;  --panel: __panel__;  --panel2: __panel2__;
  --line: __line__;  --ink: __ink__;  --muted: __muted__;  --faint: __faint__;
  --cyan: __cyan__;  --blue: __blue__;  --orange: __orange__;  --red: __red__;
  --lime: __lime__;  --violet: __violet__;  --amber: __amber__; --good: __good__;
  --action-start: __action_start__; --action-end: __action_end__; --action-ink: __action_ink__;
  --glow: __glow__;  --shadow: __shadow__;
}

/* ---------- canvas ---------- */
.stApp { background:
    radial-gradient(1200px 700px at 78% -12%, color-mix(in srgb, var(--blue) 14%, transparent), transparent 62%),
    radial-gradient(900px 600px at 8% 4%, color-mix(in srgb, var(--cyan) 10%, transparent), transparent 60%),
    var(--bg);
  color: var(--ink);
}
[data-testid="stMainBlockContainer"] { padding-top:1.5rem !important; }
.stApp, .stApp p, .stApp li, .stApp span, .stApp label, .stApp div { color: var(--ink); }
.stApp ::selection { background: var(--cyan); color: #03070d; }
.stMarkdown small, .stCaption, [data-testid="stCaptionContainer"],
[data-testid="stCaptionContainer"] p { color: var(--muted) !important; }
[data-testid="stHeader"] { background: transparent !important; }
[data-testid="stToolbar"] button { background: var(--panel) !important; }
::-webkit-scrollbar { width: 10px; height: 10px; }
::-webkit-scrollbar-thumb { background: var(--line); border-radius: 10px; }

/* ---------- type: big words ---------- */
h1, h2, h3, h4, .stApp h1, .stApp h2, .stApp h3, .stApp h4 {
  font-family: 'Space Grotesk', ui-sans-serif, system-ui, sans-serif !important;
  letter-spacing: -.02em; color: var(--ink) !important;
}
h1, .stApp h1 {
  font-size: clamp(2.6rem, 5vw, 4.1rem) !important; font-weight: 700 !important;
  line-height: .98 !important; margin: .1em 0 .05em !important;
  background: linear-gradient(96deg, var(--ink) 34%, var(--cyan) 78%, var(--blue) 100%);
  -webkit-background-clip: text; background-clip: text;
  -webkit-text-fill-color: transparent;
}
.brand-title, .stApp .brand-title {
  margin:-.18em 0 .12em !important; font-family:'Space Grotesk',ui-sans-serif,system-ui,sans-serif;
  font-size:clamp(2.6rem,5vw,4.1rem) !important; font-weight:700; letter-spacing:-.045em;
  line-height:.98; }
.brand-next { position:relative; display:inline-block; color:var(--ink) !important;
  -webkit-text-fill-color:var(--ink) !important; }
/* A route line under NextStatio continues through the N: visually it reads as
   one uninterrupted "NextStatioN", followed directly by the orange US. */
.brand-next:after { content:""; position:absolute; left:.08em; right:-.76em; bottom:-.11em; height:3px;
  border-radius:4px; background:#e2231a; box-shadow:0 0 8px rgba(226,35,26,.42); }
.brand-next:before { content:""; position:absolute; right:-.84em; bottom:-.205em; width:0; height:0;
  border-top:.11em solid transparent; border-bottom:.11em solid transparent; border-left:.18em solid #e2231a;
  filter:drop-shadow(0 0 4px rgba(226,35,26,.38)); }
.brand-station-n, .brand-us { color:#ef7c00 !important; -webkit-text-fill-color:#ef7c00 !important; }
h2, .stApp h2 { font-size: clamp(1.7rem, 2.6vw, 2.3rem) !important; font-weight: 600 !important; }
h3, .stApp h3 { font-size: 1.45rem !important; font-weight: 600 !important; }
h4, .stApp h4 {
  font-size: 1.16rem !important; font-weight: 600 !important;
  text-transform: uppercase; letter-spacing: .10em; color: var(--cyan) !important;
}
.lede { font-size: 1.22rem; line-height: 1.5; color: var(--muted); margin: .2em 0 1.1em; }

/* ---------- panels ---------- */
[data-testid="stSidebar"] {
  background: linear-gradient(180deg, var(--panel) 0%, var(--bg2) 100%);
  border-right: 1px solid var(--line);
  min-width: 360px !important; max-width: 360px !important;
}
[data-testid="stSidebar"] > div:first-child { width:360px !important; }
/* Do not let the desktop-width override reserve blank space after Streamlit
   collapses the sidebar. Its aria state is the source of truth here. */
[data-testid="stSidebar"][aria-expanded="false"] {
  min-width:0 !important; max-width:0 !important; width:0 !important;
  border-right:0 !important;
}
[data-testid="stSidebar"][aria-expanded="false"] > div:first-child {
  width:0 !important; min-width:0 !important;
}
[data-testid="stSidebar"] * { color: var(--ink); }
.stMetric { padding: 14px 16px; background: var(--panel); border: 1px solid var(--line);
            border-radius: 14px; }
[data-testid="stMetricLabel"] { color: var(--muted) !important; }
[data-testid="stMetricValue"] { color: var(--cyan) !important;
  font-family: 'Space Grotesk', sans-serif; font-weight: 700; }
.tile, [data-testid="stExpander"], [data-testid="stExpander"] details,
[data-testid="stExpander"] summary,
div[data-testid="stVerticalBlockBorderWrapper"] > div > div[style*="border"] {
  background: var(--panel) !important; border: 1px solid var(--line) !important;
  border-radius: 14px !important;
}
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary * {
  background: var(--panel) !important; color: var(--ink) !important;
  -webkit-text-fill-color: var(--ink) !important;
}
.tile { padding: 16px 18px; }
.tile .k { font-size: 11px; letter-spacing: .10em; text-transform: uppercase; color: var(--muted); }
.tile .v { font-size: 30px; font-weight: 700; line-height: 1.2;
           font-family: 'Space Grotesk', sans-serif; }
.tile .n { font-size: 12.5px; color: var(--muted); }

/* ---------- simple actions: fewer, bigger, lit ---------- */
.stButton > button, .stDownloadButton > button {
  font-family: 'Space Grotesk', sans-serif !important;
  font-weight: 600 !important; font-size: 1rem !important;
  border-radius: 12px !important; padding: .65rem 1.25rem !important;
  background: var(--panel2) !important; color: var(--ink) !important;
  border: 1px solid var(--line) !important; transition: all .16s ease;
}
.stButton > button:hover, .stDownloadButton > button:hover {
  border-color: var(--cyan) !important; color: var(--cyan) !important;
  box-shadow: 0 0 0 1px var(--cyan), 0 0 22px var(--glow) !important;
  transform: translateY(-1px);
}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"] {
  background: linear-gradient(96deg, var(--action-start), var(--action-end)) !important;
  color: var(--action-ink) !important; border: 0 !important;
  box-shadow: 0 0 26px var(--glow) !important;
}
.stButton > button[kind="primary"] *, .stDownloadButton > button[kind="primary"] *,
.stButton > button[data-testid="stBaseButton-primary"] *,
.stDownloadButton > button[data-testid="stBaseButton-primary"] *,
[data-testid="stFormSubmitButton"] button *,
button[data-testid="stBaseButton-primary"] * {
  color: #ffffff !important; -webkit-text-fill-color: #ffffff !important;
  fill: #ffffff !important;
}
.stButton > button[kind="primary"], .stDownloadButton > button[kind="primary"],
.stButton > button[data-testid="stBaseButton-primary"],
.stDownloadButton > button[data-testid="stBaseButton-primary"],
[data-testid="stFormSubmitButton"] button,
button[data-testid="stBaseButton-primary"] {
  color: #ffffff !important; -webkit-text-fill-color: #ffffff !important;
}
.stButton > button[kind="primary"]:hover, .stDownloadButton > button[kind="primary"]:hover {
  filter: brightness(1.12); color: var(--action-ink) !important; transform: translateY(-1px);
}
/* Streamlit exposes a stable st-key-* class for keyed widgets. Keep this a
   compact, normal-flow navigation rectangle above the wordmark. */
.st-key-back_navigation {
  position:static !important; top:auto; z-index:auto;
  width:max-content !important; padding:0; margin:0 0 4px;
  background:var(--blue); border:1px solid color-mix(in srgb,var(--blue) 72%,var(--cyan));
  border-radius:9px; box-shadow:0 8px 20px var(--shadow);
}
.st-key-back_navigation .stButton > button,
.st-key-back_navigation .stButton > button[kind="primary"] {
  background:transparent !important; border:0 !important; box-shadow:none !important;
  color:#ffffff !important; -webkit-text-fill-color:#ffffff !important;
}
.st-key-back_navigation .stButton > button:hover {
  background:color-mix(in srgb,#ffffff 12%,transparent) !important;
  color:#ffffff !important; box-shadow:none !important; transform:none !important;
}

/* ---------- inputs ---------- */
[data-testid="stTextInput"] input, [data-testid="stNumberInput"] input,
[data-testid="stTextArea"] textarea, [data-testid="stDateInput"] input,
[data-baseweb="select"] > div, [data-testid="stFileUploaderDropzone"] {
  background: var(--panel2) !important; color: var(--ink) !important;
  border: 1px solid var(--line) !important; border-radius: 12px !important;
}
[data-testid="stTextInput"] [data-baseweb="input"] {
  background: var(--panel2) !important; border: 1px solid var(--line) !important;
  border-radius: 12px !important; box-shadow: none !important;
}
[data-testid="stTextInput"] [data-baseweb="input"] input {
  background: transparent !important; color: var(--ink) !important;
  -webkit-text-fill-color: var(--ink) !important; opacity: 1 !important;
}
[data-testid="stTextInput"] input:focus { box-shadow: 0 0 0 1px var(--cyan), 0 0 18px var(--glow) !important; }
[data-testid="stTextInput"] input::placeholder, [data-testid="stTextArea"] textarea::placeholder {
  color: var(--muted) !important; -webkit-text-fill-color: var(--muted) !important;
  opacity: 1 !important; }
/* Streamlit normally fades disabled controls.  The persistent assistant uses
   that state before a plan exists, so retain a clearly visible search field. */
[data-testid="stTextInput"] [data-baseweb="input"]:has(input:disabled) {
  background: var(--panel) !important; border-color: var(--cyan) !important;
  box-shadow: 0 0 14px color-mix(in srgb, var(--cyan) 16%, transparent) !important;
}
[data-testid="stTextInput"] input:disabled,
[data-testid="stTextInput"] input:disabled::placeholder {
  color: var(--muted) !important; -webkit-text-fill-color: var(--muted) !important;
  opacity: 1 !important;
}
/* The app can switch its palette without restarting Streamlit. BaseWeb's
   native controls otherwise keep the startup dark fill in light mode. */
[data-testid="stSelectbox"] [data-baseweb="select"] > div,
[data-testid="stSelectbox"] [data-baseweb="select"] > div > div,
[data-testid="stSelectbox"] [role="combobox"],
[data-testid="stSelectbox"] input {
  background-color: var(--panel2) !important; color: var(--ink) !important;
  -webkit-text-fill-color: var(--ink) !important; border-color: var(--line) !important;
}
[data-testid="stSelectbox"] [data-baseweb="select"] span,
[data-testid="stSelectbox"] [data-baseweb="select"] svg {
  color: var(--ink) !important; fill: var(--ink) !important;
}
[data-testid="stFileUploaderDropzone"] { border: 1.5px dashed color-mix(in srgb, var(--blue) 42%, var(--line)) !important;
  background: linear-gradient(135deg, color-mix(in srgb, var(--cyan) 7%, var(--panel2)),
              var(--panel2)) !important; box-shadow: inset 0 0 22px color-mix(in srgb, var(--cyan) 10%, transparent); }
[data-testid="stFileUploaderDropzone"]:hover { border-color:var(--cyan) !important; }
[data-testid="stFileUploaderDropzone"] button {
  background: linear-gradient(96deg, var(--action-start), var(--action-end)) !important;
  color: var(--action-ink) !important; border: 0 !important; font-weight: 700 !important;
  box-shadow: 0 0 22px var(--glow) !important;
  animation: uploadNudge 2.8s ease-in-out .7s infinite;
}
[data-testid="stFileUploaderDropzone"] button *,
[data-testid="stFileUploaderDropzone"] button span { color: var(--action-ink) !important; }
[data-testid="stFileUploaderDropzone"] svg { color: var(--cyan) !important; fill: var(--cyan) !important; }
[data-testid="stFileUploaderDropzone"] button svg { color:var(--action-ink) !important; fill:var(--action-ink) !important; }
[data-testid="stFileUploaderDropzone"] small { color: var(--muted) !important; }
/* Streamlit renders uploaded files outside the drop-zone element. Theme these
   generated rows separately or they retain their light default background. */
[data-testid="stFileUploaderFile"],
/* Streamlit 1.64 wraps the row in an unlabelled list item/div.  Keep every
   possible row surface dark instead of inheriting its default white card. */
[data-testid="stFileUploader"] ul > li,
[data-testid="stFileUploader"] ul > li > div,
[data-testid="stFileUploader"] [data-testid="stFileUploaderFile"] > div {
  background:var(--panel2) !important;
  border-color:var(--line) !important; border-radius:10px !important; }
/* Some Streamlit builds omit a test id on the upload list. It is always the
   sibling following the drop zone, so theme that otherwise-anonymous branch
   too. This prevents the default white file chips in the dark sidebar. */
[data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"] ~ div,
[data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"] ~ div > *,
[data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"] ~ div > * > div {
  background:var(--panel2) !important; color:var(--ink) !important;
  border-color:var(--line) !important; border-radius:10px !important; }
/* Newer Streamlit builds use anonymous section/div wrappers for selected
   files. Cover those surfaces too: otherwise they retain the dark startup
   theme when the app is switched to light mode. */
[data-testid="stFileUploader"] section,
[data-testid="stFileUploader"] ul,
[data-testid="stFileUploader"] ul > li,
[data-testid="stFileUploader"] ul > li > div,
[data-testid="stFileUploader"] [data-testid="stFileUploaderFile"],
[data-testid="stFileUploader"] [data-testid="stFileUploaderFile"] > div {
  background-color:var(--panel2) !important;
  border-color:var(--line) !important;
}
[data-testid="stFileUploaderFile"] { border:1px solid var(--line) !important; }
[data-testid="stFileUploaderFileName"],
[data-testid="stFileUploaderFile"] [data-testid="stMarkdownContainer"],
[data-testid="stFileUploaderFile"] span,
[data-testid="stFileUploader"] ul > li span { color:var(--ink) !important; }
[data-testid="stFileUploaderFileData"],
[data-testid="stFileUploaderFile"] small,
[data-testid="stFileUploader"] ul > li small { color:var(--muted) !important; }
[data-testid="stFileUploaderFile"] button,
[data-testid="stFileUploader"] ul > li button,
[data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"] ~ div button { background:color-mix(in srgb, var(--cyan) 15%, var(--panel)) !important;
  border:1px solid color-mix(in srgb, var(--cyan) 35%, var(--line)) !important; border-radius:999px !important; }
[data-testid="stFileUploaderFile"] button svg,
[data-testid="stFileUploader"] ul > li button svg,
[data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"] ~ div button svg { color:var(--cyan) !important; fill:var(--cyan) !important; }
/* Streamlit 1.64 can put the selected-file list *inside* the drop zone rather
   than beside it. Its internal card has no stable test-id, so cover the list
   structure directly and keep the selected files inside the dark palette. */
[data-testid="stFileUploaderDropzone"] ul,
[data-testid="stFileUploaderDropzone"] ul > li,
[data-testid="stFileUploaderDropzone"] ul > li > div {
  background:var(--panel2) !important; color:var(--ink) !important;
  border-color:var(--line) !important; border-radius:9px !important; }
[data-testid="stFileUploaderDropzone"] ul *:not(button):not(svg) { color:var(--ink) !important; }
[data-testid="stFileUploaderDropzone"] ul button { background:var(--panel) !important;
  border:1px solid var(--blue) !important; }
/* The filename/data labels carry an inline colour of their own, so the row's
   colour does not reach them. They were pinned to the light ink back when
   Streamlit painted these chips white; the chips follow the palette now, so
   the label has to as well or it goes black on navy. */
[data-testid="stFileUploaderFileName"],
[data-testid="stFileUploaderFileData"],
[data-testid="stFileUploaderDropzone"] [data-testid="stFileUploaderFileName"],
[data-testid="stFileUploaderDropzone"] [data-testid="stFileUploaderFileData"] {
  color:var(--ink) !important; -webkit-text-fill-color:var(--ink) !important;
}
/* In the empty state, the uploader contains only its Upload button and
   instruction block. Selected files are added as a separate direct list
   branch, so scope the dark type to that branch only — never the button or
   the “20MB per file” helper. */
[data-testid="stFileUploaderDropzone"] > ul *,
[data-testid="stFileUploaderDropzone"] > div:not([data-testid="stFileUploaderDropzoneInstructions"]) *,
[data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"] > ul *,
[data-testid="stFileUploader"] [data-testid="stFileUploaderDropzone"] > div:not([data-testid="stFileUploaderDropzoneInstructions"]) * {
  color:var(--ink) !important; -webkit-text-fill-color:var(--ink) !important;
}
[data-testid="stFileUploaderDropzone"] > ul svg,
[data-testid="stFileUploaderDropzone"] > div:not([data-testid="stFileUploaderDropzoneInstructions"]) svg {
  color:var(--cyan) !important; fill:var(--cyan) !important;
}
/* A selected file's remove control should be unmistakable, not a faint dot. */
[data-testid="stFileUploaderFile"] button,
[data-testid="stFileUploaderDropzone"] > ul button,
[data-testid="stFileUploaderDropzone"] > div:not([data-testid="stFileUploaderDropzoneInstructions"]) button {
  background:var(--blue) !important; border:1px solid var(--blue) !important;
  opacity:1 !important;
}
[data-testid="stFileUploaderFile"] button svg,
[data-testid="stFileUploaderDropzone"] > ul button svg,
[data-testid="stFileUploaderDropzone"] > div:not([data-testid="stFileUploaderDropzoneInstructions"]) button svg {
  color:#ffffff !important; fill:#ffffff !important;
}
[data-testid="stFileUploaderDropzone"] > ul button *,
[data-testid="stFileUploaderDropzone"] > div:not([data-testid="stFileUploaderDropzoneInstructions"]) button * {
  color:#ffffff !important; -webkit-text-fill-color:#ffffff !important;
}
/* File rows inherit the native startup theme several levels down. Keep one
   palette surface on the row and make its inner wrappers transparent. */
[data-testid="stFileUploaderFile"],
[data-testid="stFileUploader"] ul > li,
[data-testid="stFileUploaderDropzone"] ul > li {
  background-color:var(--panel2) !important; color:var(--ink) !important;
}
[data-testid="stFileUploaderFile"] *:not(button):not(svg):not(path),
[data-testid="stFileUploader"] ul > li *:not(button):not(svg):not(path),
[data-testid="stFileUploaderDropzone"] ul > li *:not(button):not(svg):not(path) {
  background-color:transparent !important; color:var(--ink) !important;
  -webkit-text-fill-color:var(--ink) !important;
}
@keyframes uploadNudge {
  0%, 66%, 100% { transform:translateY(0); box-shadow:0 0 22px var(--glow); }
  76% { transform:translateY(-4px); box-shadow:0 7px 28px var(--glow); }
  85% { transform:translateY(0); box-shadow:0 1px 18px var(--glow); }
  92% { transform:translateY(-2px); box-shadow:0 5px 23px var(--glow); }
}

/* ---------- tabs ---------- */
[data-baseweb="tab-list"] { gap: 6px; border-bottom: 1px solid var(--line); }
[data-baseweb="tab"] {
  font-family: 'Space Grotesk', sans-serif; font-weight: 600; font-size: 1rem;
  color: var(--muted) !important; background: transparent !important;
}
[data-baseweb="tab"][aria-selected="true"] { color: var(--cyan) !important; }
[data-baseweb="tab-highlight"] { background: var(--cyan) !important; height: 3px; }

/* ---------- tables and alerts ---------- */
[data-testid="stTable"], .stDataFrame, [data-testid="stDataFrame"] {
  border-radius:12px; overflow:hidden; background:var(--panel) !important;
  border:1px solid var(--line) !important; }
[data-testid="stDataFrame"] [role="grid"], [data-testid="stDataFrame"] [role="row"],
[data-testid="stDataFrame"] [role="gridcell"] { background:var(--panel) !important; color:var(--ink) !important; }
[data-testid="stDataFrame"] [role="columnheader"] { background:var(--panel2) !important;
  color:var(--muted) !important; border-color:var(--line) !important; }
[data-testid="stDataFrame"] [role="gridcell"], [data-testid="stDataFrame"] [role="columnheader"] {
  border-color:var(--line) !important; }
/* The dataframe and editor internals are mostly anonymous wrappers. Give the
   wrappers a token surface so light mode cannot leave a dark header or gutter
   behind even though Streamlit booted in dark mode. Canvas pixels themselves
   are handled in css() below. */
[data-testid="stDataFrame"] > div,
[data-testid="stDataFrame"] > div > div,
[data-testid="stDataFrame"] [data-testid="stDataFrameResizable"],
[data-testid="stDataFrame"] [data-testid="stDataFrameGlideDataEditor"] {
  background-color:var(--panel) !important;
  border-color:var(--line) !important;
}
[data-testid="stAlert"] { background:var(--panel2) !important; color:var(--ink) !important;
  border-radius:12px; border:1px solid var(--line); }
[data-testid="stAlert"] *, [data-testid="stAlert"] p { color:var(--ink) !important; }
[data-testid="stCode"], [data-testid="stJson"] { background:var(--panel2) !important;
  border:1px solid var(--line) !important; border-radius:12px !important; }

/* Native Streamlit controls use portals and component-specific defaults, so
   they need their own token bridge in addition to the generic page styling. */
[data-testid="stRadio"] label, [data-testid="stCheckbox"] label,
[data-testid="stToggle"] label, [data-testid="stSlider"] label,
[data-testid="stSelectbox"] label, [data-testid="stDateInput"] label,
[data-testid="stTextArea"] label { color:var(--ink) !important; }
[data-testid="stRadio"] [role="radio"] { border-color:var(--muted) !important; }
[data-testid="stRadio"] [aria-checked="true"] { border-color:var(--cyan) !important; }
[data-testid="stCheckbox"] [data-checked="true"] > div,
[data-testid="stToggle"] [data-checked="true"] { background:var(--cyan) !important; }
/* The sidebar's mode switch needs a persistent edge in deep-space mode. The
   blue ring makes both its off and on states discoverable without turning the
   whole sidebar into another glowing panel. */
[data-testid="stToggle"] [role="switch"],
[data-testid="stToggle"] button[data-checked] {
  border:1.5px solid var(--blue) !important;
  box-shadow:0 0 0 1px color-mix(in srgb,var(--blue) 28%,transparent),
             0 0 10px color-mix(in srgb,var(--blue) 30%,transparent) !important;
}
[data-testid="stToggle"] [role="switch"][aria-checked="false"],
[data-testid="stToggle"] button[data-checked="false"] {
  background:var(--panel2) !important;
}
[data-testid="stToggle"] [role="switch"]:focus-visible,
[data-testid="stToggle"] button[data-checked]:focus-visible {
  outline:2px solid var(--cyan) !important; outline-offset:3px !important;
}
[data-testid="stSlider"] [role="slider"] { background:var(--cyan) !important; box-shadow:0 0 0 3px var(--glow); }
[data-testid="stSlider"] [data-testid="stTickBar"] { color:var(--muted) !important; }
[data-baseweb="select"] > div { color:var(--ink) !important; }
[data-baseweb="popover"], [data-baseweb="menu"], ul[role="listbox"] {
  background:var(--panel) !important; color:var(--ink) !important; border-color:var(--line) !important; }
[role="option"], [role="menuitem"] { color:var(--ink) !important; }
[role="option"]:hover, [role="option"][aria-selected="true"], [role="menuitem"]:hover {
  background:var(--panel2) !important; color:var(--cyan) !important; }
[data-testid="stProgressBar"] > div > div { background:linear-gradient(90deg,var(--cyan),var(--blue)) !important; }
[data-testid="stProgressBar"] > div { background:var(--panel2) !important; }
[data-testid="stSpinner"] > div { border-top-color:var(--cyan) !important; }

/* ---------- launch pad: useful before the eight files arrive ---------- */
.launch-hero { margin: 10px 0 22px; padding: 26px 28px; border:1px solid transparent;
  border-radius:20px; background:linear-gradient(120deg, color-mix(in srgb, var(--blue) 15%, var(--panel)), var(--panel) 56%) padding-box,
  linear-gradient(96deg,var(--cyan),var(--blue)) border-box;
  box-shadow:inset 0 1px 0 color-mix(in srgb, var(--cyan) 36%, transparent), 0 18px 48px var(--shadow); }
.launch-kicker { color:var(--cyan); font-size:11px; font-weight:700; letter-spacing:.16em;
  text-transform:uppercase; }
.launch-title { margin:7px 0; font-family:'Space Grotesk',sans-serif; color:var(--ink);
  font-weight:700; font-size:clamp(1.7rem,3.3vw,2.65rem); line-height:1.04; }
.launch-copy { color:var(--muted); font-size:1.05rem; line-height:1.5; max-width:680px; }
.launch-callout { width:100%; display:flex; align-items:center; justify-content:center; padding:10px 0;
  color:var(--ink); font-family:'Space Grotesk',sans-serif; font-weight:700;
  font-size:clamp(1rem,1.45vw,1.2rem); text-align:center; }
.stApp .launch-callout, .stApp .launch-callout * { color:var(--ink) !important;
  -webkit-text-fill-color:var(--ink) !important; }
.launch-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:18px;
  width:100%; max-width:1050px; margin:18px auto 24px; }
.launch-card { box-sizing:border-box; min-height:100px; padding:16px; border-radius:12px;
  border:1px solid color-mix(in srgb,var(--step-color) 55%,var(--line));
  background:color-mix(in srgb,var(--step-color) 14%,var(--panel));
  box-shadow:0 6px 18px var(--shadow); display:grid;
  place-items:center; text-align:center !important; }
.launch-detect { --step-color:var(--cyan); }
.launch-decide { --step-color:var(--blue); }
.launch-deliver { --step-color:var(--violet); }
.launch-card > * { justify-self:center; align-self:center; }
.launch-card h3 { width:100%; margin:0 !important; padding:0 !important;
  color:var(--ink); font-size:1.1rem !important; line-height:1.35;
  text-align:center !important;
  text-transform:none; letter-spacing:0; }
.launch-result { margin-top:6px; display:flex; gap:8px; flex-wrap:wrap; }
.launch-chip { padding:5px 8px; border:1px solid color-mix(in srgb,var(--cyan) 42%,var(--line));
  border-radius:99px; color:var(--cyan); font-size:11px; font-weight:650; }
@media (max-width: 760px) { .launch-hero { padding:20px; } .launch-grid { grid-template-columns:1fr; } }

/* ---------- the trains ---------- */
.railstrip { position: relative; height: 126px; margin: -8px 0 7px;
             overflow: hidden; border-bottom: 1px solid var(--line); }
.railstrip:before { content:""; position:absolute; inset:0;
  background: linear-gradient(105deg, transparent 0 15%, color-mix(in srgb, var(--blue) 10%, transparent) 36%, transparent 58%),
              repeating-linear-gradient(90deg, transparent 0 52px, color-mix(in srgb, var(--cyan) 14%, transparent) 53px 54px, transparent 55px 106px);
  opacity:.75; pointer-events:none; }
.railstrip .railbrand { position:absolute; left:0; top:8px; z-index:2; display:flex;
  align-items:center; gap:9px; font-family:'Space Grotesk',sans-serif; font-size:11px;
  font-weight:700; letter-spacing:.16em; color:var(--muted); text-transform:uppercase; }
.railstrip .signal { width:8px; height:8px; border-radius:50%; background:var(--cyan);
  box-shadow:0 0 13px var(--cyan); animation:pulse 1.7s ease-in-out infinite; }
.railstrip .railbadge { padding:3px 7px; border:1px solid var(--line); border-radius:99px;
  color:var(--cyan); letter-spacing:.1em; font-size:9px; }
.railstrip .rail { position: absolute; left: 0; right: 0; height: 1px;
                   background: linear-gradient(90deg, transparent,
                     color-mix(in srgb, var(--cyan) 55%, transparent), transparent); }
.railstrip .rail.a { top: 82px; } .railstrip .rail.b { top: 112px; opacity: .45; }
.railstrip .glowline { position: absolute; inset: 0;
  background: radial-gradient(420px 60px at 50% 100%, var(--glow), transparent 70%); }
.railstrip .streak { position:absolute; height:1px; width:32%; z-index:1;
  background:linear-gradient(90deg,transparent,var(--cyan),transparent); opacity:.48;
  animation: streak 4.6s linear infinite; }
.railstrip .streak.a { top:67px; animation-delay:-1.2s; }
.railstrip .streak.b { top:100px; animation-delay:-3.1s; opacity:.25; }
.trn { position: absolute; will-change: transform; filter:drop-shadow(0 0 8px var(--glow)); }
.trn.one { top:27px; animation: glide 16s linear infinite; }
.trn.two { top:61px; animation: glideBack 30s cubic-bezier(.38,0,.62,1) infinite; opacity:.50; }
/* Both reset positions are outside the viewport, so the metro disappears to
   the right and re-enters naturally from the left without a visible jump. */
@keyframes glide { from { transform: translateX(-640px); }
                   to { transform: translateX(calc(100vw + 80px)); } }
@keyframes glideBack { from { transform: translateX(290%) scaleX(-1); }
                       to { transform: translateX(-52%) scaleX(-1); } }
@keyframes streak { from { transform:translateX(-120%); } to { transform:translateX(420%); } }
@keyframes pulse { 0%,100%{opacity:.55;transform:scale(.85)} 50%{opacity:1;transform:scale(1.15)} }
@media (prefers-reduced-motion: reduce) {
  .trn { animation: none !important; left: 8%; }
  .railstrip .signal, .railstrip .streak { animation:none; }
  [data-testid="stFileUploaderDropzone"] button { animation:none !important; }
}
@media (max-width: 700px) { .railstrip { height:102px; } .trn.two { display:none; }
  .railstrip .rail.a { top:84px; } .railstrip .rail.b { top:96px; } }
</style>
"""


def css(mode: str) -> str:
    t = tokens(mode)
    out = _CSS
    for key in ("bg", "bg2", "panel", "panel2", "line", "ink", "muted", "faint",
                "cyan", "blue", "orange", "red", "lime", "violet", "amber",
                "good", "action_start", "action_end", "action_ink", "glow", "shadow"):
        out = out.replace(f"__{key}__", t[key])
    # Streamlit's dataframe cells are painted in a canvas using the startup
    # theme, so ordinary CSS tokens cannot recolour their pixels. The app
    # starts dark by design; reverse only that canvas when the in-app light
    # mode is selected. Other native controls are handled by the token bridge
    # above and do not need this treatment.
    if str(mode).lower() == "light":
        out = out.replace("</style>", """
[data-testid=\"stDataFrame\"] canvas {
  filter: invert(1) hue-rotate(180deg) !important;
}
/* File rows in Streamlit's current uploader have anonymous wrappers that
   retain the dark startup paint. Use the resolved light values here, after all
   generic rules, so every selected-file surface is genuinely light. */
[data-testid="stSidebar"] [data-testid="stFileUploader"] ul,
[data-testid="stSidebar"] [data-testid="stFileUploader"] ul > li,
[data-testid="stSidebar"] [data-testid="stFileUploader"] ul > li > div,
[data-testid="stSidebar"] [data-testid="stFileUploader"] ul > li > div > div,
[data-testid="stSidebar"] [data-testid="stFileUploader"] [data-testid="stFileUploaderFile"],
[data-testid="stSidebar"] [data-testid="stFileUploader"] [data-testid="stFileUploaderFile"] > div {
  background:#f5f9fd !important; border-color:#cfdcec !important;
}
[data-testid="stSidebar"] [data-testid="stFileUploader"] [data-testid="stFileUploaderFileName"],
[data-testid="stSidebar"] [data-testid="stFileUploader"] [data-testid="stFileUploaderFileData"],
[data-testid="stSidebar"] [data-testid="stFileUploader"] ul > li span,
[data-testid="stSidebar"] [data-testid="stFileUploader"] ul > li small {
  color:#061020 !important; -webkit-text-fill-color:#061020 !important;
}
</style>""")
    return out


# ------------------------------------------------- Streamlit's own furniture
# Tables, expanders, inputs and menus are drawn by Streamlit, not by our CSS,
# and st.dataframe paints its cells into a canvas no stylesheet can reach.
# Those follow the [theme] config instead, so the config is built from the same
# tokens -- otherwise a page painted dark sits behind white tables.
_STREAMLIT_KEYS = {
    "primaryColor": "blue",
    "backgroundColor": "bg",
    "secondaryBackgroundColor": "panel",
    "textColor": "ink",
    "borderColor": "line",
    "dataframeBorderColor": "line",
    "dataframeHeaderBackgroundColor": "panel2",
    "linkColor": "cyan",
    "codeBackgroundColor": "panel2",
}


def streamlit_theme(mode: str) -> dict:
    """The [theme] block for one mode, straight off the same palette."""
    t = tokens(mode)
    out = {key: t[token] for key, token in _STREAMLIT_KEYS.items()}
    colours = priority_colours(mode)
    out["chartCategoricalColors"] = [colours[1], colours[2], colours[3],
                                     t["violet"], t["amber"], t["lime"]]
    return out


def _toml_block(values: dict) -> str:
    lines = []
    for key, value in values.items():
        if isinstance(value, list):
            inner = ", ".join('"%s"' % v for v in value)
            lines.append("%s = [%s]" % (key, inner))
        else:
            lines.append('%s = "%s"' % (key, value))
    return "\n".join(lines)


def config_toml(default: str = "dark") -> str:
    """The whole .streamlit/config.toml, generated so it cannot drift.

    Rebuild it with `python -m trackaccess.theme` after changing a token.
    """
    return (
        "# Generated from src/trackaccess/theme.py -- do not hand-edit.\n"
        "# Rebuild with: python -m trackaccess.theme\n\n"
        '[theme]\nbase = "%s"\n%s\n\n' % (default, _toml_block(streamlit_theme(default)))
        + "[theme.dark]\n%s\n\n" % _toml_block(streamlit_theme("dark"))
        + "[theme.light]\n%s\n\n" % _toml_block(streamlit_theme("light"))
        + "[server]\nmaxUploadSize = 20\n"
    )


# ------------------------------------------------------------- moving trains
def _train(body: str, accent: str, window: str, headlight: str) -> str:
    """A compact metro train with lit windows, doors, bogies and a cab.

    It stays code-native SVG so it can adopt the dark/light palette and remain
    sharp on any screen without needing a separate image asset.
    """
    cars = []
    for i in range(5):
        x = i * 92
        cars.append(f'<g transform="translate({x},0)">'
                    f'<rect x="3" y="13" width="87" height="37" rx="12" fill="url(#body)" stroke="{accent}" stroke-width="1.2"/>'
                    f'<path d="M7 42 H87" stroke="{accent}" stroke-width="2" opacity=".75"/>'
                    f'<path d="M47 16 V47" stroke="{accent}" stroke-width="1" opacity=".55"/>')
        for k in range(4):
            cars.append(f'<rect x="{11 + k * 17}" y="21" width="12" height="12" rx="2" fill="{window}" opacity=".92"/>')
        cars.append(f'<rect x="48" y="21" width="11" height="12" rx="2" fill="{window}" opacity=".92"/>'
                    f'<circle cx="24" cy="53" r="5" fill="#03070d" stroke="{accent}" stroke-width="1.5"/>'
                    f'<circle cx="72" cy="53" r="5" fill="#03070d" stroke="{accent}" stroke-width="1.5"/>'
                    '</g>')
    cars.append(f'<g transform="translate(460,0)">'
                f'<path d="M2 50 V18 Q2 7 18 7 H56 Q76 7 91 24 L101 38 Q104 50 90 50 Z" fill="url(#body)" stroke="{accent}" stroke-width="1.4"/>'
                f'<path d="M61 15 Q76 18 90 34 L61 34 Z" fill="{window}" opacity=".96"/>'
                f'<rect x="17" y="20" width="13" height="12" rx="2" fill="{window}"/>'
                f'<rect x="34" y="20" width="13" height="12" rx="2" fill="{window}"/>'
                f'<path d="M8 42 H96" stroke="{accent}" stroke-width="2" opacity=".8"/>'
                f'<circle cx="94" cy="39" r="4" fill="{headlight}"><animate attributeName="opacity" values=".5;1;.5" dur="1.2s" repeatCount="indefinite"/></circle>'
                f'<circle cx="27" cy="53" r="5" fill="#03070d" stroke="{accent}" stroke-width="1.5"/>'
                f'<circle cx="76" cy="53" r="5" fill="#03070d" stroke="{accent}" stroke-width="1.5"/>'
                '</g>')
    return (f'<svg width="570" height="62" viewBox="0 0 570 62" fill="none" '
            f'xmlns="http://www.w3.org/2000/svg"><defs>'
            f'<linearGradient id="body" x1="0" y1="8" x2="0" y2="51" gradientUnits="userSpaceOnUse">'
            f'<stop stop-color="{body}"/><stop offset="1" stop-color="{accent}"/></linearGradient>'
            f'</defs><path d="M0 57 H568" stroke="{accent}" opacity=".45"/>{"".join(cars)}</svg>')


def train_banner(mode: str) -> str:
    """A single illuminated metro running across the launch strip."""
    t = tokens(mode)
    lead = _train(t["cyan"], t["blue"], t["bg"], "#ffffff")
    return (f'<div class="railstrip"><div class="glowline"></div>'
            f'<div class="rail a"></div><div class="rail b"></div>'
            f'<i class="streak a"></i><i class="streak b"></i>'
            f'<div class="trn one">{lead}</div></div>')


def landing(mode: str) -> str:
    """The useful empty state before an operator uploads a programme."""
    return '''<section class="launch-hero">
  <div class="launch-callout">Upload your 8 CSV files in the left panel to begin</div>
</section>
<div class="launch-grid">
  <article class="launch-card launch-detect"><h3>Step 1: Detect</h3></article>
  <article class="launch-card launch-decide"><h3>Step 2: Decide</h3></article>
  <article class="launch-card launch-deliver"><h3>Step 3: Deliver</h3></article>
</div>'''


if __name__ == "__main__":       # python -m trackaccess.theme
    import pathlib
    _out = pathlib.Path(__file__).resolve().parents[2] / ".streamlit" / "config.toml"
    _out.parent.mkdir(exist_ok=True)
    _out.write_text(config_toml())
    print("wrote %s" % _out)
