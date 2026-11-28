"""Turns a war.gov contracts bulletin (HTML) into structured data, without any network or AI calls.

A bulletin is a list of <p> elements inside <div class="body">: centered bold uppercase headings
name the agency (ARMY, NAVY, ...), each following paragraph is one announcement, and a final
footnote explains the markers placed after contractor names ("*Small business", "**Mandatory
source", ...). Multi-award announcements list every contractor in one paragraph, each with its own
contract number in parentheses.

Everything that can be read reliably with patterns is extracted here (contract numbers,
modification numbers, values, obligated funds, completion date, contracting activity, FMS
countries, markers). Splitting contractor names from their locations is left to Claude
(contracts.extract), because names themselves contain commas.
"""
import re

MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

# DoD contract numbers (PIIN): 6-character activity code, 2-digit fiscal year, 1-letter instrument
# type, 4-character serial; written with or without dashes (FA8625-11-C-6600, W912BU27D-A004,
# N6274219F4006).
CONTRACT_RE = re.compile(r"\b([A-Z][A-Z0-9]{5})-?(\d{2})-?([A-Z])-?([A-Z0-9]{4})\b")
MOD_RE = re.compile(r"\bmodification\s*\(?\s*(?:number\s*)?([PA]\d{5})\b|\(([PA]\d{5})\)")
MONEY_RE = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)(\s*(?:million|billion))?", re.I)
SENTENCE_SPLIT_RE = re.compile(r"(?<=[a-z0-9\)%\]])\.\s+(?=[A-Z(])")
COMPLETION_RE = re.compile(
    r"(?:estimated completion date of|expected to be complete[d]? (?:by|in)|"
    r"(?:will be )?completed? by|completion date of)\s+"
    r"([A-Z][a-z]{2,9}\.?(?:\s+\d{1,2},)?\s+\d{4})")
ACTIVITY_AFTER_RE = re.compile(r",?\s+(?:is|are|was|were)\s+the\s+contracting\s+(?:activity|activities|agency)"
                               r"(?:\s*\(([A-Z0-9-]+)\))?")
ACTIVITY_BEFORE_RE = re.compile(r"The\s+contracting\s+(?:activity|agency)\s+is\s+(?:the\s+)?(.+?)"
                                r"(?:\s*\(([A-Z0-9-]+)\))?\.(?:\s|$)")
# Typos in the source sometimes give a number an extra character (N00003022C2001); accept any
# letter-led code of 12-16 characters with mostly digits when it stands alone in parentheses.
LOOSE_CONTRACT_RE = re.compile(r"\(([A-Z][A-Z0-9-]{11,17})\)")
FMS_RE = re.compile(
    r"(?:Foreign Military Sales?|FMS)\s*(?:\(FMS\)\s*)?(?:program\s+)?(?:to|for|customers?:?|with)\s+"
    r"(?:the\s+(?:governments?\s+of\s+)?)?(.+?)(?:\.\s|\.$|;|\s+\(|\s+funds|\s+under|\s+and\s+(?:non-)?FMS)",
    re.I)
FMS_PAREN_RE = re.compile(r"(?:Foreign Military Sales?|FMS)\s*\((?!FMS\))([^)]+)\)", re.I)
NOT_COUNTRIES = {"the", "government", "governments", "of", "and", "customers", "partners", "allies"}


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()


def _money(amount: str, scale: str | None) -> float:
    v = float(amount.replace(",", ""))
    s = (scale or "").strip().lower()
    return v * (1e9 if s == "billion" else 1e6 if s == "million" else 1)


def normalize_contract(number: str) -> str:
    """W912BU-27-D-A004, W912BU27D-A004 and w912bu27da004 all become W912BU27DA004."""
    return re.sub(r"[^A-Z0-9]", "", number.upper())


