"""
hs_lookup.py
------------
Core lookup logic for querying HS code data from the Qatar e-Customs
(Al-Nadeeb) portal: https://www.ecustoms.gov.qa/qccswui/#/home/inquiries

This calls the REAL confirmed API endpoints (reverse-engineered from the
site's own Network tab) — no mock data, no browser automation needed.

Confirmed endpoints (base: https://www.ecustoms.gov.qa/qccsw/rest/home/hsCodeService)
  POST /HSCodeSearch        {"chapheadCode": "<code>"}   -> validates the code
                             and returns chapter/heading level text.
  POST /tarrifViewingPanel2 {"chapheadCode": "<code>"}   -> returns the list of
                             matching leaf-level HS codes, each with
                             description, unit of measure, ad valorem duty
                             rate, and the list of government agencies (OGA)
                             whose approval is required for that item (if any).
  POST /tarrifViewingPage3  {"hsCode": "<12-digit code>"} -> full detail for one
                             leaf code (kept available for a future "view full
                             detail" drill-down; not required for the main
                             search table).
  POST /otherGovAgency      {"hsCode": "<12-digit code>"} -> full document
                             checklist per required agency (kept available for
                             a future drill-down; not required for the main
                             search table).

Main flow used by the app:
  1. HSCodeSearch  -> confirms the code the user typed is a valid
                      chapter/heading combination (catches typos early with a
                      clear error instead of a confusing empty table).
  2. tarrifViewingPanel2 -> the actual results: one row per matching HS code,
                      including whether another government agency's approval
                      is required, and which one(s). If none is required, the
                      item is labeled as standard clearance rather than left
                      blank.

TLS note:
  The portal's server uses older TLS settings (weaker ciphers / legacy
  renegotiation) that OpenSSL 3 rejects by default, which shows up as an
  "SSLError ... handshake failure". A LegacyTLSAdapter is mounted for the
  portal's domain ONLY, so the rest of the app is unaffected. Certificate
  verification stays ON.
"""

from dataclasses import dataclass
from typing import Optional, List, Tuple
import ssl
import time
import random
import certifi
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

BASE_URL = "https://www.ecustoms.gov.qa/qccsw/rest/home/hsCodeService"

SESSION = requests.Session()
SESSION.headers.update(
    {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json;charset=UTF-8",
        "Referer": "https://www.ecustoms.gov.qa/qccswui/",
        "Origin": "https://www.ecustoms.gov.qa",
        "X-Requested-With": "XMLHttpRequest",
        "Accept-Language": "en-US,en;q=0.9",
    }
)


_LEGACY_CTX = None


def _legacy_context():
    """One shared SSL context that accepts the portal's older cipher
    (AES128-SHA) while still VERIFYING the server certificate."""
    global _LEGACY_CTX
    if _LEGACY_CTX is None:
        ctx = create_urllib3_context()
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
        # 0x4 == OP_LEGACY_SERVER_CONNECT (fallback for Pythons that don't
        # expose the constant)
        ctx.options |= getattr(ssl, "OP_LEGACY_SERVER_CONNECT", 0x4)
        # Keep certificate verification on, using certifi's CA bundle
        ctx.load_verify_locations(certifi.where())
        _LEGACY_CTX = ctx
    return _LEGACY_CTX


class LegacyTLSAdapter(HTTPAdapter):
    """Lets Python talk to servers that only offer older ciphers, which
    Python's default cipher list rejects ("handshake failure")."""

    def init_poolmanager(self, *args, **kwargs):
        kwargs["ssl_context"] = _legacy_context()
        return super().init_poolmanager(*args, **kwargs)

    def proxy_manager_for(self, *args, **kwargs):
        kwargs["ssl_context"] = _legacy_context()
        return super().proxy_manager_for(*args, **kwargs)

    def build_connection_pool_key_attributes(self, request, verify, cert=None):
        # requests >= 2.32 injects its own preloaded SSL context per request,
        # which would override the one above. Replace it here.
        host_params, pool_kwargs = super().build_connection_pool_key_attributes(
            request, verify, cert
        )
        pool_kwargs["ssl_context"] = _legacy_context()
        return host_params, pool_kwargs


# Mounted only for the portal's domain. Certificate verification stays on.
SESSION.mount("https://www.ecustoms.gov.qa", LegacyTLSAdapter())

_session_primed = False


def _prime_session():
    """Visit the portal's own pages first, like a real browser would, so any
    session/anti-bot cookies get set before we call the API. Without this,
    some government WAFs silently return an empty or HTML response instead
    of JSON to a 'cold' request with no prior page visit."""
    global _session_primed
    if _session_primed:
        return
    try:
        SESSION.get("https://www.ecustoms.gov.qa/qccswui/", timeout=15)
        SESSION.get("https://www.ecustoms.gov.qa/qccswui/#/home/inquiries", timeout=15)
    except requests.RequestException:
        pass  # if this fails we still try the real call and surface that error
    _session_primed = True


