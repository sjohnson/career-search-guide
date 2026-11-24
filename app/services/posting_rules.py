"""Relevance rules for gathered postings: one decision, used at ingest and read.

`rejection_reason` runs before an Adzuna result is stored, and again whenever
stored postings are read (panel, export), so a tightened rule also hides
postings saved earlier. Rejected results are not stored; they are counted per
rule on the fetch log. Because Adzuna returns live postings on every refresh,
a loosened rule brings matching postings back on the next refresh.

These are deterministic hard rules. Judging fit is ai-job-search's `/rank`.

Default term lists come from ai-job-search (job_scraper/adzuna-exclusion-
terms.md, drafted 2026-11-21). Where each list is matched matters more than
the words: employer names must never be matched against a description, which
often names other companies as partners or clearinghouses.

The lists live in `adzuna_settings` (editable in the UI). New settings rows
are seeded from `default_rule_lists()`: the code defaults below, with any list
defined in the gitignored local file (POSTING_RULES_FILE, default
posting_rules.local.toml) replacing its default. Personal entries go there,
like secrets in `.env`. See posting_rules.example.toml.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from app import config
from app.models import AdzunaSettings, RemoteStatus

# --- Default term lists (seeded into adzuna_settings; editable in the UI) ----

# Employer name only. Personal entries (non-competes, employers you won't
# work for) belong in posting_rules.local.toml, never here: this repo is public.
DEFAULT_COMPANY_BLOCKLIST = [
    # Gambling operators
    "DraftKings",
    "FanDuel",
    "PrizePicks",
    "Underdog",
]

# Title or employer name: industries that are non-starters.
DEFAULT_INDUSTRY_EXCLUDE = [
    "casino",
    "sportsbook",
    "betting",
    "wagering",
    "gambling",
    "igaming",
    "fantasy sports",
    "bookmaker",
    "lottery",
    "payday",
    "title loan",
    "cash advance",
    "debt collection",
    "debt collector",
    "collections agency",
    "bail bond",
    "rent-to-own",
    "lead generation",
]

# Title only, always drops.
DEFAULT_TITLE_EXCLUDE = [
    # Management and seniority
    "manager",
    "director",
    "vice president",
    "VP",
    "head of",
    "chief",
    "CTO",
    # Too junior
    "intern",
    "internship",
    "junior",
    "entry level",
    "new grad",
    "graduate",
    "apprentice",
    # Wrong discipline
    "frontend",
    "front end",
    "front-end",
    "DevOps",
    "SRE",
    "site reliability",
    "security engineer",
    "cybersecurity",
    "QA",
    "SDET",
    "test automation",
    "data scientist",
    "machine learning",
    "ML engineer",
    "research scientist",
    "computer vision",
    "NLP",
    "solutions architect",
    "sales engineer",
    "support engineer",
    "technical writer",
    "designer",
    "data analyst",
    "business analyst",
    "recruiter",
    "pre-sales",
    # Travel
    "relocate",
    "relocation",
]

# Title only, drops unless the title also names a stack in TITLE_STACK_RESCUE
# ("Ruby or C# Engineer" stays). Never matched against the description, where
# polyglot lists like "Ruby, Python, Java, or C#" are normal.
DEFAULT_TITLE_STACK_EXCLUDE = [
    ".NET",
    "dotnet",
    "C#",
    "ASP.NET",
    "Rust",
    "Laravel",
    "Drupal",
    "Salesforce",
    "Apex",
    "SAP",
    "ABAP",
    "PL/SQL",
    "COBOL",
    "mainframe",
    "Scala",
    "C++",
    "embedded",
    "firmware",
    "FPGA",
    "iOS",
    "Android",
    "Swift",
    "Kotlin",
    "Flutter",
    "React Native",
    "Unity",
    "Unreal",
    "game developer",
    "gameplay",
]

TITLE_STACK_RESCUE = ("ruby", "rails", "python", "javascript")

# Title only: the title must contain at least one of these, or the posting is
# dropped. Catches non-software roles whose full text happens to mention Ruby
# ("Field Service Technician", "Penetration Tester"). Blank turns it off.
DEFAULT_TITLE_REQUIRE = [
    "engineer",
    "engineering",
    "developer",
    "programmer",
    "software",
    "architect",
    "SWE",
    "SDE",
]

# Title or description: never drop, shown as tags for review. "Golang", not
# "Go", which would match the verb.
DEFAULT_SIGNAL_TERMS = [
    "C#",
    "Java",
    "PHP",
    "Golang",
    "Python",
    "TypeScript",
    "React",
    "on-call",
    "rotation",
    "security clearance",
    "TS/SCI",
    "HIPAA",
    "claims",
    "revenue cycle",
    "10+ years",
    "people management",
    "direct reports",
]


# adzuna_settings column -> code default.
RULE_LISTS = {
    "company_blocklist": DEFAULT_COMPANY_BLOCKLIST,
    "industry_exclude": DEFAULT_INDUSTRY_EXCLUDE,
    "title_exclude": DEFAULT_TITLE_EXCLUDE,
    "title_require": DEFAULT_TITLE_REQUIRE,
    "title_stack_exclude": DEFAULT_TITLE_STACK_EXCLUDE,
    "signal_terms": DEFAULT_SIGNAL_TERMS,
}


def default_rule_lists(path: str | Path | None = None) -> dict[str, list[str]]:
    """The code defaults, with each list the local file defines replacing
    its default (an empty list in the file turns that list off). A missing
    file means code defaults only; a malformed one raises ValueError rather
    than silently seeding the wrong rules."""
    lists = {name: list(terms) for name, terms in RULE_LISTS.items()}
    path = Path(path or config.POSTING_RULES_FILE)
    if not path.is_file():
        return lists
    try:
        local = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"{path}: {exc}") from exc
    unknown = set(local) - set(RULE_LISTS)
    if unknown:
        raise ValueError(f"{path}: unknown list(s) {sorted(unknown)}; expected some of {sorted(RULE_LISTS)}")
    for name, terms in local.items():
        if not isinstance(terms, list) or not all(isinstance(t, str) for t in terms):
            raise ValueError(f"{path}: {name} must be a list of strings")
        lists[name] = [t.strip() for t in terms if t.strip()]
    return lists


# --- Matching ----------------------------------------------------------------


def parse_lines(text: str | None) -> list[str]:
    """One entry per line (commas also accepted), trimmed, blanks dropped."""
    items = re.split(r"[\n,]", text or "")
    return [item.strip() for item in items if item.strip()]


@lru_cache(maxsize=2048)
def _term_pattern(term: str) -> re.Pattern:
    """Whole-word, case-insensitive. Letters, digits, "+" and "#" next to the
    term block a match, so "Java" misses "JavaScript", "intern" misses
    "internal" and "C" misses "C++"; punctuation inside a term ("C#", ".NET")
    is literal. Runs of whitespace in the term match any whitespace."""
    words = [re.escape(word) for word in term.split()]
    edge = "A-Za-z0-9+#"
    return re.compile(rf"(?<![{edge}])(?:{r'\s+'.join(words)})(?![{edge}])", re.IGNORECASE)


def find_term(terms: Iterable[str], text: str) -> str | None:
    """The first term that appears in `text` as a whole word, or None."""
    if not text:
        return None
    for term in terms:
        if _term_pattern(term).search(text):
            return term
    return None


# --- Location ----------------------------------------------------------------

_REMOTE_WORDS = ("remote", "remotely", "work from home", "wfh", "telecommute", "telecommuting", "distributed")
_ON_SITE_WORDS = ("on-site", "onsite", "on site", "in office", "in-office", "hybrid")


def infer_remote_status(title: str, description: str, location: str) -> str | None:
    """Remote status as stated in the text. A bare city is not evidence of
    on-site work (remote postings list the employer's city too), so with no
    stated arrangement this returns None (unknown)."""
    text = f"{title} {description} {location}"
    if find_term(("hybrid",), text):
        return RemoteStatus.HYBRID.value
    if find_term(_REMOTE_WORDS, text):
        return RemoteStatus.REMOTE.value
    if find_term(_ON_SITE_WORDS, text):
        return RemoteStatus.ON_SITE.value
    return None


# The DC metro: DC itself plus Northern Virginia's inner counties and cities.
# Adzuna names places "City, County" (the state comes from `location.area`),
# so counties are the reliable marker. Maryland is outside every allowed
# region, so its DC suburbs need no list.
_DC_METRO_MARKERS = (
    "district of columbia",
    "washington, dc",
    "washington dc",
    ", dc",
    "arlington county",
    "fairfax",
    "alexandria",
    "falls church",
    "loudoun",
    "prince william",
    "manassas",
)


def is_dc_area(location: str) -> bool:
    loc = (location or "").lower()
    return loc.strip() == "washington" or any(m in loc for m in _DC_METRO_MARKERS)


def is_vague_location(location: str) -> bool:
    return (location or "").strip().lower() in ("", "us", "usa", "united states")


_SLC_MARKERS = (
    "salt lake",
    "slc",
    "provo",
    "lehi",
    "draper",
    "sandy",
    "murray",
    "orem",
    "west valley",
    "south jordan",
    "herriman",
    "american fork",
    "pleasant grove",
    "layton",
    "bountiful",
    "utah",
)
_CHARLOTTE_MARKERS = (
    "charlotte",
    "fort mill",
    "rock hill",
    "concord",
    "gastonia",
    "huntersville",
    "matthews",
    "pineville",
    "indian trail",
    "mooresville",
)


def _is_virginia(location: str) -> bool:
    loc = location.lower()
    return "virginia" in loc or ", va" in loc or loc.endswith(" va") or " va," in loc


def in_allowed_region(location: str) -> bool:
    """SLC metro, Virginia outside the DC metro, or Charlotte metro."""
    loc = (location or "").lower()
    if any(m in loc for m in _SLC_MARKERS) or any(m in loc for m in _CHARLOTTE_MARKERS):
        return True
    return _is_virginia(location or "") and not is_dc_area(location or "")


def location_rejection(location: str, remote_status: str | None, buckets: Iterable[str]) -> str | None:
    """Keep anything inside the allowed regions, anything stated as remote,
    and anything found by the remote search that states no arrangement
    (Adzuna matched "remote" somewhere in the full posting). Reject what's
    left: on-site or hybrid stated outside the regions, or a metro-search
    result outside the regions with nothing said about remote. The metro
    searches use a radius, so they do reach outside: "Virginia" within 50
    miles returns Maryland and the DC suburbs."""
    if is_vague_location(location) or in_allowed_region(location):
        return None
    if remote_status == RemoteStatus.REMOTE.value:
        return None
    if remote_status is None and "remote" in set(buckets):
        return None
    return remote_status or "not stated as remote"


# --- The decision ------------------------------------------------------------


@dataclass(frozen=True)
class Rejection:
    rule: str  # company | industry | title | require | stack | location
    term: str


RULE_LABELS = {
    "company": "blocked company",
    "industry": "industry",
    "title": "title",
    "stack": "title stack",
    "require": "title missing a required word",
    "location": "location",
}


@dataclass
class PostingRules:
    blocked_companies: list[str]
    industry_terms: list[str]
    title_terms: list[str]
    stack_terms: list[str]
    signal_terms: list[str]
    required_title_terms: list[str] = field(default_factory=list)

    @classmethod
    def from_settings(cls, settings: AdzunaSettings) -> "PostingRules":
        return cls(
            blocked_companies=parse_lines(settings.company_blocklist),
            industry_terms=parse_lines(settings.industry_exclude),
            title_terms=parse_lines(settings.title_exclude),
            stack_terms=parse_lines(settings.title_stack_exclude),
            signal_terms=parse_lines(settings.signal_terms),
            required_title_terms=parse_lines(settings.title_require),
        )

    def rejection_reason(
        self,
        *,
        title: str,
        company: str,
        location: str | None,
        remote_status: str | None,
        buckets: Iterable[str],
    ) -> Rejection | None:
        title = title or ""
        company = company or ""
        # Whole words within the name: "Globex" also blocks "Globex Health".
        term = find_term(self.blocked_companies, company)
        if term:
            return Rejection("company", term)
        term = find_term(self.industry_terms, title) or find_term(self.industry_terms, company)
        if term:
            return Rejection("industry", term)
        term = find_term(self.title_terms, title)
        if term:
            return Rejection("title", term)
        if self.required_title_terms and not find_term(self.required_title_terms, title):
            return Rejection("require", "none of the required words")
        term = find_term(self.stack_terms, title)
        if term and not find_term(TITLE_STACK_RESCUE, title):
            return Rejection("stack", term)
        verdict = location_rejection(location or "", remote_status, buckets)
        if verdict:
            return Rejection("location", f"{verdict.replace('_', '-')}, outside your regions")
        return None

    def signals(self, title: str, description: str | None) -> list[str]:
        """Signal terms present in the title or description snippet. Tags
        for review; they never decide anything."""
        text = f"{title or ''}\n{description or ''}"
        return [term for term in self.signal_terms if _term_pattern(term).search(text)]