def parse_date_text(text: str) -> str | None:
    """'Nov. 24, 2026' -> '2026-11-24'; 'Sept. 2027' or 'December 2023' -> '2027-09' / '2023-12'."""
    m = re.match(r"([A-Za-z]+)\.?\s+(?:(\d{1,2}),\s+)?(\d{4})", text or "")
    if not m or m.group(1)[:3].lower() not in MONTHS:
        return None
    month, day, year = MONTHS[m.group(1)[:3].lower()], m.group(2), m.group(3)
    return f"{year}-{month:02d}-{int(day):02d}" if day else f"{year}-{month:02d}"


def bulletin_date(title: str) -> str | None:
    m = re.search(r"Contracts\s+for\s+([A-Za-z]+\.?\s+\d{1,2},?\s+20\d{2})", title or "", re.I)
    return parse_date_text(m.group(1).replace(",", ", ").replace(",  ", ", ")) if m else None


def article_id(html: str, url: str | None = None) -> str | None:
    for source in (url or "", html):
        m = re.search(r"/Contract/Article/(\d+)", source) or re.search(r"/Article/(\d+)/contracts-for", source)
        if m:
            return m.group(1)
    return None


def _is_heading(p, text: str) -> bool:
    strong = p.find(["strong", "b"])
    if not strong:
        return False
    centered = "center" in (p.get("style") or "").lower() or "center" in (p.get("align") or "").lower()
    whole = _clean(strong.get_text(" ")) == text
    return (centered or whole) and text.isupper() and len(text) < 100


def _legend(text: str) -> dict:
    """'*Small business **Mandatory source' -> {'*': 'Small business', '**': 'Mandatory source'}"""
    return {m.group(1): m.group(2).strip()
            for m in re.finditer(r"(\*+)\s*([^*]+)", text) if m.group(2).strip()}


def structure(html: str, url: str | None = None) -> dict:
    """The bulletin as clean text: date, agency headings, announcements in order, marker legend."""
    from bs4 import BeautifulSoup  # only needed when reading HTML, not when building the database
    soup = BeautifulSoup(html, "html.parser")
    title = _clean(soup.title.get_text()) if soup.title else ""
    body = soup.find("div", class_="body") or soup
    agency, legend, items = None, {}, []
    for p in body.find_all("p"):
        text = _clean(p.get_text(" "))
        if not text:
            continue
        if _is_heading(p, text):
            if text != "CONTRACTS":
                agency = text
            continue
        if text.startswith("*"):
            legend.update(_legend(text))
            continue
        # A few older bulletins put several announcements in one <p>, separated by <br>.
        chunks = re.split(r"<br\s*/?>", str(p), flags=re.I) if p.find("br") else [str(p)]
        for chunk in chunks:
            t = _clean(BeautifulSoup(chunk, "html.parser").get_text(" "))
            t = re.sub(r"\s+([,.;)])", r"\1", t)          # "Inc. ," left by get_text(" ")
            if len(t) < 40:
                continue
            kind = "correction" if re.match(r"CORRECTION\b", t, re.I) else "announcement"
            items.append({"agency": agency, "kind": kind, "text": t})
    for i, it in enumerate(items, 1):
        it["seq"] = i
    canonical = re.search(r'url="(https://www\.(?:war|defense)\.gov/News/Contracts/Contract/Article/[^"]+)"', html)
    return {
        "article_id": article_id(html, url),
        "url": url or (canonical.group(1) if canonical else None),
        "title": title.split(" > ")[0],
        "date": bulletin_date(title),
        "legend": legend,
        "announcements": items,
    }


def _sentences(text: str) -> list[str]:
    return SENTENCE_SPLIT_RE.split(text)


