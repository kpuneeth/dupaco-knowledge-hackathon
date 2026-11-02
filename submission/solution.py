# NOTE: do not add `from __future__ import annotations` here. The harness loads this file via
# importlib without registering it in sys.modules, and @dataclass crashes on string annotations
# in that situation (Python 3.11+).
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple
from urllib.parse import urlparse

# Interface imports expected by harness/contract.py
from contract import Answer, Conflict, Page, Snapshot, Source

# Extraction Regexes
RATE_PATTERN = re.compile(r"(\d+(?:\.\d+)?\s*%|\d+(?:\.\d+)?\s*%\s*APR|\d+(?:\.\d+)?\s*%\s*APY)", re.IGNORECASE)
WORD_PATTERN = re.compile(r"[a-z0-9$%.]+")
TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
FOOTNOTE_PATTERN = re.compile(r"(%|\bAPR|\bAPY)\d+\b")       # "4.00%1" -> "4.00%", "5.39% APR1" -> "5.39% APR"
MONTHS_PATTERN = re.compile(r"\b(\d{1,3})\s*-?\s*(?:months?|mos?)\b", re.I)
YEARS_PATTERN = re.compile(r"\b(\d{1,2})\s*-?\s*years?\b", re.I)
MODEL_RANGE_PATTERN = re.compile(r"\b((?:19|20)\d{2})\s*[-–]\s*(\d{2,4})\b")
MODEL_YEAR_PATTERN = re.compile(r"\b((?:19|20)\d{2})\b")
AMOUNT_RANGE_PATTERN = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*(?:[-–]|to)\s*\$?\s?([\d,]+(?:\.\d+)?)")
AMOUNT_PLUS_PATTERN = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*\+")
AMOUNT_MAX_PATTERN = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*or less", re.I)
Q_AMOUNT_PATTERN = re.compile(r"\$\s?([\d,]+(?:\.\d+)?)\s*(k\b)?|\b(\d+(?:\.\d+)?)\s*k\b", re.I)

REFUSAL_TEXT = "That information isn't listed on our website. Please contact us for details."

STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "what", "whats", "which", "who", "how", "much", "many",
    "do", "does", "did", "you", "your", "yours", "i", "im", "me", "my", "we", "our", "us", "can", "could", "would",
    "tell", "give", "get", "provide", "show", "please", "on", "for", "of", "to", "in", "at", "by", "with", "and",
    "or", "it", "its", "this", "that", "there", "any", "some", "current", "currently", "right", "now", "today",
    "dupaco", "s", "about", "like", "know", "want", "need", "if", "as", "from", "than", "have", "has", "offer",
    "offered", "available", "see", "rate", "rates", "apy", "apr", "interest", "dividend", "yield", "percentage",
    "annual", "earn", "pay", "pays", "charge", "between", "balance", "vehicle", "model", "term", "month", "year",
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
    "november", "december", "was", "then", "back", "ago", "last", "since", "when", "where", "why", "will",
    "should", "still", "go", "going", "use", "using", "been",
}
# Question words that mean the same thing as the website's own product vocabulary.
# REPLACE_WORDS are swapped out entirely (the site never uses them in its rate tables).
REPLACE_WORDS = {"mortgage", "mortgages", "cd", "cds", "car", "truck", "vehicle", "house"}
SYNONYMS = {
    "mortgage": ["home", "loan"], "mortgages": ["home", "loan"], "cd": ["certificate"], "cds": ["certificate"],
    "car": ["auto"], "truck": ["auto"], "vehicle": ["auto"], "motorcycle": ["auto", "motorcycle"],
    "card": ["visa", "card"], "cards": ["visa", "card"], "rv": ["boat", "rv"], "boat": ["boat", "rv"],
    "heloc": ["home", "equity", "line"], "house": ["home", "loan"], "refi": ["refinance"], "share": ["share"],
}
# Words that only ever mean "a percentage" ("pay"/"earn" also mean other things).
STRICT_RATE_WORDS = {"rate", "rates", "apy", "apr", "aprs", "dividend", "yield", "percent"}
RATE_WORDS = {"rate", "rates", "apy", "apr", "aprs", "dividend", "interest", "yield", "earn", "pay", "pays", "percent"}
SUPERLATIVE_MAX = {"highest", "best", "top", "max", "maximum", "most"}
SUPERLATIVE_MIN = {"lowest", "cheapest", "minimum"}
# Product qualifiers: if the question names one, an answer row without it is the wrong product.
DISCRIMINATORS = {"adjustable", "arm", "construction", "fha", "va", "usda", "land", "lot", "commercial"}


def _stem(tok: str) -> str:
    """Plural -> singular: branches -> branch, policies -> policy, loans -> loan."""
    if len(tok) <= 3 or not tok.endswith("s") or tok.endswith(("ss", "us", "is")):
        return tok
    if tok.endswith("ies") and len(tok) > 4:
        return tok[:-3] + "y"
    if tok.endswith(("ches", "shes", "xes", "sses")):
        return tok[:-2]
    return tok[:-1]


def _tokens(text: str) -> List[str]:
    return [_stem(t) for t in TOKEN_PATTERN.findall(text.lower().replace("'", ""))]


def _money(s: str) -> float:
    return float(s.replace(",", ""))


def _clean_value(cell: str) -> str:
    return FOOTNOTE_PATTERN.sub(r"\1", cell.replace("\\", "")).strip()


def _authority(url: str) -> float:
    """How much to trust a page for rates/facts. The rate sheets are the source of truth, product
    pages mirror them, landing pages and promos drift, calculators/blog/news/PDFs are often stale."""
    p = urlparse(url)
    host = p.netloc.lower().removeprefix("www.")
    path = p.path.lower().rstrip("/")
    if host != "dupaco.com":
        return 0.5
    if path in ("/rates", "/business-rates"):
        return 5.0
    if re.search(r"calculator|/learn/blog|/newsroom|/business/resources|/hubfs|/tag/|/author/|^/20\d\d/", path):
        return 0.3
    if path.startswith(("/personal/", "/business/", "/savings-account/")):
        return 4.0
    # /membership is a lead-capture form, not the membership info page (/about/join)
    if path in ("", "/contact", "/about", "/about/join", "/about/member-services"):
        return 3.0
    if path.endswith("-lp") or path.startswith("/learn/"):
        return 1.0
    return 2.0


@dataclass
class IndexedPage:
    url: str
    title: str
    markdown: str
    fetched_at: str
    authority: float
    published: Optional[str] = None     # "YYYY-MM-DD" for dated pages (press releases, blog posts)
    lines: List[str] = field(default_factory=list)   # cleaned text lines used for passages


@dataclass
class Passage:
    """A ~500-character window of page text, used for non-rate questions."""
    page: IndexedPage
    start: int                          # line range in page.lines
    end: int
    length: int                         # number of index terms

    @property
    def text(self) -> str:
        return "\n".join(self.page.lines[self.start:self.end])

    def extended(self, extra_chars: int = 300) -> str:
        """The window plus the lines right after it (answers often sit just past the match). For
        press releases and blog posts, the lead sentence (which states the news) goes first."""
        j, size = self.end, 0
        while j < len(self.page.lines) and size < extra_chars:
            size += len(self.page.lines[j])
            j += 1
        lines = self.page.lines[self.start:j]
        if self.page.published:
            lead = next((l for l in self.page.lines[:12] if len(l) >= 120), None)
            if lead and lead not in lines:
                lines = [lead] + lines
        return "\n".join(lines)


@dataclass
class Fact:
    """One row of a rate table, with the headings above it."""
    page: IndexedPage
    table_id: int
    parent: str                         # broader heading, e.g. "Certificates"
    section: str                        # nearest heading, e.g. "Special Certificates"
    label: str                          # non-rate cells, e.g. "17 Month Fixed Certificate Special"
    values: List[Tuple[str, str]]       # (column header, cleaned value) for every % cell
    raw: str
    tokens: FrozenSet[str]              # section + label tokens
    parent_tokens: FrozenSet[str]       # tokens only found in the parent heading
    term_months: Optional[int]
    model_years: Optional[Tuple[int, int]]
    amounts: Optional[Tuple[float, float]]

    @property
    def name(self) -> str:
        if self.section and self.section.lower() not in self.label.lower():
            return f"{self.section} – {self.label}"
        return self.label

    def key(self) -> Tuple[str, Tuple[str, ...]]:
        """Identity used to find the same row on other pages."""
        norm = re.sub(r"[^a-z0-9]+", "", self.label.lower().replace("months", "month"))
        return norm, tuple(v for _, v in self.values)


