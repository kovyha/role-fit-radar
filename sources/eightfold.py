# sources/eightfold.py
# Fetches jobs from an Eightfold AI job board.
# Standard path (most boards): direct API calls via requests.
# Playwright path (use_playwright=True): navigates the careers page first to
# establish session cookies — required for boards with PCSX auth (e.g. Citi).

import html as html_lib
import asyncio
import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from config import (
    JOB_CONTENT_MAX_CHARS, REQUEST_TIMEOUT_SECS, PLAYWRIGHT_PAGE_TIMEOUT_MS,
    PLAYWRIGHT_AUTH_SETTLE_MS, TITLE_TERMS, TITLE_BLOCKLIST,
)
from sources.filters import passes_local_filter

_USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
)

# Injected before any page script to mask headless Chromium fingerprints that
# PCSX bot-detection uses to block automated browsers.
_STEALTH_SCRIPT = """
(() => {
    // webdriver flag — the primary headless tell
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});

    // Realistic Chrome plugin list (headless has none)
    const makePlugin = (name, desc, filename, types) => {
        const plugin = Object.create(Plugin.prototype);
        Object.defineProperties(plugin, {
            name: {value: name}, description: {value: desc}, filename: {value: filename},
            length: {value: types.length},
        });
        types.forEach((t, i) => {
            const mt = Object.create(MimeType.prototype);
            Object.defineProperties(mt, {
                type: {value: t.type}, description: {value: t.desc},
                suffixes: {value: t.suffixes}, enabledPlugin: {value: plugin},
            });
            plugin[i] = mt;
        });
        return plugin;
    };
    const pluginData = [
        {name: 'Chrome PDF Plugin', desc: 'Portable Document Format', filename: 'internal-pdf-viewer',
         types: [{type: 'application/x-google-chrome-pdf', desc: 'Portable Document Format', suffixes: 'pdf'}]},
        {name: 'Chrome PDF Viewer', desc: '', filename: 'mhjfbmdgcfjbbpaeojofohoefgiehjai',
         types: [{type: 'application/pdf', desc: '', suffixes: 'pdf'}]},
        {name: 'Native Client', desc: '', filename: 'internal-nacl-plugin',
         types: [{type: 'application/x-nacl', desc: 'Native Client Executable', suffixes: ''},
                 {type: 'application/x-pnacl', desc: 'Portable Native Client Executable', suffixes: ''}]},
    ];
    const plugins = pluginData.map(d => makePlugin(d.name, d.desc, d.filename, d.types));
    Object.defineProperty(navigator, 'plugins', {get: () => plugins});
    Object.defineProperty(navigator, 'mimeTypes', {get: () => plugins.flatMap(p => Array.from({length: p.length}, (_, i) => p[i]))});

    // window.chrome — present in real Chrome, absent in headless
    window.chrome = {
        app: {isInstalled: false, InstallState: {DISABLED:'disabled',INSTALLED:'installed',NOT_INSTALLED:'not_installed'}, RunningState: {CANNOT_RUN:'cannot_run',READY_TO_RUN:'ready_to_run',RUNNING:'running'}},
        runtime: {OnInstalledReason: {CHROME_UPDATE:'chrome_update',INSTALL:'install',SHARED_MODULE_UPDATE:'shared_module_update',UPDATE:'update'}, OnRestartRequiredReason: {APP_UPDATE:'app_update',OS_UPDATE:'os_update',PERIODIC:'periodic'}, PlatformArch: {ARM:'arm',ARM64:'arm64',MIPS:'mips',MIPS64:'mips64',X86_32:'x86-32',X86_64:'x86-64'}, PlatformNaclArch: {ARM:'arm',MIPS:'mips',MIPS64:'mips64',X86_32:'x86-32',X86_64:'x86-64'}, PlatformOs: {ANDROID:'android',CROS:'cros',LINUX:'linux',MAC:'mac',OPENBSD:'openbsd',WIN:'win'}, RequestUpdateCheckStatus: {NO_UPDATE:'no_update',THROTTLED:'throttled',UPDATE_AVAILABLE:'update_available'}},
    };

    // permissions.query — headless returns 'denied' for notifications, real Chrome returns 'default'
    const origQuery = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = (params) =>
        params.name === 'notifications'
            ? Promise.resolve({state: Notification.permission, onchange: null})
            : origQuery(params);

    // WebGL — headless uses SwiftShader which is a known bot fingerprint
    const getParam = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function(p) {
        if (p === 37445) return 'Intel Inc.';
        if (p === 37446) return 'Intel Iris OpenGL Engine';
        return getParam.call(this, p);
    };
    const getParam2 = WebGL2RenderingContext.prototype.getParameter;
    WebGL2RenderingContext.prototype.getParameter = function(p) {
        if (p === 37445) return 'Intel Inc.';
        if (p === 37446) return 'Intel Iris OpenGL Engine';
        return getParam2.call(this, p);
    };

    // Hardware properties — headless often has defaults that differ from real machines
    Object.defineProperty(navigator, 'hardwareConcurrency', {get: () => 8});
    Object.defineProperty(navigator, 'deviceMemory', {get: () => 8});
    Object.defineProperty(navigator, 'platform', {get: () => 'MacIntel'});
    Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']});
})();
"""