def obligated(text: str) -> dict:
    """Funds obligated at award, from sentences like 'Fiscal 2027 ... funds in the amount of $X; ...
    funds in the amount of $Y were obligated at the time of award' (sum = X + Y)."""
    sentences = [s for s in _sentences(text) if re.search(r"obligat", s, re.I)]
    if not sentences:
        return {"obligated_usd": None, "funding_text": None}
    if any(re.search(r"\bno funds\b|\bnot? (?:be )?obligated\b|\$0 (?:will|was|were)", s, re.I) for s in sentences):
        total = 0.0
    else:
        total = 0.0
        for s in sentences:
            s = re.split(r",?\s+of which\b", s)[0]          # "... of which $X will expire" is a subset
            amounts = re.findall(r"in the amount of\s+" + MONEY_RE.pattern, s, re.I) \
                or MONEY_RE.findall(s)
            total += sum(_money(a, sc) for a, sc in amounts)
    return {"obligated_usd": total, "funding_text": " ".join(sentences)}


def fms_countries(text: str) -> list[str]:
    out = []
    chunks = [m.group(1) for m in FMS_PAREN_RE.finditer(text)]
    chunks += [re.sub(r"\(.*?\)", "", m.group(1)) for m in FMS_RE.finditer(text)]
    for chunk in chunks:
        for part in re.split(r",\s*|\s+and\s+|\s*&\s*", chunk):
            part = part.strip(" .")
            part = re.sub(r"^(?:and|the|government of|governments of)\s+", "", part, flags=re.I)
            if part and part.lower() not in NOT_COUNTRIES and part[0].isupper() and len(part) < 40 \
                    and not re.search(r"\d|funds|contract|program|percent", part, re.I) \
                    and part not in out:
                out.append(part)
    return out


def fields(text: str, legend: dict | None = None) -> dict:
    """Pattern-based fields for one announcement."""
    contracts = []
    for m in CONTRACT_RE.finditer(text):
        n = normalize_contract(m.group(0))
        if n not in contracts:
            contracts.append(n)
    for m in LOOSE_CONTRACT_RE.finditer(text):
        n = normalize_contract(m.group(1))
        if sum(c.isdigit() for c in n) >= 7 and not any(n in c or c in n for c in contracts):
            contracts.append(n)
    mods = [a or b for a, b in MOD_RE.findall(text)]
    money = MONEY_RE.search(text)
    cumulative = re.search(r"(?:cumulative|total)[^.$]{0,60}?(?:value|amount)[^.$]{0,40}?" + MONEY_RE.pattern, text, re.I)
    completion = COMPLETION_RE.search(text)
    activity = None
    after = list(ACTIVITY_AFTER_RE.finditer(text))
    before = ACTIVITY_BEFORE_RE.search(text)
    if after:
        name = _sentences(text[:after[-1].start()])[-1]
        activity = {"name": _clean(name).strip(" ,"), "code": after[-1].group(1)}
    elif before:
        activity = {"name": _clean(before.group(1)).strip(" ,"), "code": before.group(2)}
    markers = sorted({k for k in re.findall(r"(?<=[\w.)]),?(\*+)(?=[\s,])", text)}, key=len)
    is_mod = bool(re.search(r"\bmodification\b|\bexercis\w+ (?:an? )?options?\b", text, re.I))
    return {
        "contract_numbers": contracts,
        "modification_numbers": list(dict.fromkeys(mods)),
        "is_modification": is_mod,
        "value_usd": _money(*money.groups()) if money else None,
        "cumulative_value_usd": _money(*cumulative.groups()[-2:]) if cumulative else None,
        **obligated(text),
        "completion_date": parse_date_text(completion.group(1)) if completion else None,
        "contracting_activity": activity,
        "fms": bool(re.search(r"Foreign Military Sales?|\bFMS\b", text)),
        "fms_countries": fms_countries(text),
        "markers": [{"marker": k, "meaning": (legend or {}).get(k)} for k in markers],
    }


def parse(html: str, url: str | None = None) -> dict:
    """Structure plus pattern-based fields for every announcement."""
    b = structure(html, url)
    for a in b["announcements"]:
        a.update(fields(a["text"], b["legend"]))
    return b


