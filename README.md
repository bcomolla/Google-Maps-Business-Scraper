# Google Maps Business Scraper

A desktop application that searches Google Maps for businesses with no web presence or an outdated website, and exports the results to a formatted Excel spreadsheet ready for outreach.

**Platform:** Windows &nbsp;|&nbsp; **Python:** 3.10+ &nbsp;|&nbsp; **Launch:** `pythonw launch.pyw`

---

## Overview

The Google Maps Business Scraper is a lead-generation tool aimed at web designers and developers. It automates the process of finding local businesses that either have **no website at all** or have a website that was last active **before a configurable year** (default: 2010). These businesses are prime candidates for a new website pitch.

The scraper uses a real Chromium browser behind the scenes — it behaves like a human browsing Google Maps, not a traditional web crawler. No API keys or paid subscriptions are required.

---

## Installation

> Python 3.10 or later is required. Check your version with `python --version`.

**1. Install Python dependencies**

```bash
pip install -r requirements.txt
```

**2. Install the Chromium browser**

Playwright needs to download a bundled Chromium. Run this once:

```bash
playwright install chromium
```

**3. Launch the application**

Double-click `launch.pyw`, or run from a terminal:

```bash
python main.py
```

### Dependencies

| Package | Purpose |
|---|---|
| `customtkinter` | Modern themed GUI framework |
| `playwright` | Headless Chromium browser automation |
| `httpx` | Async HTTP client for website checks |
| `beautifulsoup4` + `lxml` | HTML parsing for copyright year scan |
| `openpyxl` | Excel file creation and formatting |

---

## Quick Start

1. **Open the application** — double-click `launch.pyw`. No terminal window will appear.
2. **Enter a postcode** — type a UK postcode in the *Postcodes* box (e.g. `EC1A 1BB`). Multiple postcodes can be separated by commas or new lines.
3. **Choose your filters** — tick *No website* and/or *Outdated website* to select what to look for.
4. **Click Start Scraping** — results populate the table in real time, colour-coded by status.
5. **Export to Excel** — once the scan finishes, click *Export to Excel* and choose a save location.

---

## Application Interface

### Left sidebar — Search Filters

| Control | Description |
|---|---|
| **Postcodes** | One or more UK postcodes, comma or newline separated. Automatically uppercased and deduplicated. |
| **No website** checkbox | Includes businesses with no website listed on Google Maps. |
| **Outdated website** checkbox | Includes businesses whose website shows evidence of being created before the threshold year. |
| **Outdated before** | Year cutoff for the outdated check. Defaults to 2010. |
| **Max results / postcode** | Limits businesses fetched per postcode. Defaults to 20. |
| **Start Scraping** | Begins the scrape. All controls are disabled while running. |
| **Stop** | Signals the scraper to stop cleanly after the current business finishes. |
| **Clear** | Clears the results table and resets the progress bar. Only active when not scraping. |

### Results table

The table populates in real time as each business is processed. Column headers can be **clicked to sort** (ascending/descending) and **dragged to resize**.

---

## Filter Options

**No website** — businesses are included if Google Maps shows no website link in their listing. The most straightforward filter — the business has no web presence at all.

**Outdated website** — businesses are included if the scraper determines their website was created or last significantly updated before the *Outdated before* year.

Both filters can be active at the same time. Businesses whose website appears modern (post-threshold) are silently excluded.

### Choosing the right threshold year

The default of **2010** targets websites that are 15+ years old — typically built before responsive design, mobile-first layouts, and modern security standards. Raising it (e.g. to 2016) catches more businesses at the cost of occasionally flagging functional but dated sites.

---

## Reading the Results

### Row colour coding

| Colour | Status | Meaning |
|---|---|---|
| Red | No Website | No website URL on the Google Maps listing. |
| Orange | Outdated | A website was found but evidence suggests it predates the threshold year. |
| Green | OK | The website appears modern. Filtered out by default. |
| Grey | Unknown | A website was found but no reliable age signal could be determined. |

### Column reference

| Column | Description |
|---|---|
| **#** | Row number in order of discovery. |
| **Business Name** | Name as listed on Google Maps. |
| **Address** | Full street address from the listing. |
| **Phone** | Phone number from the listing, if present. |
| **Website** | Website URL. Clickable hyperlink in the exported Excel file. |
| **Status** | No Website / Outdated / OK / Unknown. |
| **Last Evidence** | Date or year used as evidence for age classification. |
| **Detection Method** | Which step in the detection chain produced the result. |
| **Rating** | Google Maps star rating, if shown. |
| **Postcode** | Which postcode search produced this result. |

---

## Exporting to Excel

Once a scrape completes, click **Export to Excel** in the bottom-right corner. A save dialog appears — choose a filename and location. The file is saved as `.xlsx`.

### Spreadsheet layout