# How many results to return for each code searched:
#   "auto"  - a short code (e.g. a 4-digit heading) returns EVERYTHING under it;
#             a code with FIRST_ONLY_FROM_DIGITS digits or more returns only the first match
#   "first" - only the first match, whatever the length
#   "all"   - every match, whatever the length
FIRST_ONLY_FROM_DIGITS = 6
RESULT_MODES = ("auto", "first", "all")

NO_APPROVAL_TEXT = "No approval required from other agency (standard clearance)"


class ApiError(Exception):
    """Raised when the portal responds but reports a non-OK status."""


@dataclass
class HSCodeItem:
    query: str                     # what the user typed
    hs_code: str                   # the full leaf HS code, e.g. 851769900001
    found: bool
    description_en: str = ""
    description_ar: str = ""
    uom: str = ""
    ad_valorem_rate: str = ""
    approval_required: bool = False
    approval_agencies: str = NO_APPROVAL_TEXT
    error: Optional[str] = None
    note: str = ""                 # informational (shown in the Notes column)


def _post(endpoint: str, payload: dict):
    """POST to one of the confirmed endpoints; returns the 'data' field or
    raises ApiError / requests.RequestException on failure."""
    _prime_session()
    resp = SESSION.post(f"{BASE_URL}/{endpoint}", json=payload, timeout=15)
    resp.raise_for_status()
    try:
        body = resp.json()
    except ValueError:
        # Show exactly what came back instead of a bare parser error, so we
        # can tell a WAF block page apart from an empty response, etc.
        snippet = resp.text[:200].replace("\n", " ").strip()
        raise ApiError(
            f"Server did not return JSON (status {resp.status_code}). "
            f"Response started with: {snippet!r}"
        )
    msg = body.get("responseMessage") or {}
    if msg.get("status") != 200:
        raise ApiError(msg.get("message") or "Request failed")
    return body.get("data")


def _oga_summary(oga_list) -> Tuple[bool, str]:
    """Turns the raw ogaResponseDTOList into (approval_required, human text)."""
    if not oga_list:
        return False, NO_APPROVAL_TEXT
    names = []
    for o in oga_list:
        name = o.get("ogaNameEn") or o.get("ogaNameAr") or ""
        if name:
            names.append(name)
    if not names:
        return False, NO_APPROVAL_TEXT
    return True, "Approval required from: " + "; ".join(names)


def search_hs_code(query: str, mode: str = "auto") -> List[HSCodeItem]:
    """
    Look up an HS code (or a chapter+heading prefix) and return every
    matching item, exactly as the portal's own search does.

    Returns a list because a partial code (e.g. an 8-digit chapter+heading)
    can match several leaf-level 12-digit HS codes — same behavior as
    searching directly on the portal.
    """
    query = query.strip()

    if not query:
        return [HSCodeItem(query=query, hs_code="", found=False, error="Empty HS code")]
    if not query.isdigit():
        return [
            HSCodeItem(
                query=query, hs_code="", found=False,
                error="HS code should contain digits only",
            )
        ]

    # Step 1: validate the chapter/heading exist (gives a clear error for typos)
    try:
        _post("HSCodeSearch", {"chapheadCode": query})
    except ApiError as e:
        return [HSCodeItem(query=query, hs_code="", found=False, error=str(e))]
    except requests.RequestException as e:
        return [HSCodeItem(query=query, hs_code="", found=False, error=f"Network error: {e}")]

    # Step 2: get the actual matching item(s) with description/UOM/rate/OGA
    try:
        items = _post("tarrifViewingPanel2", {"chapheadCode": query}) or []
    except ApiError as e:
        return [HSCodeItem(query=query, hs_code="", found=False, error=str(e))]
    except requests.RequestException as e:
        return [HSCodeItem(query=query, hs_code="", found=False, error=f"Network error: {e}")]

    if not items:
        return [
            HSCodeItem(
                query=query, hs_code="", found=False,
                error="No matching HS codes found",
            )
        ]

    total_matches = len(items)
    note = ""
    if mode == "first":
        first_only = True
    elif mode == "all":
        first_only = False
    else:  # "auto"
        first_only = len(query) >= FIRST_ONLY_FROM_DIGITS
    if first_only and total_matches > 1:
        items = items[:1]
        note = f"Showing the first of {total_matches} matches"

    results = []
    for it in items:
        approval_required, approval_agencies = _oga_summary(it.get("ogaResponseDTOList"))
        rate = it.get("adValoremRate")
        results.append(
            HSCodeItem(
                query=query,
                hs_code=it.get("code", ""),
                found=True,
                description_en=it.get("desc", ""),
                description_ar=it.get("adesc", ""),
                uom=it.get("uom", ""),
                ad_valorem_rate=f"{rate}%" if rate is not None else "",
                approval_required=approval_required,
                approval_agencies=approval_agencies,
                note=note,
            )
        )

    # Light pacing so bulk searches behave like a normal user, not a scraper
    time.sleep(random.uniform(0.1, 0.2))
    return results


