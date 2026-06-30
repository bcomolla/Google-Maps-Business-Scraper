import asyncio
import re
import email.utils
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

STATUS_NO_WEBSITE = "No Website"
STATUS_OUTDATED = "Outdated"
STATUS_OK = "OK"
STATUS_UNKNOWN = "Unknown"

_WAYBACK_SEMAPHORE: asyncio.Semaphore | None = None

# Matches: © 1998-2026, © 2026, Copyright 2026, (c) 2026
# Group 1 = optional start year of a range, Group 2 = the main / end year
_COPYRIGHT_RE = re.compile(
    r"(?:©|&copy;|copyright|\(c\))"
    r"\s*(?:[\w\s,&.'-]{0,40}?)"
    r"\s*(?:(\d{4})\s*[-–—]\s*)?"   # optional range start
    r"(\d{4})",                       # main / end year
    re.IGNORECASE,
)

# Meta tag names that carry a last-modified / publication date
_DATE_META_NAMES = re.compile(
    r"^(last[-_]?modified|revised|date|DC\.date\.modified|article:modified_time)$",
    re.IGNORECASE,
)

# HTML4 / XHTML doctypes — presence means the page is almost certainly pre-2010 design
_OLD_DOCTYPE_RE = re.compile(
    r"<!DOCTYPE\s+HTML\s+PUBLIC\s+[\"']-//W3C//DTD",
    re.IGNORECASE,
)


def _get_wayback_semaphore() -> asyncio.Semaphore:
    global _WAYBACK_SEMAPHORE
    if _WAYBACK_SEMAPHORE is None:
        _WAYBACK_SEMAPHORE = asyncio.Semaphore(3)
    return _WAYBACK_SEMAPHORE


@dataclass
class CheckResult:
    status: str
    last_evidence_date: str
    method_used: str