@dataclass
class SnapshotIndex:
    """One full crawl of the website. Each snapshot stands alone: it is the whole site as of
    `taken_on`, so pages are never merged across snapshots."""
    snapshot_id: str
    taken_on: str                       # ISO date "YYYY-MM-DD"
    pages: List[IndexedPage] = field(default_factory=list)
    facts: List[Fact] = field(default_factory=list)
    idf: Dict[str, float] = field(default_factory=dict)
    passages: List[Passage] = field(default_factory=list)
    hours: List["BranchHours"] = field(default_factory=list)
    fees: List["Fee"] = field(default_factory=list)
    fee_idf: Dict[str, float] = field(default_factory=dict)
    branches: List[Tuple[str, IndexedPage]] = field(default_factory=list)   # (street address, page)
    postings: Dict[str, List[Tuple[int, int]]] = field(default_factory=dict)   # term -> [(passage, tf)]
    avg_len: float = 1.0


# ---------------------------------------------------------------------------------------------
# Table extraction
# ---------------------------------------------------------------------------------------------

def _term_months(text: str) -> Optional[int]:
    m = MONTHS_PATTERN.search(text)
    if m:
        return int(m.group(1))
    m = YEARS_PATTERN.search(text)
    if m and 0 < int(m.group(1)) <= 40:
        return int(m.group(1)) * 12
    return None


def _model_years(text: str) -> Optional[Tuple[int, int]]:
    m = MODEL_RANGE_PATTERN.search(text)
    if m:
        a, b = int(m.group(1)), m.group(2)
        b = int(b) if len(b) == 4 else int(str(a)[:2] + b)
        return min(a, b), max(a, b)
    m = MODEL_YEAR_PATTERN.search(text)
    if m and "model year" in text.lower():
        y = int(m.group(1))
        return (1900, y) if "older" in text.lower() else (y, y)
    return None


def _amount_range(text: str) -> Optional[Tuple[float, float]]:
    m = AMOUNT_RANGE_PATTERN.search(text)
    if m:
        return _money(m.group(1)), _money(m.group(2))
    m = AMOUNT_PLUS_PATTERN.search(text)
    if m:
        return _money(m.group(1)), float("inf")
    m = AMOUNT_MAX_PATTERN.search(text)
    if m:
        return 0.0, _money(m.group(1))
    return None


def _is_heading(line: str) -> bool:
    if not line or len(line) > 80 or line[0] in "[!|-*>" or line.endswith((".", ":", "?")):
        return False
    return not re.match(r"^\d+[A-Z]", line) and bool(re.search(r"[A-Za-z]", line))


def _split_row(line: str) -> List[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _extract_facts(page: IndexedPage, start_id: int) -> Tuple[List[Fact], int]:
    facts: List[Fact] = []
    parent, section = "", ""
    heading_run: List[str] = []
    lines = [l.strip() for l in page.markdown.split("\n")]
    i, table_id = 0, start_id
    while i < len(lines):
        line = lines[i]
        if line.startswith("|") and line.endswith("|") and line.count("|") >= 3:
            block = []
            while i < len(lines) and lines[i].startswith("|"):
                block.append(_split_row(lines[i]))
                i += 1
            table_id += 1
            facts.extend(_table_facts(page, table_id, parent, section, block))
            heading_run = []
            continue
        if line:
            cleaned = line.lstrip("#").strip().strip("*").strip()
            if _is_heading(cleaned):
                heading_run.append(cleaned)
                if len(heading_run) >= 2:
                    parent = heading_run[-2]
                section = heading_run[-1]
            else:
                heading_run = []
        i += 1
    return facts, table_id


def _table_facts(page: IndexedPage, table_id: int, parent: str, section: str,
                 block: List[List[str]]) -> List[Fact]:
    rows = [r for r in block if not all(re.fullmatch(r":?-{2,}:?", c or "---") for c in r)]
    if not rows:
        return []
    headers: List[str] = []
    if not any("%" in c for c in rows[0]):
        headers, rows = rows[0], rows[1:]
    out = []
    for cells in rows:
        if not any("%" in c for c in cells):
            continue
        label_parts, values = [], []
        for j, cell in enumerate(cells):
            header = re.sub(r"\d+$", "", headers[j]).strip() if j < len(headers) else ""
            if re.search(r"min\.|minimum|payment|points", header, re.I):
                continue
            if "%" in cell:
                values.append((header, _clean_value(cell)))
            elif cell not in ("", "—", "-"):
                label_parts.append(cell)
        label = " ".join(label_parts).replace("\\", "").strip()
        if not label:
            continue
        toks = frozenset(t for t in _tokens(f"{section} {label}") if not t.isdigit())
        ptoks = frozenset(t for t in _tokens(parent) if not t.isdigit()) - toks
        out.append(Fact(page=page, table_id=table_id, parent=parent, section=section, label=label,
                        values=values, raw=" | ".join(cells), tokens=toks, parent_tokens=ptoks,
                        term_months=_term_months(label), model_years=_model_years(label),
                        amounts=_amount_range(label)))
    return out


# ---------------------------------------------------------------------------------------------
# Passage extraction (non-rate questions)
# ---------------------------------------------------------------------------------------------

MONTH_NUM = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
     "november", "december"])}
DATE_PATTERN = re.compile(r"\b(" + "|".join(MONTH_NUM) + r")\s+(\d{1,2}),\s+((?:19|20)\d{2})\b", re.I)
# FAQ question links that only jump to an anchor on the same page ("- [What are your fees?](...#)")
ANCHOR_ONLY_LINE = re.compile(r"^[-*]?\s*(?:\[[^\]]*\]\([^)]*#[^)]*\)[\s,·|]*)+$")
# Index pages (tag/author listings, blog/news front pages) only hold teasers of other pages.
LISTING_PATH = re.compile(r"/(tag|author|page)/|/page-\d+|^/(learn/blog|newsroom|business/resources)/?$")
MD_LINK = re.compile(r"\[([^\]]*)\]\(([^)\s]+)[^)]*\)")
PASSAGE_CHARS = 500


def _published(page: Page) -> Optional[str]:
    """Publish date of press releases and blog posts: a 'Month DD, YYYY' line near the top."""
    m = DATE_PATTERN.search(page.markdown[:600])
    if m:
        return f"{m.group(3)}-{MONTH_NUM[m.group(1).lower()]:02d}-{int(m.group(2)):02d}"
    m = re.search(r"/((?:19|20)\d{2})/(\d{2})/", page.url)
    return f"{m.group(1)}-{m.group(2)}-01" if m else None


def _clean_line(line: str) -> str:
    def link(m):
        text, url = m.group(1).strip(), m.group(2)
        if url.endswith("#") or url.startswith(("tel:", "mailto:")) or not text:
            return text
        return f"{text} ({url})"
    line = MD_LINK.sub(link, line)
    line = re.sub(r"[*#]+", "", line).replace("\\", "")
    return re.sub(r"\s+", " ", line).strip()


def _page_lines(page: IndexedPage) -> List[str]:
    if LISTING_PATH.search(urlparse(page.url).path.lower()):
        return []
    lines = []
    for raw in page.markdown.split("\n"):
        raw = raw.strip()
        if (not raw or raw.startswith("|") or "![" in raw or ANCHOR_ONLY_LINE.match(raw)
                or re.fullmatch(r"\d+ min read", raw)):
            continue
        line = _clean_line(raw)
        if len(line) >= 3:
            lines.append(line)
    return lines


