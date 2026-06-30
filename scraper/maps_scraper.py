import asyncio
import queue
import random
import threading
from dataclasses import dataclass, field
from urllib.parse import quote, parse_qs, urlparse

from playwright.async_api import async_playwright, BrowserContext, Page

from .website_checker import (
    WebsiteChecker,
    CheckResult,
    STATUS_NO_WEBSITE,
    STATUS_OUTDATED,
)


@dataclass
class ScraperConfig:
    postcodes: list[str]
    filter_no_website: bool
    filter_outdated: bool
    threshold_year: int
    max_results_per_postcode: int


@dataclass
class BusinessResult:
    name: str
    address: str
    phone: str
    website: str
    website_status: str
    last_evidence_date: str
    method_used: str
    rating: str
    postcode: str

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "address": self.address,
            "phone": self.phone,
            "website": self.website,
            "website_status": self.website_status,
            "last_evidence_date": self.last_evidence_date,
            "method_used": self.method_used,
            "rating": self.rating,
            "postcode": self.postcode,
        }


_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class MapsScraper:
    def __init__(
        self,
        config: ScraperConfig,
        result_queue: queue.Queue,
        stop_event: threading.Event,
    ) -> None:
        self._config = config
        self._q = result_queue
        self._stop = stop_event
        self._checker = WebsiteChecker(threshold_year=config.threshold_year)
        self._total = len(config.postcodes)

    def _put(self, msg: dict) -> None:
        self._q.put(msg)

    async def scrape(self) -> None:
        self._put({"type": "status", "message": "Launching browser..."})
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                ],
            )
            context = await browser.new_context(
                viewport={"width": 1280, "height": 800},
                user_agent=_USER_AGENT,
            )
            await context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
            )
            try:
                consent_done = False
                for idx, postcode in enumerate(self._config.postcodes):
                    if self._stop.is_set():
                        break
                    consent_done = await self._scrape_postcode(
                        context, postcode, idx, consent_done
                    )
                    if idx < self._total - 1 and not self._stop.is_set():
                        await asyncio.sleep(random.uniform(1.5, 3.0))
            finally:
                await self._checker.close()
                await browser.close()

        if self._stop.is_set():
            self._put({"type": "status", "message": "Stopped by user."})

    async def _scrape_postcode(
        self,
        context: BrowserContext,
        postcode: str,
        idx: int,
        consent_done: bool,
    ) -> bool:
        self._put({
            "type": "status",
            "message": f"Searching: businesses in {postcode} ({idx + 1}/{self._total})",
        })
        self._put({"type": "progress", "value": idx / self._total})

        search_term = quote(f"businesses in {postcode}", safe="")
        url = f"https://www.google.com/maps/search/{search_term}"

        page = await context.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30_000)

            if not consent_done:
                consent_done = await self._handle_consent(page)

            await asyncio.sleep(random.uniform(1.5, 3.0))

            if await self._is_no_results(page):
                self._put({
                    "type": "status",
                    "message": f"No results for {postcode}, skipping.",
                })
                return consent_done

            if "/maps/place/" in page.url:
                raw = await self._extract_business_detail(page)
                if raw:
                    await self._process_and_emit([raw], postcode)
            else:
                try:
                    await page.wait_for_selector('div[role="feed"]', timeout=15_000)
                    place_urls = await self._collect_place_urls(page)
                    raw_list = await self._visit_places(context, place_urls, postcode)
                    await self._process_and_emit(raw_list, postcode)
                except Exception:
                    self._put({
                        "type": "error",
                        "message": f"Could not load results list for {postcode}.",
                    })
        except Exception as exc:
            self._put({"type": "error", "message": f"Error on {postcode}: {exc}"})
        finally:
            await page.close()

        return consent_done

    async def _handle_consent(self, page: Page) -> bool:
        for selector in [
            'button[aria-label="Accept all"]',
            "#L2AGLb",
            'form[action*="consent"] button[type="submit"]',
        ]:
            try:
                await page.click(selector, timeout=3_000)
                await page.wait_for_url("*maps.google.com*", timeout=10_000)
                return True
            except Exception:
                continue
        return False

    async def _is_no_results(self, page: Page) -> bool:
        for text in ["couldn't find", "can't find", "No results"]:
            try:
                if await page.locator(f':has-text("{text}")').count() > 0:
                    return True
            except Exception:
                pass
        return False

    async def _collect_place_urls(self, page: Page) -> list[str]:
        # Dedup by full href to avoid merging two different places that share a slug
        collected: dict[str, str] = {}  # full href → stripped nav URL
        max_rounds = min(20, (self._config.max_results_per_postcode // 5) + 5)
        feed_selector = 'div[role="feed"]'

        for _ in range(max_rounds):
            if self._stop.is_set():
                break

            links = await page.query_selector_all('a[href*="/maps/place/"]')
            prev_count = len(collected)
            for link in links:
                href = await link.get_attribute("href")
                if href and href not in collected:
                    collected[href] = href.split("?")[0]

            if len(collected) >= self._config.max_results_per_postcode:
                break

            try:
                end_el = await page.query_selector('span[class*="HlvSq"]')
                if end_el:
                    break
            except Exception:
                pass

            try:
                await page.eval_on_selector(feed_selector, "el => el.scrollBy(0, 800)")
                # Wait up to 2.5 s for new cards to appear rather than a fixed sleep
                for _ in range(5):
                    await asyncio.sleep(0.5)
                    new_links = await page.query_selector_all('a[href*="/maps/place/"]')
                    if len(new_links) > prev_count:
                        break
            except Exception:
                break

        return list(collected.values())[: self._config.max_results_per_postcode]

    async def _visit_places(
        self, context: BrowserContext, urls: list[str], postcode: str
    ) -> list[dict]:
        sem = asyncio.Semaphore(3)

        async def visit_one(url: str) -> dict | None:
            if self._stop.is_set():
                return None
            async with sem:
                page = await context.new_page()
                try:
                    await page.goto(url, wait_until="domcontentloaded", timeout=20_000)
                    await asyncio.sleep(random.uniform(0.6, 1.2))

                    if "sorry" in page.url or "captcha" in page.url.lower():
                        self._put({
                            "type": "status",
                            "message": "CAPTCHA detected. Pausing 30s...",
                        })
                        await asyncio.sleep(30)
                        await page.goto(url, wait_until="domcontentloaded", timeout=20_000)

                    return await self._extract_business_detail(page)
                except Exception:
                    return None
                finally:
                    await page.close()

        results = await asyncio.gather(*[visit_one(u) for u in urls], return_exceptions=True)
        return [r for r in results if r and not isinstance(r, Exception)]

    async def _extract_business_detail(self, page: Page) -> dict | None:
        try:
            await page.wait_for_selector("h1", timeout=8_000)
        except Exception:
            return None

        name = await self._safe_text(
            page,
            'h1[class*="DUwDvf"]',
            'h1[class*="fontHeadlineLarge"]',
            "h1",
        )
        if not name:
            return None

        address = await self._safe_text(
            page,
            'button[data-item-id="address"] .rogA2c',
            'button[data-item-id="address"] [class*="fontBodyMedium"]',
            '[aria-label^="Address:"]',
        )

        phone = ""
        try:
            el = await page.query_selector('button[data-item-id^="phone:tel:"]')
            if el:
                item_id = await el.get_attribute("data-item-id") or ""
                phone = item_id.replace("phone:tel:", "")
            else:
                el = await page.query_selector('[aria-label^="Phone:"]')
                if el:
                    label = await el.get_attribute("aria-label") or ""
                    phone = label.replace("Phone:", "").strip()
        except Exception:
            pass

        website = ""
        try:
            el = await page.query_selector('a[data-item-id="authority"]')
            if el:
                href = await el.get_attribute("href") or ""
                website = self._clean_google_redirect(href)
            else:
                el = await page.query_selector('a[aria-label*="website" i]')
                if el:
                    href = await el.get_attribute("href") or ""
                    website = self._clean_google_redirect(href)
        except Exception:
            pass

        rating = await self._safe_text(
            page,
            'div.F7nice span[aria-hidden="true"]',
            "span.MW4etd",
        )

        return {
            "name": name,
            "address": address,
            "phone": phone,
            "website": website,
            "rating": rating,
        }

    async def _process_and_emit(self, raw_list: list[dict], postcode: str) -> None:
        if not raw_list:
            return

        sem = asyncio.Semaphore(5)

        async def check_one(raw: dict) -> CheckResult:
            async with sem:
                return await self._checker.check(raw.get("website") or None)

        check_results = await asyncio.gather(
            *[check_one(r) for r in raw_list], return_exceptions=True
        )

        for raw, check in zip(raw_list, check_results):
            if isinstance(check, Exception):
                continue

            status = check.status

            include = (
                (status == STATUS_NO_WEBSITE and self._config.filter_no_website)
                or (status == STATUS_OUTDATED and self._config.filter_outdated)
            )
            if not include:
                continue

            result = BusinessResult(
                name=raw["name"],
                address=raw.get("address", ""),
                phone=raw.get("phone", ""),
                website=raw.get("website", ""),
                website_status=status,
                last_evidence_date=check.last_evidence_date,
                method_used=check.method_used,
                rating=raw.get("rating", ""),
                postcode=postcode,
            )
            self._put({"type": "result", "data": result.to_dict()})

    async def _safe_text(self, page: Page, *selectors: str) -> str:
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    text = await el.text_content()
                    if text and text.strip():
                        return text.strip()
            except Exception:
                continue
        return ""

    def _clean_google_redirect(self, href: str) -> str:
        if "google.com/maps" in href and "url=" in href:
            try:
                return parse_qs(urlparse(href).query).get("url", [href])[0]
            except Exception:
                pass
        return href