class WebsiteChecker:
    def __init__(self, threshold_year: int, timeout_seconds: int = 8) -> None:
        self.threshold_year = threshold_year
        self.timeout = timeout_seconds
        self._cache: dict[str, CheckResult] = {}
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            },
        )

    # ------------------------------------------------------------------ #
    #  Public entry point                                                  #
    # ------------------------------------------------------------------ #

    async def check(self, url: str | None) -> CheckResult:
        if not url or not url.strip():
            return CheckResult(STATUS_NO_WEBSITE, "", "")

        url = url.strip()
        if not url.startswith(("http://", "https://")):
            url = "https://" + url

        domain = self._extract_domain(url)

        if domain in self._cache:
            return self._cache[domain]

        # Primary: inspect the live website
        result = await self._check_live_site(url)

        # Fallback: Wayback Machine *latest* snapshot (handles sites that won't load)
        if result is None:
            result = await self._check_wayback_latest(domain)

        final = result if result is not None else CheckResult(STATUS_UNKNOWN, "", "none")
        self._cache[domain] = final
        return final

    # ------------------------------------------------------------------ #
    #  Live site inspection                                                #
    # ------------------------------------------------------------------ #

    async def _check_live_site(
        self, url: str
    ) -> CheckResult | None:
        # --- 1. HEAD request: fast Last-Modified header check ---
        try:
            head = await self._http.head(url)
            result = self._year_result_from_header(head)
            if result is not None:
                return result
        except Exception:
            pass

        # --- 2. Full GET + HTML parse ---
        try:
            resp = await self._http.get(url)
        except Exception:
            return None

        html = resp.text
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            return None

        # 2a. Copyright year scan (most reliable "last maintained" signal)
        result = self._check_copyright_year(soup)
        if result is not None:
            return result

        # 2b. Meta date tags
        result = self._check_meta_dates(soup)
        if result is not None:
            return result

        # 2c. Last-Modified from GET response headers
        result = self._year_result_from_header(resp)
        if result is not None:
            return result

        # 2d. Structural era signals (weaker — used only as a last live-site signal)
        result = self._check_structural_signals(soup, html)
        if result is not None:
            return result

        return None

    # ------------------------------------------------------------------ #
    #  Copyright year                                                      #
    # ------------------------------------------------------------------ #

    def _check_copyright_year(self, soup: BeautifulSoup) -> CheckResult | None:
        """
        Scan footer → meta copyright → full page text for copyright years.
        Uses the MOST RECENT year found (max), so "© 1998–2026" correctly
        returns 2026, not 1998.
        """
        candidates: list[str] = []

        footer = soup.find("footer")
        if footer:
            candidates.append(footer.get_text(" ", strip=True))

        meta = soup.find("meta", attrs={"name": re.compile(r"copyright", re.I)})
        if meta and meta.get("content"):
            candidates.append(str(meta["content"]))

        # Full page text last (broadest, most noise)
        candidates.append(soup.get_text(" ", strip=True))

        years: list[int] = []
        for text in candidates:
            for m in _COPYRIGHT_RE.finditer(text):
                # group(2) is the end/main year; group(1) is optional range start
                for grp in (m.group(2), m.group(1)):
                    if grp:
                        y = int(grp)
                        if 1990 <= y <= 2100:
                            years.append(y)

        if not years:
            return None

        # The most recent copyright year is the best "last maintained" signal
        latest = max(years)
        if latest < self.threshold_year:
            return CheckResult(STATUS_OUTDATED, str(latest), "HTML copyright year")
        return CheckResult(STATUS_OK, str(latest), "HTML copyright year")

    # ------------------------------------------------------------------ #
    #  Meta date tags                                                      #
    # ------------------------------------------------------------------ #

    def _check_meta_dates(self, soup: BeautifulSoup) -> CheckResult | None:
        """Check <meta name="last-modified">, <meta name="revised">, etc."""
        for tag in soup.find_all("meta"):
            name = tag.get("name", "") or tag.get("property", "")
            if not _DATE_META_NAMES.match(str(name)):
                continue
            content = tag.get("content", "")
            year = self._extract_year_from_string(str(content))
            if year:
                if year < self.threshold_year:
                    return CheckResult(STATUS_OUTDATED, str(year), f"meta:{name}")
                return CheckResult(STATUS_OK, str(year), f"meta:{name}")
        return None

    # ------------------------------------------------------------------ #
    #  HTTP Last-Modified header                                           #
    # ------------------------------------------------------------------ #

    def _year_result_from_header(self, resp: httpx.Response) -> CheckResult | None:
        lm = resp.headers.get("last-modified")
        if not lm:
            return None
        try:
            dt = email.utils.parsedate_to_datetime(lm)
            year = dt.year
            date_str = dt.date().isoformat()
            if year < self.threshold_year:
                return CheckResult(STATUS_OUTDATED, date_str, "Last-Modified header")
            return CheckResult(STATUS_OK, date_str, "Last-Modified header")
        except Exception:
            return None

    # ------------------------------------------------------------------ #
    #  Structural era signals                                              #
    # ------------------------------------------------------------------ #

    def _check_structural_signals(
        self, soup: BeautifulSoup, raw_html: str
    ) -> CheckResult | None:
        """
        Weak but useful signals when no date is present.

        - Missing <meta name="viewport">  → site was built before mobile-first
          design became standard (~2011). Very few post-2012 sites omit this.
        - HTML4 / XHTML DOCTYPE            → almost never used in sites built
          after 2010; signals an old code-base.

        These return Outdated with the signal name as the evidence date so the
        user knows it is an inferred classification, not an exact date.
        """
        # HTML4 / XHTML DOCTYPE
        if _OLD_DOCTYPE_RE.search(raw_html[:500]):
            return CheckResult(STATUS_OUTDATED, "HTML4/XHTML doctype", "Structural signal")

        # No viewport meta tag
        viewport = soup.find("meta", attrs={"name": re.compile(r"^viewport$", re.I)})
        if viewport is None:
            return CheckResult(STATUS_OUTDATED, "No viewport meta tag", "Structural signal")

        return None

    # ------------------------------------------------------------------ #
    #  Wayback Machine — latest snapshot (fallback only)                  #
    # ------------------------------------------------------------------ #

    async def _check_wayback_latest(self, domain: str) -> CheckResult | None:
        """
        Used ONLY when the live site cannot be reached or gave no signals.
        Queries for the MOST RECENT successful snapshot (not the earliest).
        If the site hasn't been archived recently, it may be defunct.
        """
        sem = _get_wayback_semaphore()
        async with sem:
            try:
                url = (
                    f"http://web.archive.org/cdx/search/cdx"
                    f"?url={domain}&output=json&limit=1&fl=timestamp"
                    f"&filter=statuscode:200&from=19960101&fastLatest=true"
                )
                resp = await self._http.get(url)
                if resp.status_code != 200:
                    return None
                data = resp.json()
                if not data or len(data) < 2:
                    return None
                timestamp = data[1][0]
                year = int(timestamp[:4])
                month = timestamp[4:6]
                day = timestamp[6:8]
                date_str = f"{year}-{month}-{day}"
                if year < self.threshold_year:
                    return CheckResult(STATUS_OUTDATED, date_str, "Wayback Machine (latest)")
                return CheckResult(STATUS_OK, date_str, "Wayback Machine (latest)")
            except Exception:
                return None

    # ------------------------------------------------------------------ #
    #  Helpers                                                             #
    # ------------------------------------------------------------------ #

    def _extract_year_from_string(self, text: str) -> int | None:
        """Pull the first plausible 4-digit year out of a date string."""
        m = re.search(r"(\d{4})", text)
        if m:
            y = int(m.group(1))
            if 1990 <= y <= 2100:
                return y
        return None

    def _extract_domain(self, url: str) -> str:
        netloc = urlparse(url).netloc
        return netloc.removeprefix("www.")

    async def close(self) -> None:
        await self._http.aclose()