| Row(s) | Content |
|---|---|
| Row 1 | Title bar on a navy background. |
| Row 2 | Generated timestamp and total result count. |
| Row 3 | Empty spacer row. |
| Row 4 | Column headers with auto-filter dropdowns. Frozen — stays visible while scrolling. |
| Row 5+ | Data rows with colour-coded backgrounds. Website URLs are clickable hyperlinks. |

---

## How Maps Scraping Works

For each postcode the scraper navigates to:

```
https://www.google.com/maps/search/businesses+in+{POSTCODE}
```

A real headless Chromium browser is used so JavaScript renders fully and Google Maps behaves as it would for a human visitor.

### Step-by-step flow

1. **Consent handling** — automatically clicks "Accept all" on Google's consent page if shown.
2. **Results detection** — checks whether the page shows a list or a single business and handles each accordingly.
3. **Scrolling the results list** — progressively scrolls the feed, waiting for new cards to appear, up to the configured maximum.
4. **Parallel place visits** — up to 3 business pages are visited simultaneously, extracting name, address, phone, website, and rating. Concurrent visits reduce total run time by roughly 3×.
5. **Website age checks** — all extracted website URLs for a postcode are checked concurrently and matching businesses are emitted to the results table in real time.

### Rate limiting & anti-detection

- Random delays of 0.6–1.2 s between individual place page visits
- Random delays of 1.5–3.0 s between different postcodes
- The `navigator.webdriver` property is hidden from the page
- A realistic Chrome user-agent string is used
- If a CAPTCHA page is detected, the scraper pauses for 30 seconds and retries once

> Google Maps does not have a public API for bulk business data. The built-in rate limiting is designed to keep usage at a normal human-browsing pace.

---

## Website Age Detection

When a business has a website URL, four checks are attempted in order. The first to return a conclusive result wins — the rest are cancelled. Results for each unique domain are cached for the lifetime of a scrape run.

### Detection chain

**① WHOIS + Wayback Machine** *(raced concurrently)*

Both run simultaneously; whichever returns first with a conclusive result is used.

- **WHOIS** — queries the domain registrar for the registration date. A domain registered in 2004 almost certainly means the site has been around since at least 2004.
- **Wayback Machine (Archive.org CDX API)** — queries the Internet Archive for the earliest successful snapshot of the domain.

**② HTML Copyright Year Scan** *(fallback)*

The homepage is fetched and parsed. The scraper searches the footer, copyright meta tags, and full page text for patterns like `© 2006`, `Copyright 2008`, or `(c) 2003`. The earliest year found is used.

**③ HTTP `Last-Modified` Header** *(fallback)*

A HEAD request is sent first. If the server responds with a `Last-Modified` header, the date is compared to the threshold year.

**④ Unknown** *(final fallback)*

If all methods fail, the website is classified as *Unknown* and appears in grey in the table and export.

### Classification logic

| Evidence date | Result |
|---|---|
| Date < threshold year | Outdated |
| Date ≥ threshold year | OK (excluded from results) |
| No website URL on Google Maps | No Website |
| Website found but no date signal | Unknown |

---

## Architecture

The application follows a **producer–consumer** pattern. A background thread runs an `asyncio` event loop that drives Playwright and HTTP requests. The GUI (tkinter) runs on the main thread and is never blocked. A `queue.Queue` bridges the two threads safely.

The scraper thread is a daemon thread — it is automatically killed when the main window closes, preventing zombie browser processes. The Stop button sets a `threading.Event` that the scraper checks at each iteration for a clean shutdown.

---

## Tips & Troubleshooting

### Getting more results
- Increase *Max results / postcode* to 50 or more for dense urban areas
- Run multiple adjacent postcodes together — enter them comma-separated
- *Unknown* status rows are still worth exporting; many have no website even if the detection chain couldn't confirm a date

### The scrape is slow
- Website checks (especially WHOIS and Wayback Machine) depend on external servers — slowness is often network latency, not the app itself
- Each postcode requires the browser to scroll and visit multiple pages; 20 results typically takes 1–3 minutes

### No results for a postcode
- Google Maps returns very localised results — a postcode with few businesses will naturally return fewer listings
- Try a neighbouring or broader postcode (e.g. `EC1A` instead of `EC1A 1BB`)

### Many "Unknown" results
- Many small business websites use domain privacy (WHOIS hidden), have never been archived, have no copyright notice, and omit HTTP headers — all four checks can legitimately fail
- *Unknown* does **not** mean the website is modern; it means the age could not be determined automatically
- Consider manually spot-checking *Unknown* rows before outreach

### CAPTCHA warning in the status bar
If Google detects automated browsing it may serve a CAPTCHA page. The scraper detects this, pauses for 30 seconds, and retries once. If the problem persists, stop the scrape, wait a few minutes, then try again with a smaller *Max results* value or fewer postcodes per run.

> **Tip:** Running `python main.py` from a terminal instead of `launch.pyw` shows a console window with real-time debug output — useful for diagnosing unexpected behaviour.
