"""Gemini-powered helpers: extract deadlines from syllabus PDF."""
import asyncio
import json
import os
import re
import uuid
from datetime import datetime

from pypdf import PdfReader

try:
    from google import genai
    from google.genai import types
    _GENAI_AVAILABLE = True
except ImportError:
    genai = None
    types = None
    _GENAI_AVAILABLE = False

# Accept both key names for flexibility
GEMINI_API_KEY = (
    os.environ.get("GEMINI_API_KEY")
    or os.environ.get("EMERGENT_LLM_KEY")
)
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")

_SYSTEM_EXTRACT = (
    "You are an academic scheduling assistant. Extract every deadline, exam, "
    "quiz, project, and reading deadline from the supplied syllabus text. "
    "Return ONLY valid JSON (no markdown, no commentary) with this schema: "
    "{\"course\": {\"code\": str, \"title\": str, \"term\": str|null, \"instructor\": str|null}, "
    "\"events\": [ {\"title\": str, \"type\": one of "
    "[\"assignment\",\"quiz\",\"midterm\",\"final\",\"project\",\"reading\",\"other\"], "
    "\"dueDateISO\": str (YYYY-MM-DD), \"notes\": str|null } ] } "
    "If the year is missing in the syllabus, infer the most likely upcoming year. "
    "Sort events ascending by dueDateISO."
)


def _extract_pdf_text(pdf_path: str) -> str:
    reader = PdfReader(pdf_path)
    pages = []
    for page in reader.pages:
        text = page.extract_text() or ""
        pages.append(text)
    return "\n".join(pages)


def _parse_json(raw: str) -> dict:
    s = (raw or "").strip()
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", s, re.DOTALL)
    if m:
        s = m.group(1).strip()
    if not s.startswith("{"):
        left = s.find("{")
        right = s.rfind("}")
        if left != -1 and right != -1:
            s = s[left: right + 1]
    return json.loads(s)


# ── Regex fallback ────────────────────────────────────────────────────────────
_DATE_PATTERNS = [
    # Jan 15, 2025 / January 15 2025
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+\d{1,2}(?:st|nd|rd|th)?,?\s*(?:\d{4})?",
    # 2025-01-15 or 01/15/2025 or 01-15-2025
    r"\d{4}[-/]\d{2}[-/]\d{2}",
    r"\d{1,2}[-/]\d{1,2}[-/]\d{2,4}",
]

_EVENT_KEYWORDS = re.compile(
    r"(assignment|quiz|midterm|final|exam|project|essay|report|lab|"
    r"submission|due|deadline|test|presentation|reading)",
    re.IGNORECASE,
)

_DATE_RE = re.compile("|".join(_DATE_PATTERNS), re.IGNORECASE)

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _normalize_date(raw: str) -> str | None:
    raw = raw.strip().rstrip(",")
    # Already ISO
    if re.match(r"\d{4}-\d{2}-\d{2}", raw):
        return raw
    # Numeric slash/dash  01/15/2025 or 1/15/25
    m = re.match(r"(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})$", raw)
    if m:
        mo, day, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if yr < 100:
            yr += 2000
        try:
            return datetime(yr, mo, day).strftime("%Y-%m-%d")
        except ValueError:
            return None
    # Month name  Jan 15 2025 / January 15, 2025
    m = re.match(
        r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
        r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
        r"\s+(\d{1,2})(?:st|nd|rd|th)?,?\s*(\d{4})?",
        raw, re.IGNORECASE,
    )
    if m:
        mo = _MONTH_MAP[m.group(1)[:3].lower()]
        day = int(m.group(2))
        yr = int(m.group(3)) if m.group(3) else datetime.now().year
        try:
            return datetime(yr, mo, day).strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


def _regex_fallback(text: str, filename: str) -> dict:
    course_code = re.sub(r"[^A-Z0-9 ]", "", filename.upper().rsplit(".", 1)[0])[:32].strip() or "COURSE"
    events = []
    seen = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        date_match = _DATE_RE.search(line)
        if not date_match:
            continue
        iso = _normalize_date(date_match.group(0))
        if not iso or iso in seen:
            continue
        seen.add(iso)
        kw = _EVENT_KEYWORDS.search(line)
        ev_type = "other"
        if kw:
            kw_lower = kw.group(1).lower()
            if kw_lower in ("midterm", "exam", "test"):
                ev_type = "midterm"
            elif kw_lower == "final":
                ev_type = "final"
            elif kw_lower == "quiz":
                ev_type = "quiz"
            elif kw_lower in ("project", "presentation"):
                ev_type = "project"
            elif kw_lower == "lab":
                ev_type = "assignment"
            elif kw_lower in ("reading",):
                ev_type = "reading"
            else:
                ev_type = "assignment"
        title = line[:80].strip() or f"Event on {iso}"
        events.append({"title": title, "type": ev_type, "dueDateISO": iso, "notes": None})

    events.sort(key=lambda e: e["dueDateISO"])
    return {
        "course": {"code": course_code, "title": None, "term": None, "instructor": None},
        "events": events,
        "_source": "regex_fallback",
    }


# ── Main entry ────────────────────────────────────────────────────────────────
async def extract_deadlines(pdf_path: str, session_id: str) -> dict:
    """Extract structured deadlines/events JSON from a syllabus PDF.

    Tries Gemini first (text-in, not binary PDF — far fewer tokens).
    Falls back to regex extraction if Gemini is unavailable.
    """
    filename = os.path.basename(pdf_path)

    # Extract text locally first — works even without Gemini
    try:
        text = await asyncio.to_thread(_extract_pdf_text, pdf_path)
    except Exception:
        text = ""

    # Try Gemini if we have a key and got some text
    if _GENAI_AVAILABLE and GEMINI_API_KEY and text.strip():
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            prompt = f"Syllabus text:\n\n{text[:30000]}"  # cap at 30k chars

            def _call():
                return client.models.generate_content(
                    model=GEMINI_MODEL,
                    contents=[
                        types.Content(
                            role="user",
                            parts=[types.Part(text=prompt)],
                        )
                    ],
                    config=types.GenerateContentConfig(
                        system_instruction=_SYSTEM_EXTRACT
                    ),
                )

            response = await asyncio.to_thread(_call)
            return _parse_json(response.text)

        except Exception as e:
            msg = str(e)
            if "RESOURCE_EXHAUSTED" in msg or "429" in msg:
                # Fall through to regex fallback
                pass
            else:
                raise

    # Regex fallback — always works, no API needed
    if text.strip():
        return _regex_fallback(text, filename)

    raise RuntimeError(
        "Could not extract text from PDF. "
        "Ensure the file is a text-based PDF (not a scanned image)."
    )