def search_many(queries: List[str], on_progress=None, mode: str = "auto") -> List[HSCodeItem]:
    """
    Look up a list of HS codes / prefixes sequentially, flattening all
    matches into one combined list.

    on_progress: optional callback(index, total, current_query) so the GUI
    can update a progress bar / status line while a batch runs.
    mode: "auto" | "first" | "all" - see RESULT_MODES above.
    """
    results: List[HSCodeItem] = []
    total = len(queries)
    for i, q in enumerate(queries, start=1):
        if on_progress:
            on_progress(i, total, q)
        results.extend(search_hs_code(q, mode))
    return results


# ---------------------------------------------------------------------------
# Full detail drill-down (tarrifViewingPage3 + otherGovAgency)
# ---------------------------------------------------------------------------

@dataclass
class OgaDetail:
    name_en: str
    name_ar: str
    website: str
    documents: List[str]


@dataclass
class FullDetail:
    hs_code: str
    found: bool
    chapter_code: str = ""
    chapter_desc: str = ""
    heading_code: str = ""
    heading_desc: str = ""
    subheading_code: str = ""
    subheading_desc: str = ""
    subheading2_code: str = ""
    subheading2_desc: str = ""
    local1_code: str = ""
    local1_desc: str = ""
    local2_code: str = ""
    local2_desc: str = ""
    final_description: str = ""
    rate: Optional[str] = None
    rate_type: Optional[int] = None
    protection_rate: Optional[str] = None
    protection_rate_type: Optional[int] = None
    valuation_type: str = ""
    hs_status: Optional[str] = None
    agencies: List[OgaDetail] = None  # populated below
    error: Optional[str] = None

    def __post_init__(self):
        if self.agencies is None:
            self.agencies = []


def get_full_detail(hs_code: str) -> FullDetail:
    """
    Fetches the full classification breakdown (chapter -> heading ->
    subheading -> local subheadings) plus, for every government agency
    whose approval is required, the exact list of documents they need.

    Requires a full 12-digit leaf HS code (the kind shown in the main
    results table), not a chapter/heading prefix.
    """
    hs_code = hs_code.strip()

    if not hs_code.isdigit() or len(hs_code) < 12:
        return FullDetail(
            hs_code=hs_code, found=False,
            error="A full 12-digit HS code is needed for full detail.",
        )

    try:
        page3 = _post("tarrifViewingPage3", {"hsCode": hs_code}) or {}
    except ApiError as e:
        return FullDetail(hs_code=hs_code, found=False, error=str(e))
    except requests.RequestException as e:
        return FullDetail(hs_code=hs_code, found=False, error=f"Network error: {e}")

    if not page3:
        return FullDetail(hs_code=hs_code, found=False, error="No detail found for this code.")

    # Document checklist per agency. Not fatal if this call fails — the
    # classification detail above is still useful on its own.
    agencies: List[OgaDetail] = []
    try:
        oga_raw = _post("otherGovAgency", {"hsCode": hs_code}) or []
    except (ApiError, requests.RequestException):
        oga_raw = []

    for a in oga_raw:
        docs = [
            d.get("documentDesc")
            for d in (a.get("ogaDocList") or [])
            if d.get("documentDesc")
        ]
        agencies.append(
            OgaDetail(
                name_en=a.get("ogaName") or "",
                name_ar=a.get("arabicName") or "",
                website=a.get("wbesite") or "",  # matches the site API's own field name
                documents=docs,
            )
        )

    rate = page3.get("rate")
    protection_rate = page3.get("protectionRate")

    return FullDetail(
        hs_code=hs_code,
        found=True,
        chapter_code=page3.get("chapterCode", ""),
        chapter_desc=page3.get("chapterDesc", ""),
        heading_code=page3.get("headingCode", ""),
        heading_desc=page3.get("headingDesc", ""),
        subheading_code=page3.get("subHeadingCode", ""),
        subheading_desc=page3.get("subHeadingDesc", ""),
        subheading2_code=page3.get("subHeading2Code", ""),
        subheading2_desc=page3.get("subHeading2Desc", ""),
        local1_code=page3.get("localSubheading1Code", ""),
        local1_desc=page3.get("localSubheading1DescEn", ""),
        local2_code=page3.get("localSubheading2Code", ""),
        local2_desc=page3.get("localSubheading2DescEn", ""),
        final_description=page3.get("description", ""),
        rate=str(rate) if rate is not None else None,
        rate_type=page3.get("rateType"),
        protection_rate=str(protection_rate) if protection_rate is not None else None,
        protection_rate_type=page3.get("protectionRateType"),
        valuation_type=page3.get("valuationType", ""),
        hs_status=page3.get("hsStatus"),
        agencies=agencies,
    )