def _passages(page: IndexedPage) -> List[Tuple[int, int]]:
    """Overlapping windows of ~PASSAGE_CHARS, as (first line, end line) into _page_lines(page)."""
    lines = page.lines
    out, i = [], 0
    while i < len(lines):
        j, size = i, 0
        while j < len(lines) and (size < PASSAGE_CHARS or j == i):
            size += len(lines[j]) + 1
            j += 1
        out.append((i, j))
        if j >= len(lines):
            break
        i += max(1, (j - i) // 2)
    return out


# ---------------------------------------------------------------------------------------------
# Branch hours and branch addresses
# ---------------------------------------------------------------------------------------------

DAY_RE = r"(?:mon|tue|wed|thu|fri|sat|sun)[a-z]*"
DAY_LINE = re.compile(rf"^({DAY_RE}(?:\s*[-–—]\s*{DAY_RE})?)\s*:\s*(.+)$", re.I)
HOURS_KIND = re.compile(r"^(lobby|drive[- ]?(?:up|thru|through))\b\s*(.*)$", re.I)
STREET_RE = (r"\d+ [^,;]*?\b(?:Road|Rd|Street|St|Avenue|Ave|Boulevard|Blvd|Drive|Dr|Highway|Hwy|Lane|Ln|"
             r"Way|Parkway|Pkwy|Court|Ct|Place|Pl|Square)\b\.?")
DATELINE = re.compile(r"^([A-Z][A-Z .]+),\s*(Iowa|Wis\.?|Wisconsin|Ill\.?|Illinois)\b")


@dataclass
class BranchHours:
    page: IndexedPage
    kind: str                           # "lobby" or "drive-up"
    schedule: Tuple[Tuple[str, str], ...]   # (("Monday-Thursday", "8:30 a.m.–5 p.m."), ...)
    place: str                          # "Platteville (1100 E. Business Highway 151)"
    terms: FrozenSet[str]               # words that name this branch

    def text(self) -> str:
        return "; ".join(f"{d}: {t}" for d, t in self.schedule)


def _branch_place(page: IndexedPage) -> Tuple[str, FrozenSet[str]]:
    head = page.lines[:15]
    city, street = "", ""
    for line in head:
        m = DATELINE.match(line)
        if m and not city:
            city = m.group(1).title().strip()
        m = re.search(r"located at (" + STREET_RE + ")", line)
        if m and not street:
            street = m.group(1).rstrip(".")
        m = re.search(r"\bThe ([A-Z][a-z]+(?: [A-Z][a-z]+)?) (?:Dupaco )?branch\b", line)
        if m and not city:
            city = m.group(1)
    place = f"{city} ({street})" if city and street else (city or street or page.title.split("|")[0].strip())
    terms = frozenset(_tokens(f"{city} {street} {page.title.split('|')[0]}")) - STOPWORDS
    return place, terms


def _extract_hours(page: IndexedPage) -> List[BranchHours]:
    out, kind, sched = [], None, []

    def flush():
        if kind and sched:
            place, terms = _branch_place(page)
            out.append(BranchHours(page=page, kind=kind, schedule=tuple(sched), place=place, terms=terms))

    for line in page.lines:
        m = HOURS_KIND.match(line)
        if m:
            flush()
            kind, sched = ("lobby" if m.group(1).lower() == "lobby" else "drive-up"), []
            line = m.group(2).strip()
            if not line:
                continue
        if kind is None:
            continue
        d = DAY_LINE.match(line)
        if d:
            sched.append((re.sub(r"\s*[-–—]\s*", "-", d.group(1)), re.sub(r"\s*[-–—]\s*", "–", d.group(2).strip())))
        else:
            flush()
            kind, sched = None, []
    flush()
    return out


FEE_VALUE = r"(\$\d[\d,]*(?:\.\d{2})?\*?(?:\s*(?:each|per [a-z/ ]+?|plus tax|for non-members))?|Free)"
FEE_LINE = re.compile(r"^(?P<label>.{3,}?)\s+" + FEE_VALUE + r"(?:\s.*)?$")


@dataclass
class Fee:
    page: IndexedPage
    label: str
    value: str
    tokens: FrozenSet[str]


def _extract_fees(page: IndexedPage) -> List[Fee]:
    """Fee schedule lines: 'Domestic wire $25.00 each' (plain text or a table row)."""
    if not re.search(r"fee", page.url + page.title, re.I):
        return []
    out, prev = [], ""
    for raw in page.markdown.split("\n"):
        line = html_unescape(raw.strip())
        if line.startswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            cells = [c for c in cells if c and not re.fullmatch(r"-+|Col\d+", c)]
            line = " ".join(cells)
        line = re.sub(r"[*#]{2,}", "", line).strip()
        m = FEE_LINE.match(line)
        if m and not m.group("label").startswith(("•", "-", "*")) and "$" not in m.group("label"):
            label = m.group("label").strip()
            if label.startswith("(") or label[:1].islower():
                label = f"{prev} {label}"
            out.append(Fee(page=page, label=label, value=m.group(2).strip(),
                           tokens=frozenset(_tokens(label)) - STOPWORDS))
        prev = line
    return out


def html_unescape(s: str) -> str:
    return s.replace("&amp;#45;", "-").replace("&amp;", "&").replace("&#45;", "-")


def _extract_branches(page: IndexedPage) -> List[str]:
    """Branch addresses from the location finder ('Dupaco Branch' followed by an address line)."""
    out = []
    for i, line in enumerate(page.lines[:-1]):
        if line.strip().lower() == "dupaco branch" and re.match(r"^\d+ ", page.lines[i + 1]):
            out.append(page.lines[i + 1])
    return out


def _index_terms(text: str) -> List[str]:
    """Words for passage search; URLs are dropped so 'www'/'com' don't match everything."""
    return [t for t in _tokens(re.sub(r"\(https?://[^)]*\)", " ", text)) if t not in STOPWORDS]


def _index_snapshot(snapshot: Snapshot) -> SnapshotIndex:
    idx = SnapshotIndex(snapshot_id=snapshot.snapshot_id, taken_on=snapshot.taken_on[:10])
    table_id = 0
    total_len = 0
    for p in snapshot.pages:
        ip = IndexedPage(url=p.url, title=p.title, markdown=p.markdown, fetched_at=p.fetched_at,
                         authority=_authority(p.url), published=_published(p))
        idx.pages.append(ip)
        facts, table_id = _extract_facts(ip, table_id)
        idx.facts.extend(facts)
        ip.lines = _page_lines(ip)
        idx.hours.extend(_extract_hours(ip))
        idx.branches.extend((addr, ip) for addr in _extract_branches(ip))
        idx.fees.extend(_extract_fees(ip))
        for start, end in _passages(ip):
            terms = Counter(_index_terms(p.title + "\n" + "\n".join(ip.lines[start:end])))
            pid = len(idx.passages)
            idx.passages.append(Passage(page=ip, start=start, end=end, length=sum(terms.values())))
            total_len += sum(terms.values())
            for t, tf in terms.items():
                idx.postings.setdefault(t, []).append((pid, tf))
    idx.avg_len = total_len / max(1, len(idx.passages))
    fee_df = Counter(t for f in idx.fees for t in f.tokens)
    idx.fee_idf = {t: math.log(1 + len(idx.fees) / c) for t, c in fee_df.items()}
    df = Counter(t for f in idx.facts for t in f.tokens | f.parent_tokens)
    n = max(1, len(idx.facts))
    idx.idf = {t: math.log(1 + n / c) for t, c in df.items()}
    return idx


# ---------------------------------------------------------------------------------------------
# Question parsing
# ---------------------------------------------------------------------------------------------

@dataclass
class Query:
    text: str
    words: Set[str]                     # raw lowercase words
    terms: Set[str]                     # stemmed content words + synonyms
    term_months: Optional[int]
    model_year: Optional[int]
    amount: Optional[float]
    wants_rate: bool
    superlative: Optional[str]          # "max" / "min"
    is_list: bool


def _parse_query(question: str) -> Query:
    q = question.lower().replace("’", "'")
    words = set(TOKEN_PATTERN.findall(q.replace("'", "")))
    terms: Set[str] = set()
    for w in words:
        if w.isdigit():
            continue
        for t in ([] if w in REPLACE_WORDS else [w]) + SYNONYMS.get(w, []):
            t = _stem(t)
            if t not in STOPWORDS and w not in STOPWORDS:
                terms.add(t)
            elif w in SYNONYMS:
                terms.add(t)
    model_year = None
    if re.search(r"model|vehicle|car|auto|truck|motorcycle|boat|rv|atv|snowmobile", q):
        years = [int(y) for y in MODEL_YEAR_PATTERN.findall(q) if 1980 <= int(y) <= 2030]
        model_year = years[0] if years else None
    amount = None
    for m in Q_AMOUNT_PATTERN.finditer(q):
        if m.group(1):
            amount = _money(m.group(1)) * (1000 if m.group(2) else 1)
        else:
            amount = float(m.group(3)) * 1000
        break
    # "Apple Pay" / "Google Pay" is a wallet, not "what does it pay"
    rate_words = set(TOKEN_PATTERN.findall(re.sub(r"\b(apple|google|samsung|android) pay\b", " ", q)))
    sup = "max" if words & SUPERLATIVE_MAX else ("min" if words & SUPERLATIVE_MIN else None)
    is_list = bool(re.search(r"\b(all|list|every|each|what (?:kinds?|types?)|(?:do|does) \w+ (?:have|offer))\b", q)
                   or re.search(r"\bwhich\b.*\b(cards|certificates|cds|accounts|loans)\b", q)
                   or re.search(r"\b(cards|certificates|cds|accounts|loans)\b.*\brates\b|\brates\b.*\b(cards|certificates|cds)\b", q))
    return Query(text=q, words=words, terms=terms, term_months=_term_months(q), model_year=model_year,
                 amount=amount, wants_rate=bool(rate_words & RATE_WORDS) or "%" in q or (
                     # "How much is a 7-year car loan on a 2024 vehicle?" names a rate-table row
                     bool(_term_months(q) or model_year) and bool(re.search(r"\b(loan|certificate|cd)s?\b", q))), superlative=sup,
                 is_list=is_list)


# ---------------------------------------------------------------------------------------------
# Fact matching
# ---------------------------------------------------------------------------------------------

def _flag(text: str, pattern: str) -> bool:
    return bool(re.search(pattern, text))


FLAG_PATTERNS = {
    # flag: (regex, hard) -- hard flags must agree; soft flags only rank.
    "ira": (r"\b(ira|iras|roth|traditional|retirement)\b", True),
    "refinance": (r"\b(refinanc\w*|refi)\b", True),
    "intro": (r"\b(intro\w*|balance transfer|promo\w*)\b", True),
    "equity": (r"\bequity\b", True),
    "jumbo": (r"\bjumbo\b", False),
    "special": (r"\bspecial\b", False),
    "business": (r"\bbusiness\b", False),
}


def _fact_flags(f: Fact) -> Set[str]:
    # The parent heading is a guess (it can belong to the previous table), so it never sets flags.
    text = f"{f.section} {f.label} {urlparse(f.page.url).path}".lower()
    return {k for k, (pat, _) in FLAG_PATTERNS.items() if _flag(text, pat)}


def _match_facts(snap: SnapshotIndex, query: Query) -> List[Tuple[float, int, Fact]]:
    """Facts that fit the question's qualifiers, with (lexical score, mismatch count, fact)."""
    q_text = query.text + " " + " ".join(sorted(query.terms))
    q_flags = {k for k, (pat, _) in FLAG_PATTERNS.items() if _flag(q_text, pat)}
    out = []
    for f in snap.facts:
        overlap = query.terms & f.tokens
        if not overlap:
            continue
        score = sum(snap.idf.get(t, 0.0) for t in overlap)
        score += 0.5 * sum(snap.idf.get(t, 0.0) for t in query.terms & f.parent_tokens)
        # Term, model year and balance/loan amount must fit when both sides state them.
        if query.term_months is not None:
            if f.term_months is None or f.term_months != query.term_months:
                continue
        if query.model_year is not None and f.model_years is not None:
            if not (f.model_years[0] <= query.model_year <= f.model_years[1]):
                continue
        if query.amount is not None and f.amounts is not None:
            if not (f.amounts[0] <= query.amount <= f.amounts[1]):
                continue
        f_flags = _fact_flags(f)
        mismatches = 0
        hard_fail = False
        for k, (_, hard) in FLAG_PATTERNS.items():
            if (k in q_flags) != (k in f_flags):
                if hard:
                    hard_fail = True
                    break
                if k == "business" and query.is_list and k not in q_flags:
                    continue
                mismatches += 1
        if hard_fail:
            continue
        out.append((score, mismatches, f))
    return out


def _value_columns(f: Fact, query: Query) -> List[Tuple[str, str]]:
    def short(h: str) -> str:
        hl = h.lower()
        if "yield" in hl or "apy" in hl:
            return "APY"
        if "dividend" in hl:
            return "dividend rate"
        if "annual percentage rate" in hl or "apr" in hl:
            return "APR"
        if "rate" in hl:
            return "rate"
        return ""
    cols = [(short(h), v) for h, v in f.values]
    if "apy" in query.words or "yield" in query.words:
        picked = [c for c in cols if c[0] == "APY"]
    elif query.words & {"apr", "aprs"}:
        picked = [c for c in cols if c[0] == "APR"]
    elif "dividend" in query.words:
        picked = [c for c in cols if c[0] == "dividend rate"]
    else:
        picked = []
    return picked or cols


def _percent(v: str) -> float:
    m = re.search(r"(\d+(?:\.\d+)?)\s*%", v)
    return float(m.group(1)) if m else 0.0


def _format_fact(f: Fact, query: Query) -> str:
    vals = ", ".join(f"{h} {v}".strip() if h and h.lower() not in v.lower() else v
                     for h, v in _value_columns(f, query))
    return f"{f.name}: {vals}"


def _sources_for(snap: SnapshotIndex, chosen: List[Fact]) -> List[Source]:
    """Cite every trusted page that shows the same rows (product pages first)."""
    keys = {f.key() for f in chosen}
    pages: Dict[str, Tuple[float, IndexedPage, str]] = {}
    for f in snap.facts:
        if f.page.authority >= 3.0 and f.key() in keys and f.page.url not in pages:
            pages[f.page.url] = (f.page.authority, f.page, f.raw)
    for f in chosen:
        pages.setdefault(f.page.url, (f.page.authority, f.page, f.raw))
    ranked = sorted(pages.values(), key=lambda x: (x[0] == 5.0, -x[0], "/business" in x[1].url.lower(),
                                                   len(x[1].url), x[1].url))
    return [Source(url=p.url, snapshot_id=snap.snapshot_id, quote=raw) for _, p, raw in ranked[:5]]


def _answer_from_facts(snap: SnapshotIndex, query: Query) -> Optional[Answer]:
    matches = _match_facts(snap, query)
    if not matches:
        return None
    best_lex = max(s for s, _, _ in matches)
    if best_lex < 2.0:
        return None
    min_mis = min(m for s, m, _ in matches if s >= 0.6 * best_lex)
    pool = [(s, m, f) for s, m, f in matches if s >= 0.6 * best_lex and m == min_mis]

    if query.is_list and query.term_months is None and query.amount is None:
        # List questions: every trusted row that matches as well as the best one, deduplicated.
        top = max(s for s, _, _ in pool)
        rows, seen = [], set()
        for s, _, f in sorted(pool, key=lambda x: (-x[2].page.authority, x[2].table_id)):
            if s < 0.85 * top or f.page.authority < 3.0:
                continue
            k = (f.name.lower(), tuple(v for _, v in f.values))
            if k not in seen:
                seen.add(k)
                rows.append(f)
        chosen = rows[:16]
    else:
        # Pick the table: best lexical fit first, then the most authoritative page.
        top = max(s for s, _, _ in pool)
        best = max((x for x in pool if x[0] >= 0.85 * top),
                   key=lambda x: (x[2].page.authority, x[0], -x[2].table_id))
        table, page, parent = best[2].table_id, best[2].page.url, best[2].parent
        chosen = [f for s, _, f in pool if f.table_id == table and s >= 0.9 * best[0]]
        # Sibling tables under the same heading that fit equally well (e.g. Free Checking and
        # 1st Rate Checking are separate tables under "Checking Accounts").
        chosen += [f for s, _, f in pool if f.table_id != table and f.page.url == page
                   and f.parent == parent and parent and s >= 0.98 * best[0]
                   and query.terms & set(_tokens(f.section))]
        if query.superlative == "max":
            chosen = [max(chosen, key=lambda f: max(_percent(v) for _, v in f.values))]
        elif query.superlative == "min":
            chosen = [min(chosen, key=lambda f: min(_percent(v) for _, v in f.values))]
        chosen = chosen[:8]
    if not chosen:
        return None

    # A product qualifier the website never shows next to these rows (e.g. "7/1 ARM").
    disc = query.words & DISCRIMINATORS
    if disc and not any(disc & set(TOKEN_PATTERN.findall(f"{f.section} {f.label}".lower())) for f in chosen):
        return Answer(text=REFUSAL_TEXT, confident=False)

    text = "; ".join(_format_fact(f, query) for f in chosen) + "."
    return Answer(text=text, sources=_sources_for(snap, chosen), confident=True)


# ---------------------------------------------------------------------------------------------
# Text questions
# ---------------------------------------------------------------------------------------------

LINK_WORDS = {"link", "url", "website", "webpage", "locator", "page", "site"}
LINK_PHRASE = re.compile(r"\bwhere (?:can|do|should) i (?:find|see|check|look)\b.*\bonline\b")
# Words that describe hours/branches in general rather than naming a specific branch.
GENERIC_BRANCH_WORDS = {"lobby", "hour", "drive", "up", "thru", "through", "branch", "open", "close", "closed",
                        "time", "general", "same", "keep", "all", "every", "differ", "different", "weekend",
                        "weekday", "saturday", "sunday", "monday", "tuesday", "wednesday", "thursday",
                        "friday", "location", "office", "usual", "normal", "typical", "regular", "address",
                        "where", "located", "find", "locate", "street", "avenue", "ave", "road", "st", "rd",
                        "window", "teller", "get", "direction", "town"}


def _name_terms(question: str) -> Set[str]:
    return {t for t in _query_terms(question) if t not in GENERIC_BRANCH_WORDS}


def _answer_hours(snap: SnapshotIndex, question: str) -> Optional[Answer]:
    q = question.lower()
    # "When do lobbies close?" is about hours, but "When does the Hy-Vee branch close?" is about a
    # closure date, so "when ... close" only counts when no branch is named.
    asks_close = bool(re.search(r"\bwhen\b.*\bclose\b", q)) and not _name_terms(question)
    if not (re.search(r"\bhours?\b|what time|\b(?:mon|tues|wednes|thurs|fri|satur|sun)days?\b|\bweekends?\b"
                      r"|\bwhen\b.*\bopen\b", q) or asks_close) or not snap.hours:
        return None
    kind = "drive-up" if re.search(r"drive|thru", q) else "lobby"
    blocks = [h for h in snap.hours if h.kind == kind]
    if not blocks:
        return None
    names = _name_terms(question)
    if names:
        hit = [h for h in blocks if names & h.terms]
        if not hit:
            # A specific branch we have no hours for: don't guess.
            return Answer(text="I can't find hours for that branch on our website. Please contact us "
                               "or check the branch locator for its current hours.", confident=False)
        h = hit[0]
        return Answer(text=f"{kind.capitalize()} hours for {h.place}: {h.text()}.",
                      sources=[Source(url=h.page.url, snapshot_id=snap.snapshot_id)])
    # General question: hours differ by branch, so give the common schedule(s) and ask which branch.
    groups: Dict[Tuple, List[BranchHours]] = {}
    for h in blocks:
        groups.setdefault(h.schedule, []).append(h)
    ranked = sorted(groups.values(), key=lambda g: (-len(g), g[0].page.url))
    parts = []
    for g in ranked:
        places = ", ".join(sorted({h.place for h in g}))
        parts.append(f"{g[0].text()} (e.g. {places})")
    text = (f"{kind.capitalize()} hours vary by branch. Most common: {parts[0]}."
            + (f" Other branches: {' | '.join(parts[1:])}." if len(parts) > 1 else "")
            + " Which branch would you like hours for?")
    srcs = [Source(url=g[0].page.url, snapshot_id=snap.snapshot_id) for g in ranked[:3]]
    return Answer(text=text, sources=srcs)


FEE_WORDS = {"fee", "fees", "charge", "charges", "cost", "costs", "price", "much"}
FEE_SYNONYMS = {"cashier": ["official"], "cashiers": ["official"], "atm": ["atm"], "notary": ["notary"]}


def _answer_fee(snap: SnapshotIndex, question: str) -> Optional[Answer]:
    q = question.lower().replace("'", "")
    words = set(TOKEN_PATTERN.findall(q))
    if not (words & FEE_WORDS) or not snap.fees:
        return None
    terms = set()
    for w in words - FEE_WORDS:
        if w in STOPWORDS:              # before stemming: "does" -> "doe" is not a stopword
            continue
        for t in FEE_SYNONYMS.get(w, [w]):  # synonyms replace the word ("cashier" never appears)
            t = _stem(t)
            if t not in STOPWORDS and not t.isdigit():
                terms.add(t)
    if not terms:
        return None
    # Title-case product names ("Free Checking") must all be in the row, so the Analysis Checking
    # fee doesn't answer for Free Checking.
    names = {_stem(w.lower()) for w in re.findall(r"(?<!^)\b([A-Z][a-z]+)\b", question.strip())} & terms
    need = min(2, len(terms))           # "order checks" shouldn't match on "check" alone
    scored = []
    unseen = max(snap.fee_idf.values())     # a question word no fee label uses counts fully against
    for f in snap.fees:
        hit = terms & f.tokens
        if not hit or not names <= f.tokens:
            continue
        weight = sum(snap.fee_idf.get(t, unseen) for t in terms)
        coverage = sum(snap.fee_idf.get(t, 0.0) for t in hit) / max(weight, 1e-9)
        scored.append((coverage, f))
    best = [x for x in scored if len(terms & x[1].tokens) >= need]
    if not best:
        return None
    best_c, best_f = max(best, key=lambda x: (x[0], x[1].page.url))
    if best_c < 0.6:
        return None
    rows, seen = [], set()
    for c, f in sorted(scored, key=lambda x: -x[0]):
        # one fee schedule (the site has two copies of it), rows that fit about as well
        # weaker fits must be mostly about the question ("Domestic wire" yes, "Processing fee
        # for payment using a card" no)
        fits = c >= 0.5 * best_c or (c >= 0.4 * best_c and 2 * len(terms & f.tokens) >= len(f.tokens))
        if f.page is best_f.page and fits and f.label.lower() not in seen:
            seen.add(f.label.lower())
            rows.append(f)
    rows = rows[:5]
    text = "; ".join(f"{f.label}: {f.value.replace('*', '')}" for f in rows) + "."
    return Answer(text=text, sources=[Source(url=rows[0].page.url, snapshot_id=snap.snapshot_id,
                                             quote=f"{rows[0].label} {rows[0].value}")])


PRICE_WORDS = {"fee", "fees", "charge", "charges", "cost", "costs", "price", "prices", "pricing"}
PRICE_TEXT = re.compile(r"\$\s?\d|\bfree\b|\bno (?:\w+ )?(?:fee|charge|cost)s?\b|\bwaive", re.I)


def _is_price_question(question: str) -> bool:
    q = question.lower()
    return bool(set(TOKEN_PATTERN.findall(q)) & PRICE_WORDS) or bool(re.search(r"\bhow much (?:is|are|does|do)\b", q))


COUNT_Q = re.compile(r"\b(?:how many|number of|count of)\s+(?:dupaco(?:'?s)?\s+)?([a-z]+)")
# Words that don't narrow a count: "how many branch offices are there" is still the branch count.
COUNT_GENERIC = {"number", "office", "location", "total", "operate", "exist", "currently", "open"}


def _answer_count(snap: SnapshotIndex, question: str) -> Optional[Answer]:
    """'How many branches/employees/members?' Counts drift over time (23 branches -> 22 after a
    closure) and old pages keep the old number, so take the majority of the 5 newest statements."""
    m = COUNT_Q.search(question.lower())
    if not m:
        return None
    noun = _stem(m.group(1))
    if set(_query_terms(question)) - {noun} - COUNT_GENERIC:
        return None                     # extra qualifiers ("employees used VTO") -> passage search
    pat = re.compile(rf"\b(\d[\d,]*)\+?\s+(?:[\w’'-]+\s+){{0,2}}{re.escape(noun[:5])}\w*", re.I)
    mentions = []
    for page in snap.pages:
        date = page.published or (snap.taken_on if page.authority >= 3.0 else None)
        if not date:
            continue
        for line in page.lines:
            for mm in pat.finditer(line):
                value = mm.group(1).replace(",", "")
                if not (1900 <= int(value) <= 2100):
                    mentions.append((date, value, page, line))
    if not mentions:
        return None
    recent = sorted(mentions, key=lambda x: x[0], reverse=True)[:5]
    votes = Counter(v for _, v, _, _ in recent)
    value = max(votes, key=lambda v: (votes[v], max(d for d, vv, _, _ in recent if vv == v)))
    date, _, page, line = next(x for x in recent if x[1] == value)
    sentence = next((s for s in re.split(r"(?<=[.!?])\s+", line) if value in s.replace(",", "")), line)
    return Answer(text=sentence.strip(), sources=[Source(url=page.url, snapshot_id=snap.snapshot_id, quote=sentence)],
                  conflict_note=f"Most recent statements (as of {date}) say {value}.")


def _answer_branch_address(snap: SnapshotIndex, question: str) -> Optional[Answer]:
    q = question.lower()
    if not re.search(r"\baddress\b|\bwhere is\b|\blocated\b|\blocation of\b|\bget to\b|\bdirections?\b"
                     r"|\bbranch in\b", q):
        return None
    names = _name_terms(question)
    if not names:
        return None
    for addr, page in snap.branches:
        if names & set(_tokens(addr)):
            return Answer(text=f"The {' '.join(sorted(n.title() for n in names))} branch is at {addr}.",
                          sources=[Source(url=page.url, snapshot_id=snap.snapshot_id, quote=addr)])
    return None
TEXT_SYNONYMS = {
    "locator": ["location", "find"], "eligible": ["eligibility", "membership", "live", "work"],
    "join": ["membership", "member"], "wallet": ["wallet", "pay"], "vto": ["volunteer"],
    "closing": ["close"], "closed": ["close"], "open": ["open"],
    "college": ["student"], "university": ["student"], "tuition": ["student"],
    "requirement": ["eligible", "eligibility", "live", "work"], "qualify": ["eligible", "live", "work"],
    "membership": ["join"], "closest": ["near", "mile"], "nearest": ["near", "mile"],
    "change": ["update"], "moved": ["update", "address"],
}
# Phrases that ask the same thing as a single word the site uses.
PHRASE_SYNONYMS = [(re.compile(r"\bwho can (?:join|become)\b"), ["eligible", "live", "work"])]
BM25_K1, BM25_B = 1.2, 0.75
TIME_RE = r"\b\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?|noon)"
ANSWER_TYPES = [
    # (question trigger, pattern the answer passage should contain)
    (r"\bhours?\b|\bopen\b|\bclose[sd]?\b|what time", TIME_RE),
    (r"\baddress\b|\bwhere is\b|\blocated\b", r"\d+ [A-Z][a-z]+.*\b[A-Z]{2},? \d{5}"),
    (r"\bwhen\b|\bdate\b", r"\b(?:" + "|".join(MONTH_NUM) + r")\s+\d{1,2},\s+\d{4}"),
    (r"\bphone\b|\bcall\b|\bcontact\b|\b(?:update|change)\b.*\b(?:address|info|information|name|email)\b|\bmoved\b",
     r"\b\d{3}[-.]\d{3}[-.]\d{4}\b"),
    (r"\brouting\b", r"\b\d{9}\b"),
]


def _query_terms(question: str) -> List[str]:
    terms = []
    for w in TOKEN_PATTERN.findall(question.lower().replace("'", "")):
        if w in STOPWORDS and w not in TEXT_SYNONYMS:
            continue
        for t in [w] + TEXT_SYNONYMS.get(w, []):
            t = _stem(t)
            if t not in STOPWORDS and not t.isdigit() and t not in terms:
                terms.append(t)
    for pat, extra in PHRASE_SYNONYMS:
        if pat.search(question.lower()):
            terms += [t for t in extra if t not in terms]
    return terms


def _unknown_names(snap: SnapshotIndex, question: str) -> Set[str]:
    """Capitalised words (names) in the question that appear nowhere in this snapshot."""
    words = re.findall(r"(?<![.?!]\s)(?<!^)\b([A-Z][a-z]{2,})\b", question.strip())
    return {w for w in words if w.lower() not in STOPWORDS and _stem(w.lower()) not in snap.postings
            and w.lower() not in snap.postings}


def _is_blog(url: str) -> bool:
    return "/blog/" in url or "/learn/" in url


def _search_passages(snap: SnapshotIndex, question: str, limit: int = 5) -> List[Tuple[float, Passage]]:
    """BM25 over passages, nudged toward trusted pages. Among near-equal hits, the most recently
    published page wins, so a 2025 press release beats the 2021 one it updates."""
    n = len(snap.passages)
    scores: Dict[int, float] = {}
    for t in _query_terms(question):
        posting = snap.postings.get(t)
        if not posting:
            continue
        idf = math.log(1 + (n - len(posting) + 0.5) / (len(posting) + 0.5))
        for pid, tf in posting:
            norm = tf * (BM25_K1 + 1) / (tf + BM25_K1 * (1 - BM25_B + BM25_B * snap.passages[pid].length / snap.avg_len))
            scores[pid] = scores.get(pid, 0.0) + idf * norm
    if not scores:
        return []
    ranked = sorted(((sc * (1 + 0.15 * snap.passages[pid].page.authority), pid) for pid, sc in scores.items()),
                    reverse=True)[:60]
    # Rerank: passages holding the kind of thing asked for (a time, an address, a number...) and
    # the question's word pairs as phrases ("student loan", "lobby hours").
    q = question.lower()
    want = [pat for trigger, pat in ANSWER_TYPES if re.search(trigger, q)]
    m = COUNT_Q.search(q)
    if m:   # "how many branches" -> a number right before "branch..."
        want.append(rf"\b\d[\d,]*\+?\s+(?:[\w-]+\s+){{0,2}}{re.escape(_stem(m.group(1))[:5])}")
    words = [w for w in TOKEN_PATTERN.findall(q.replace("'", "")) if w not in STOPWORDS]
    pairs = [(a, b) for a, b in zip(words, words[1:])]
    q_terms = set(_query_terms(question))
    q_typed = set(_tokens(question)) - STOPWORDS      # without synonyms: "eligible" is not "membership"
    # Multi-word product names as typed ("Free Checking", "Bright Savings") should appear verbatim.
    names = [n for n in re.findall(r"(?<!^)\b([A-Z][a-z]+(?: [A-Z][a-z]+)*)\b", question.strip())
             if not set(n.lower().split()) <= STOPWORDS]
    reranked = []
    for sc, pid in ranked:
        text = snap.passages[pid].text.lower()
        title = set(_tokens(snap.passages[pid].page.title.split("|")[0])) - STOPWORDS
        title_hits = len(q_terms & title)
        sc *= 1 + 0.2 * min(title_hits, 3)
        if title and title <= q_typed:      # the page is about exactly what was asked
            sc *= 1.5
        for pat in want:
            if re.search(pat, text, re.I):
                sc *= 2.0
        for a, b in pairs:
            if re.search(rf"\b{re.escape(a[:5])}\w*\W+{re.escape(b[:5])}", text):
                sc *= 1.25
        for n in names:
            if n in snap.passages[pid].text:
                sc *= 1.5
        reranked.append((sc, pid))
    ranked = sorted(reranked, reverse=True)[:40]
    if want:
        typed = [(sc, pid) for sc, pid in ranked
                 if any(re.search(pat, snap.passages[pid].text, re.I) for pat in want)]
        if typed and typed[0][0] >= 0.4 * ranked[0][0]:
            ranked = typed
    top = ranked[0][0]
    if top < 4.0:
        return []
    band = [(sc, snap.passages[pid]) for sc, pid in ranked if sc >= 0.9 * top]
    if _is_blog(band[0][1].page.url):
        # A blog post explains the topic; a Dupaco product page scoring close to it states the offer.
        site = [(sc, snap.passages[pid]) for sc, pid in ranked
                if sc >= 0.85 * top and snap.passages[pid].page.authority >= 2.0]
        if site:
            band = site
    if band[0][1].page.published:
        band.sort(key=lambda x: (x[1].page.published or "0000", x[0]), reverse=True)
    else:
        # near-equal undated hits: the more trusted page ("Join" beats "Scholarships")
        band.sort(key=lambda x: (x[1].page.authority, x[0]), reverse=True)
    return band[:limit]


def _answer_link(snap: SnapshotIndex, query: Query) -> Optional[Answer]:
    """'What link/URL should I use for X?' -> the page itself, not its text."""
    url = None
    if query.wants_rate:
        facts = _answer_from_facts(snap, query)
        if facts is not None and facts.sources:
            url = facts.sources[0].url
    if url is None:
        ranked = _search_passages(snap, query.text)
        trusted = [p for _, p in ranked if p.page.authority >= 2.0]
        if not trusted:
            return None
        url = trusted[0].page.url
    return Answer(text=f"You can find it at {url}", sources=[Source(url=url, snapshot_id=snap.snapshot_id)])


# ---------------------------------------------------------------------------------------------
# Conflicts
# ---------------------------------------------------------------------------------------------

# Rate-table rows are grouped into product families so the same row matches across pages whose
# headings differ ("Auto Loan Rates" on /rates, "Auto & Motorcycle Loans" on the product page).
# Rows that fit no family are skipped: precision matters more than recall here.
FAMILIES = [
    (r"model year|\bauto\b|motorcycle", "Auto loan"),
    (r"\bboat\b|\brv\b", "Boat & RV loan"),
    (r"\bpurchase\b.*\byear\b", "Home loan purchase (mortgage)"),
    (r"cash[- ]?out", "Cash-out refinance"),
    (r"equity refinance", "Home equity refinance"),
    (r"refinance", "Home loan refinance (mortgage)"),
    (r"heloc|home equity line", "Home equity line of credit (HELOC)"),
    (r"home equity loan", "Home equity loan"),
    (r"personal loan", "Personal loan"),
    (r"student", "Student loan"),
    (r"visa|credit limit|credit card", "Visa credit card"),
    (r"\bira\b|\broth\b|traditional", "IRA certificate"),
    (r"special", "Special certificate"),
    (r"\bregular\b|certificate", "Certificate"),
    (r"investor", "Investor's Choice"),          # before Achieve: both are "Money Market" rows
    (r"achieve|money market|high-yield", "Achieve Money Market"),
    (r"1st rate checking", "1st Rate Checking"),
    (r"share savings", "Share Savings"),
    (r"you[- ]name[- ]it", "You Name It Savings"),
    (r"holiday club", "Holiday Club Savings"),
    (r"bright savings", "Bright Savings"),
]
FAMILY_WORDS = re.compile(r"\b(business|achieve|money|market|share|savings?|you|name|it|holiday|club|bright|accounts?|"
                          r"checking|1st|rate|certificates?|investor.s|choice|high|yield|online|only)\b")
CLEAN_RATE = re.compile(r"^\d+(?:\.\d+)?%(?:\s*(?:APR|APY))?(?:\s*[-–]\s*\d+(?:\.\d+)?%?(?:\s*(?:APR|APY))?)?$")


def _family(f: Fact) -> Optional[Tuple[str, str]]:
    """(family name, tier signature) for a rate row, e.g. ("Auto loan", "202326modelyear60month")."""
    text = f"{f.section} {f.label}".lower()
    for pat, name in FAMILIES:
        if re.search(pat, text):
            path = urlparse(f.page.url).path.lower()
            if "business" in text or path.startswith(("/business", "/business-rates")):
                name = "Business " + name
            tier = re.sub(r"[^a-z0-9]+", "", FAMILY_WORDS.sub(" ", f.label.lower().replace("months", "month")))
            tier += "".join(re.findall(r"\$[\d,]+", f.section)).replace(",", "")   # "Minimum credit limit: $500"
            return name, tier
    return None


def _metric(header: str, value: str, i: int) -> str:
    h = f"{header} {value}".lower()
    if "apy" in h:
        return "APY"
    if "apr" in h:
        return "APR"
    return "rate" if header else f"col{i}"     # no header row: compare by column position only


def _rate_conflicts(snapshots: List[SnapshotIndex]) -> List[Conflict]:
    # identity -> observations (snapshot, page, metric, numeric value, display value)
    obs: Dict[Tuple[str, str], List[Tuple[SnapshotIndex, IndexedPage, str, Tuple[float, ...], str]]] = {}
    labels: Dict[Tuple[str, str], Fact] = {}
    successors: Dict[str, List[Fact]] = {}     # family -> trusted rows in the newest snapshot
    for snap in snapshots:
        for f in snap.facts:
            ident = _family(f)
            if ident is None:
                continue
            for i, (header, value) in enumerate(f.values):
                value = re.sub(r"\s+\d$", "", value).strip()       # stray footnote: "20.5% 1"
                if not CLEAN_RATE.match(value):
                    continue
                metric = _metric(header, value, i)
                nums = tuple(float(x) for x in re.findall(r"\d+(?:\.\d+)?", value))
                shown = re.sub(r"\s*(APR|APY)", "", value).replace(" ", "")
                if metric in ("APR", "APY"):
                    shown += f" {metric}"
                obs.setdefault(ident, []).append((snap, f.page, metric, nums, shown))
                labels.setdefault(ident, f)
            if snap is snapshots[-1] and f.page.authority >= 4.0:
                successors.setdefault(ident[0], []).append(f)

    # Row position of each identity on the current rate sheet (most trusted page first), used to
    # pick the headline tier when several tiers share one stale page.
    latest = snapshots[-1]
    row_pos: Dict[Tuple[str, str], Tuple[float, int]] = {}
    page_start: Dict[int, int] = {}
    for i, f in enumerate(latest.facts):
        start = page_start.setdefault(id(f.page), i)
        ident = _family(f)
        if ident is not None:
            pos = (-f.page.authority, i - start)
            if ident not in row_pos or pos < row_pos[ident]:
                row_pos[ident] = pos

    def trust(r):
        # The newest value on a trusted page (rate sheet or product page) wins. A row that only
        # survives on stale pages (calculator, promo) resolves to its last trusted value.
        snap, page = r[0], r[1]
        return page.authority >= 4.0, snap.taken_on, page.authority, page.url.rstrip("/").endswith("/rates")

    merged: Dict[FrozenSet[Tuple[str, Tuple[float, ...]]], Conflict] = {}
    meta: Dict[FrozenSet[Tuple[str, Tuple[float, ...]]], Tuple[Tuple, Tuple[float, int]]] = {}
    # personal products first, so a table repeated for business/IRA merges under the personal name
    for ident, rows in sorted(obs.items(), key=lambda kv: (kv[0][0].startswith("Business"), "IRA" in kv[0][0])):
        by_metric: Dict[str, Set[Tuple[float, ...]]] = {}
        for _, _, metric, nums, _ in rows:
            by_metric.setdefault(metric, set()).add(nums)
        if not any(len(v) > 1 for v in by_metric.values()):
            continue
        f = labels[ident]
        best = max(rows, key=trust)
        pos = row_pos.get(ident, (0.0, 10 ** 6))
        if best[0] is not snapshots[-1] and f.model_years:
            # The tier was renamed on the rate sheet ("2023-26 Model Year" -> "2024-27"): the
            # current value is the newest trusted row for the same term and overlapping years.
            nxt = next((g for g in successors.get(ident[0], []) if g.term_months == f.term_months and g.model_years
                        and g.model_years[0] <= f.model_years[1] and f.model_years[0] <= g.model_years[1]), None)
            if nxt is not None:
                pos = row_pos.get(_family(nxt), pos)
                for i, (header, value) in enumerate(nxt.values):
                    value = re.sub(r"\s+\d$", "", value).strip()
                    metric = _metric(header, value, i)
                    shown = re.sub(r"\s*(APR|APY)", "", value).replace(" ", "") + (f" {metric}" if metric in ("APR", "APY") else "")
                    rows.append((snapshots[-1], nxt.page, metric,
                                 tuple(float(x) for x in re.findall(r"\d+(?:\.\d+)?", value)), shown))
                best = max(rows, key=trust)
        group = [r for r in rows if r[0] is best[0] and r[1] is best[1]]
        same_snap = [r for r in rows if r[0] is best[0]]
        winner = []
        for metric in dict.fromkeys(r[2] for r in group):
            # one value per metric; if the page itself disagrees, the value most pages show
            counts = Counter(r[3] for r in same_snap if r[2] == metric)
            winner.append(max((r for r in group if r[2] == metric), key=lambda r: counts[r[3]]))
        win_vals = {(r[2], r[3]) for r in winner}
        resolution = " / ".join(r[4] for r in winner)
        values = list(dict.fromkeys([r[4] for r in winner] +
                                    [r[4] for r in sorted(rows, key=lambda r: r[0].taken_on)]))
        current = [r for r in rows if r[0].taken_on == max(x[0].taken_on for x in rows)]
        stale_now = sorted({r[1].url.replace("https://www.dupaco.com", "") for r in current
                            if (r[2], r[3]) not in win_vals and any(r[2] == m for m, _ in win_vals)})
        if not stale_now and best[0] is not latest:
            # The row is gone from the current site and nothing still shows an old value: a past
            # rate change on a discontinued product, not a live contradiction.
            continue
        if stale_now:
            reason = (f"{best[1].url} ({best[0].taken_on}) is the most authoritative source and shows "
                      f"{resolution}; {', '.join(stale_now[:3])} still show{'s' if len(stale_now) == 1 else ''} "
                      f"older values in the latest snapshot ({current[0][0].taken_on}).")
        else:
            reason = f"The rate changed between snapshots; the newest trusted value is {resolution} ({best[1].url}, {best[0].taken_on})."
        hints = []
        if f.term_months:
            hints += [f"{f.term_months}-month", f"{f.term_months} month"]
            if f.term_months % 12 == 0:
                hints += [f"{f.term_months // 12}-year", f"{f.term_months // 12} year"]
        topic = f"{ident[0]} – {f.label}" + (f" ({', '.join(hints)})" if hints else "")
        srcs, seen = [], set()
        for snap, page, _, _, shown in winner + sorted(rows, key=lambda r: r[0].taken_on, reverse=True):
            if (page.url, shown) not in seen:
                seen.add((page.url, shown))
                srcs.append(Source(url=page.url, snapshot_id=snap.snapshot_id, quote=shown))
        key = frozenset((r[2], r[3]) for r in rows)
        if key in merged:
            # The same table repeated for another audience (business, IRA): one contradiction.
            merged[key].topic += f"; also {ident[0]}"
            continue
        merged[key] = Conflict(topic=topic, values=values, sources=srcs[:8], resolution=resolution, reason=reason)
        meta[key] = ((ident[0], f.term_months) if stale_now else (key,), pos)

    # A stale page is one contradiction per product and term: when several balance or model-year
    # tiers are contradicted by stale pages (calculator, promo, guide), keep the headline tier (the first row of
    # the current rate table) rather than reporting every tier separately.
    keep: Dict[Tuple, FrozenSet[Tuple[str, Tuple[float, ...]]]] = {}
    for key, (group, pos) in meta.items():
        if group not in keep or pos < meta[keep[group]][1]:
            keep[group] = key
    kept = set(keep.values())
    return [c for key, c in merged.items() if key in kept]


ORDINALS = ["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eighth", "ninth", "tenth"]


def _text_conflicts(snapshots: List[SnapshotIndex]) -> List[Conflict]:
    """Facts stated in prose that drift: the branch count (old pages keep the old number) and how
    many times Forbes has recognised Dupaco (each press release states its own count)."""
    out = []
    latest = snapshots[-1]
    # Branch count
    pat = re.compile(r"\b(\d{1,2})\s+(?:[\w’'-]+\s+){0,2}branch(?:es)?\b", re.I)
    seen: Dict[str, List[Tuple[SnapshotIndex, IndexedPage]]] = {}
    for snap in snapshots:
        for page in snap.pages:
            for line in page.lines:
                for m in pat.finditer(line):
                    seen.setdefault(m.group(1), []).append((snap, page))
    current = _answer_count(latest, "How many branches does Dupaco have?")
    win = re.search(r"say (\d+)", current.conflict_note or "") if current else None
    counts = {v: len(where) for v, where in seen.items() if len(where) >= 3}
    if win and len(counts) > 1:
        value = win.group(1)
        others = sorted((v for v in counts if v != value), key=lambda v: -counts[v])
        src = current.sources[0]
        out.append(Conflict(
            topic="Number of Dupaco branches (branch count, how many branches)",
            values=[f"{value} branches"] + [f"{v} branches" for v in others],
            sources=[src] + [Source(url=seen[v][-1][1].url, snapshot_id=seen[v][-1][0].snapshot_id,
                                    quote=f"{v} branches") for v in others[:5]],
            resolution=f"{value} branches",
            reason="The most recent dated statements give this count (the Hy-Vee branch closed on 2026-03-31); "
                   "older pages, bios and press releases still give earlier counts."))
    # Forbes recognition
    pat = re.compile(rf"\b({'|'.join(ORDINALS)}) time Forbes", re.I)
    found: Dict[str, Tuple[str, IndexedPage, SnapshotIndex]] = {}
    for snap in snapshots:
        for page in snap.pages:
            if "credit union" not in page.title.lower():     # not the "top small employer" award
                continue
            for m in pat.finditer(page.markdown):
                found[m.group(1).lower()] = (page.published or "", page, snap)
    if len(found) > 1:
        newest = max(found, key=lambda k: (found[k][0], ORDINALS.index(k)))
        order = [newest] + sorted((k for k in found if k != newest), key=lambda k: -ORDINALS.index(k))
        out.append(Conflict(
            topic="Forbes recognition: how many times Forbes named Dupaco a top / best-in-state credit union",
            values=[f"{k} time" for k in order],
            sources=[Source(url=found[k][1].url, snapshot_id=found[k][2].snapshot_id, quote=f"{k} time Forbes")
                     for k in order],
            resolution=f"{newest} time",
            reason=f"The newest press release ({found[newest][0] or 'latest'}) counts the {newest} time; "
                   "older releases give the count as of their own year."))
    return out


DOLLAR_NAME = re.compile(r"\b([A-Z][a-z]+)\$([a-z]{2,})\b")


class TemporalKnowledgeSystem:
    """
    Temporal & Contradiction Resolution Engine compatible with contract.py.
    """

    def __init__(self):
        # Snapshot indexes, kept sorted by taken_on (oldest first)
        self.snapshots: List[SnapshotIndex] = []
        # Brand names spelled with "$" ("Home$tart"), keyed by how people type them
        # ("homestart", "home start"), so the question uses the site's spelling.
        self.dollar_names: Dict[str, str] = {}

    def ingest(self, snapshot: Snapshot) -> None:
        """
        Ingest a snapshot (called in chronological order: oldest to newest).
        """
        self.snapshots.append(_index_snapshot(snapshot))
        for page in snapshot.pages:
            for a, b in DOLLAR_NAME.findall(page.markdown):
                self.dollar_names.setdefault(f"{a}s{b}".lower(), f"{a}${b}")
                self.dollar_names.setdefault(f"{a} s{b}".lower(), f"{a}${b}")
        self.snapshots.sort(key=lambda s: s.taken_on)

    def _select_snapshot(self, as_of: Optional[str] = None) -> Optional[SnapshotIndex]:
        """
        as_of=None -> newest snapshot. Otherwise the newest snapshot taken on or before as_of;
        if as_of predates every snapshot, fall back to the earliest one.
        """
        if not self.snapshots:
            return None
        if not as_of:
            return self.snapshots[-1]
        target = as_of.strip()[:10]     # ISO dates compare correctly as strings
        eligible = [s for s in self.snapshots if s.taken_on <= target]
        return eligible[-1] if eligible else self.snapshots[0]

    def answer(self, question: str, as_of: Optional[str] = None) -> Answer:
        """
        Answers a user question based on the valid snapshot state as of a date.
        """
        snap = self._select_snapshot(as_of)
        if snap is None:
            return Answer(text=REFUSAL_TEXT, confident=False)

        for typed, name in self.dollar_names.items():
            question = re.sub(rf"\b{re.escape(typed)}\b", name, question, flags=re.I)
        query = _parse_query(question)
        unknown = _unknown_names(snap, question)
        if unknown:
            # The question names something (a branch, product, person) the website never mentions.
            return Answer(text=REFUSAL_TEXT, confident=False,
                          conflict_note=f"No page mentions: {', '.join(sorted(unknown))}")
        for special in (_answer_hours, _answer_branch_address, _answer_count, _answer_fee):
            ans = special(snap, question)
            if ans is not None:
                return ans
        if query.words & LINK_WORDS or LINK_PHRASE.search(query.text):
            ans = _answer_link(snap, query)
            if ans is not None:
                return ans
        if query.wants_rate:
            ans = _answer_from_facts(snap, query)
            if ans is not None:
                return ans
            if query.words & DISCRIMINATORS:
                # A rate for a product the rate tables never list (e.g. construction loans).
                return Answer(text=REFUSAL_TEXT, confident=False)
        ans = self._answer_from_text(snap, question)
        if ans.confident and _is_price_question(question) and not query.wants_rate \
                and not PRICE_TEXT.search(ans.text):
            # A fee/price question the fee schedule can't answer, and the best passage names no
            # price either: say so rather than return an unrelated paragraph.
            return Answer(text=REFUSAL_TEXT, confident=False)
        if ans.confident and query.words & STRICT_RATE_WORDS and not RATE_PATTERN.search(ans.text):
            # Asked for a rate no table lists (e.g. a special that didn't exist yet on that date)
            # and the best passage has no rate in it either.
            return Answer(text=REFUSAL_TEXT, confident=False)
        return ans

    def _answer_from_text(self, snap: SnapshotIndex, question: str) -> Answer:
        ranked = _search_passages(snap, question)
        if not ranked:
            return Answer(text=REFUSAL_TEXT, confident=False)
        passage = ranked[0][1]
        return Answer(text=passage.extended(), confident=True,
                      sources=[Source(url=passage.page.url, snapshot_id=snap.snapshot_id,
                                      quote=passage.text[:200])])

    def conflicts(self) -> List[Conflict]:
        """
        Every place the website contradicts itself: the same rate-table row (product, tier, metric)
        showing different values on different pages or in different snapshots. The winner is the
        most authoritative page in the newest snapshot that still lists the row.
        """
        if not self.snapshots:
            return []
        return _rate_conflicts(self.snapshots) + _text_conflicts(self.snapshots)


def build() -> TemporalKnowledgeSystem:
    """Entry point required by the harness."""
    return TemporalKnowledgeSystem()