def fetch_jobs(
    domain: str,
    location_filter: str,
    seen_urls: set | None = None,
    *,
    allowlist: frozenset = TITLE_TERMS,
    blocklist: frozenset = TITLE_BLOCKLIST,
    use_playwright: bool = False,
) -> list[dict]:
    """
    Fetch new jobs from an Eightfold board, filtered by location.

    Args:
        domain:          Eightfold domain e.g. "mlp.com"
        location_filter: Location string e.g. "London"
        seen_urls:       URLs already recorded; descriptions skipped for these
        use_playwright:  True for boards requiring browser session (e.g. Citi)

    Returns:
        List of job dicts with keys: title, url, location, department, content
    """
    if seen_urls is None:
        seen_urls = set()

    if use_playwright:
        return asyncio.run(_fetch_jobs_playwright(domain, location_filter, seen_urls, allowlist, blocklist))

    subdomain = domain.split(".")[0]
    base_url = f"https://{subdomain}.eightfold.ai/api/apply/v2/jobs"

    stubs = _fetch_stubs(base_url, domain, location_filter)

    results = []
    for stub in stubs:
        if stub["url"] in seen_urls:
            continue
        if not passes_local_filter(stub["title"], allowlist, blocklist):
            continue
        content = _fetch_content(base_url, domain, stub.pop("id"))
        stub["content"] = content
        results.append(stub)

    return results


# ── Shared parsers (used by both requests and Playwright paths) ────────────────

def _parse_stubs(data: dict) -> tuple[list[dict], int]:
    """Parse Eightfold list API response into stub dicts and total count."""
    positions = data.get("positions", [])
    stubs = [{
        "id":         job["id"],
        "title":      job.get("name", ""),
        "url":        job.get("canonicalPositionUrl", ""),
        "location":   job.get("location", ""),
        "department": job.get("department", ""),
    } for job in positions]
    return stubs, data.get("count", 0)


def _parse_description(detail: dict) -> str:
    """Extract and clean job description from Eightfold detail API response."""
    raw = detail.get("job_description", "") or ""
    return _strip_html(raw)[:JOB_CONTENT_MAX_CHARS]


# ── Requests path ──────────────────────────────────────────────────────────────

def _fetch_stubs(base_url: str, domain: str, location_filter: str) -> list[dict]:
    """Paginate the Eightfold list endpoint and return all matching job stubs."""
    stubs = []
    limit = 100
    start = 0

    while True:
        params = {"domain": domain, "location": location_filter, "limit": limit, "start": start}
        try:
            response = requests.get(base_url, params=params, timeout=REQUEST_TIMEOUT_SECS)
            response.raise_for_status()
        except requests.RequestException as e:
            print(f"[eightfold] Failed to fetch stubs (start={start}): {e}")
            break

        page_stubs, total = _parse_stubs(response.json())
        stubs.extend(page_stubs)
        start += len(page_stubs)
        if start >= total or not page_stubs:
            break

    return stubs