# --- long contractor lists ---------------------------------------------------------------------
# Multiple-award announcements can list hundreds of contractors ("Name,* City, State (contract);
# ..."). Writing them all back out exceeds Claude's answer length, so they are read here instead.
_PLACE_WORD = r"[A-Z][A-Za-z.'’\-]*"
_PLACE_RE = re.compile(rf"^{_PLACE_WORD}(?:\s+(?:{_PLACE_WORD}|of|de|la|du|d’|d'))*$")
_SEGMENT_SEP_RE = re.compile(r";\s*(?:and\s+)?|(?<=\))\s+(?=[A-Z])")
MIN_LIST = 60   # shorter lists fit in Claude's answer and are left to it


US_STATES = ("Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|District of Columbia|"
             "Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|"
             "Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|"
             "New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|"
             "Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|"
             "West Virginia|Wisconsin|Wyoming|Puerto Rico|Guam|DC|D\\.C\\.")


def _awardee(segment: str):
    """'Acme Corp.,* Herndon, Virginia (W15P7T-19-D-0001)' -> dict, or None if it doesn't fit."""
    s = segment.strip()
    contract = None
    m = re.search(r"\(([A-Z][A-Z0-9-]{11,17})\)", s)
    if m:
        contract, s = normalize_contract(m.group(1)), s[:m.start()]
    else:
        s = re.split(r",?\s+(?:will|are|is|have|has)\s+(?:compete|been|awarded|being)", s)[0]
    s = s.strip().rstrip(".,").strip()
    # Typos in the source: "Reston. Virginia", "Chesapeake Virginia", "Corp.* Oakton, Virginia".
    s = re.sub(rf"(?<=[a-z])\.?\s+({US_STATES})$", r", \1", s)
    s = re.sub(r"(\*+)\s+(?=[A-Z])", r"\1, ", s)
    parts = [p.strip() for p in s.split(",")]
    if len(parts) < 3:
        return None
    city, state = parts[-2].strip("* "), parts[-1].strip("* ")
    head = ", ".join(parts[:-2]) + "".join(re.findall(r"^\*+", parts[-2]))   # "Inc.,* Herndon"
    if len(head) > 120:                                   # preamble before the first contractor
        head = re.split(r":\s+|\.\s+(?=[A-Z])", head)[-1]
    markers = "".join(re.findall(r"\*+", head)) or None
    name = re.sub(r"\s*\*+\s*", "", head).strip(" ,")
    if not (name and name[0].isalnum() and _PLACE_RE.match(city) and _PLACE_RE.match(state)
            and len(state) < 30 and len(city) < 40 and name.count("(") == name.count(")")
            and len(name) < 150):
        return None
    return {"name": name, "location": f"{city}, {state}", "contract_number": contract,
            "markers": markers, "start": None}


def awardee_list(text: str):
    """For an announcement with a long contractor list: (awardees, text with the list replaced by a
    short placeholder). None when the announcement has no such list."""
    pos, found = 0, []
    for m in list(_SEGMENT_SEP_RE.finditer(text)) + [None]:
        end = m.start() if m else len(text)
        seg = text[pos:end]
        w = _awardee(seg)
        if w:
            lead = len(seg) - len(seg.lstrip())
            start = pos + lead
            if len(seg.split(",")) > 3 and len(", ".join(seg.split(",")[:-2])) > 120:
                start = pos + seg.find(w["name"][:20])       # skip the preamble
            found.append((start, end, w))
        pos = m.end() if m else end
    if len(found) < MIN_LIST:
        return None
    awardees = [w for _, _, w in found]
    for w in awardees:
        w.pop("start")
    first, last = found[0][0], found[-1][1]
    tail = text[last:]
    # The last entry often runs into the rest of the sentence ("..., Alabama (W15P7T-19-D-0198), will compete").
    m = re.search(r"\([A-Z][A-Z0-9-]{11,17}\)", text[found[-1][0]:last])
    if m:
        tail = text[found[-1][0] + m.end():]
    elif not tail.strip():
        tail = "."
    placeholder = f"[list of {len(awardees)} contractors omitted; they are recorded separately]"
    return awardees, text[:first] + placeholder + tail