def _fetch_content(detail_base: str, domain: str, job_id: int) -> str:
    """Fetch and clean the description for a single Eightfold job."""
    url = f"{detail_base}/{job_id}"
    try:
        response = requests.get(url, params={"domain": domain}, timeout=REQUEST_TIMEOUT_SECS)
        response.raise_for_status()
        return _parse_description(response.json())
    except requests.RequestException as e:
        print(f"[eightfold] Failed to fetch content for job {job_id}: {e}")
        return ""


# ── Playwright path ────────────────────────────────────────────────────────────

async def _fetch_jobs_playwright(
    domain: str,
    location_filter: str,
    seen_urls: set,
    allowlist: frozenset,
    blocklist: frozenset,
) -> list[dict]:
    """Navigate the careers page to establish a PCSX session, then call the API."""
    subdomain = domain.split(".")[0]
    base = f"https://{subdomain}.eightfold.ai"
    careers_url = f"{base}/careers"
    search_url = f"{base}/api/pcsx/search"
    detail_url = f"{base}/api/pcsx/position_details"

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"],
        )
        context = await browser.new_context(user_agent=_USER_AGENT)
        await context.add_init_script(_STEALTH_SCRIPT)
        page = await context.new_page()

        try:
            await page.goto(careers_url, wait_until="load", timeout=PLAYWRIGHT_PAGE_TIMEOUT_MS)
            await page.wait_for_timeout(PLAYWRIGHT_AUTH_SETTLE_MS)  # PCSX JS challenge sets auth cookie ~1-3s after load
        except Exception as e:
            print(f"[eightfold] Playwright: failed to load {careers_url}: {e}")
            await browser.close()
            return []

        # Phase 1: paginate stubs via the PCSX search API
        stubs = []
        num = 100
        start = 0
        while True:
            try:
                resp = await context.request.get(search_url, params={
                    "domain": domain, "query": "", "location": location_filter,
                    "num": num, "start": start,
                }, timeout=PLAYWRIGHT_PAGE_TIMEOUT_MS)
                if not resp.ok:
                    print(f"[eightfold] Playwright: search API returned {resp.status} for {domain}")
                    break
                payload = (await resp.json()).get("data", {})
                positions = payload.get("positions", [])
                total = payload.get("count", 0)
            except Exception as e:
                print(f"[eightfold] Playwright: stub fetch failed for {domain}: {e}")
                break
            for pos in positions:
                stubs.append({
                    "id":         pos["id"],
                    "title":      pos.get("name", ""),
                    "url":        f"{base}{pos.get('positionUrl', '')}",
                    "location":   ", ".join(pos.get("locations", [])),
                    "department": pos.get("department", ""),
                })
            start += len(positions)
            if start >= total or not positions:
                break

        # Phase 2: filter, then fetch descriptions for new jobs only
        results = []
        for stub in stubs:
            if stub["url"] in seen_urls:
                continue
            if not passes_local_filter(stub["title"], allowlist, blocklist):
                continue
            job_id = stub.pop("id")
            try:
                resp = await context.request.get(detail_url, params={
                    "position_id": job_id, "domain": domain, "hl": "en",
                }, timeout=PLAYWRIGHT_PAGE_TIMEOUT_MS)
                if resp.ok:
                    detail = (await resp.json()).get("data", {})
                    stub["content"] = _strip_html(detail.get("jobDescription", "") or "")[:JOB_CONTENT_MAX_CHARS]
                else:
                    stub["content"] = ""
            except Exception as e:
                print(f"[eightfold] Playwright: content fetch failed for job {job_id}: {e}")
                stub["content"] = ""
            results.append(stub)

        await browser.close()

    return results


# ── Utilities ──────────────────────────────────────────────────────────────────

def _strip_html(html: str) -> str:
    """Strip HTML tags and return clean text, handling entity-encoded HTML."""
    if not html:
        return ""
    return BeautifulSoup(html_lib.unescape(html), "html.parser").get_text(separator="\n", strip=True)
