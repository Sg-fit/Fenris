import threading
from urllib.parse import quote_plus, urljoin

from addons.base import Addon, AddonResult
from addons.net import safe_public_url


class WebBrowserAddon(Addon):
    """Controlled browser access for research and explicitly approved tasks."""

    id = "web_browser"
    name = "Web browser"
    description = "Research public web pages or perform explicitly confirmed browser steps."
    required_role = "user"

    def __init__(self):
        # Cookies/local storage per enrolled actor, so a login made through
        # one call (e.g. interact) is still there on a later, separate call
        # (another interact, or read_page). In-memory only, for as long as
        # this backend process runs — never written to disk, and never kept
        # for guests, since "guest" isn't a specific person.
        self._storage_states: dict[tuple[str, str], dict] = {}
        self._lock = threading.Lock()

    def _session_key(self, actor_name: str, actor_role: str) -> tuple[str, str] | None:
        return None if actor_role == "guest" else (actor_name, actor_role)

    def _new_context(self, browser, session_key: tuple[str, str] | None):
        state = None
        if session_key is not None:
            with self._lock:
                state = self._storage_states.get(session_key)
        return browser.new_context(storage_state=state) if state else browser.new_context()

    def _remember_context(self, context, session_key: tuple[str, str] | None) -> None:
        if session_key is None:
            return
        state = context.storage_state()
        with self._lock:
            self._storage_states[session_key] = state

    @staticmethod
    def _extract_media(page, base_url: str) -> tuple[list[str], list[str]]:
        """Best-effort image/video URLs on the page, so the model has real
        links to hand to the show_media tool instead of guessing."""
        images: list[str] = []
        og_image = page.locator('meta[property="og:image"]')
        if og_image.count():
            content = og_image.first.get_attribute("content")
            if content:
                images.append(urljoin(base_url, content))
        for element in page.locator("img").all()[:8]:
            src = element.get_attribute("src")
            if src:
                resolved = urljoin(base_url, src)
                if resolved not in images:
                    images.append(resolved)
            if len(images) >= 5:
                break

        videos: list[str] = []
        for element in page.locator("video source, video").all()[:5]:
            src = element.get_attribute("src")
            if src:
                resolved = urljoin(base_url, src)
                if resolved not in videos:
                    videos.append(resolved)
        if len(videos) < 5:
            for element in page.locator("iframe").all()[:10]:
                src = element.get_attribute("src") or ""
                if "youtube.com/embed" in src or "youtube-nocookie.com/embed" in src:
                    resolved = urljoin(base_url, src)
                    if resolved not in videos:
                        videos.append(resolved)
                if len(videos) >= 5:
                    break

        return images[:5], videos[:5]

    @staticmethod
    def _extract_fields(page) -> list[dict]:
        """Best-effort real selectors for interactive elements (inputs,
        selects, buttons) on the page, so browser_actions can target exact
        elements instead of guessing selectors blindly. Prefers id/name
        attributes, which are stable across a fresh page load; falls back to
        a global positional match otherwise."""
        fields: list[dict] = []
        elements = page.locator("input, textarea, select, button").all()[:40]
        for index, element in enumerate(elements):
            try:
                tag = element.evaluate("el => el.tagName.toLowerCase()")
            except Exception:
                continue
            element_id = element.get_attribute("id")
            name = element.get_attribute("name")
            if element_id:
                selector = f"#{element_id}"
            elif name:
                selector = f'{tag}[name="{name}"]'
            else:
                # Global 1-indexed positional match — Playwright-specific,
                # only used when nothing more stable is available.
                selector = f":nth-match({tag}, {index + 1})"

            label = None
            if element_id:
                label_locator = page.locator(f'label[for="{element_id}"]')
                if label_locator.count():
                    label = label_locator.first.inner_text().strip()
            if not label:
                label = element.get_attribute("placeholder") or element.get_attribute("aria-label")
            if not label and tag == "button":
                label = element.inner_text().strip()
            if not label and tag == "input" and (element.get_attribute("type") or "") in {"submit", "button"}:
                # <input type="submit" value="Sign In"> shows its text via
                # value, not inner_text — this is usually the button label.
                label = element.get_attribute("value")

            fields.append(
                {
                    "selector": selector,
                    "tag": tag,
                    "type": element.get_attribute("type") or tag,
                    "label": (label or "")[:100] or None,
                }
            )
        return fields

    @staticmethod
    def _browser():
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as error:
            raise RuntimeError("Browser support is not installed. Run: pip install -r requirements.txt; playwright install chromium") from error
        return sync_playwright()

    def run(self, actor_name: str, actor_role: str, action: str, payload: dict, confirmed: bool) -> AddonResult:
        session_key = self._session_key(actor_name, actor_role)
        if action == "research":
            return self._research(payload)
        if action == "browse":
            return self._browse(payload, session_key)
        if action == "interact":
            if not confirmed:
                return AddonResult("confirmation_required", "Browser interaction can change website state. Review the steps, then confirm.", payload)
            return self._interact(payload, session_key)
        return AddonResult("invalid", "Supported actions: research, browse, interact.")

    def _research(self, payload: dict) -> AddonResult:
        query = payload.get("query")
        if not isinstance(query, str) or not query.strip():
            return AddonResult("invalid", "query is required.")
        limit = payload.get("limit", 5)
        if not isinstance(limit, int) or not 1 <= limit <= 10:
            return AddonResult("invalid", "limit must be an integer from 1 to 10.")
        site = payload.get("site")
        # site:domain scopes results to inside that one site/platform — the
        # only way this lightweight search backend can search "within"
        # somewhere like reddit.com or a specific news site.
        full_query = f"site:{site} {query}" if isinstance(site, str) and site.strip() else query
        with self._browser() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                page.goto(f"https://html.duckduckgo.com/html/?q={quote_plus(full_query)}", wait_until="domcontentloaded")
                links = page.locator(".result__a")
                results = []
                for index in range(min(links.count(), limit)):
                    link = links.nth(index)
                    results.append({"title": link.inner_text(), "url": link.get_attribute("href")})
            finally:
                browser.close()
        return AddonResult("complete", f"Found {len(results)} results for {full_query}.", {"results": results})

    def _browse(self, payload: dict, session_key: tuple[str, str] | None) -> AddonResult:
        try:
            url = safe_public_url(payload.get("url", ""))
        except ValueError as error:
            return AddonResult("invalid", str(error))
        with self._browser() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                context = self._new_context(browser, session_key)
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30_000)
                title = page.title()
                text = page.locator("body").inner_text()[:6_000]
                images, videos = self._extract_media(page, url)
                fields = self._extract_fields(page)
                self._remember_context(context, session_key)
            finally:
                browser.close()
        return AddonResult(
            "complete",
            f"Read {title}.",
            {"url": url, "title": title, "text": text, "images": images, "videos": videos, "fields": fields},
        )

    # Click/fill fail fast rather than sitting on Playwright's 30s-per-action
    # default — across up to 12 steps that default could eat minutes on a
    # single bad selector before ever reporting back.
    ACTION_TIMEOUT_MS = 8_000

    def _interact(self, payload: dict, session_key: tuple[str, str] | None) -> AddonResult:
        steps = payload.get("steps")
        if not isinstance(steps, list) or not 1 <= len(steps) <= 12:
            return AddonResult("invalid", "steps must contain 1 to 12 explicit browser steps.")
        # A visible window only appears when the user actually asked to watch;
        # otherwise this runs headless like research/browse.
        show_window = bool(payload.get("show_window", False))
        with self._browser() as playwright:
            browser = playwright.chromium.launch(headless=not show_window)
            try:
                context = self._new_context(browser, session_key)
                page = context.new_page()
                for index, step in enumerate(steps):
                    if not isinstance(step, dict) or step.get("action") not in {"open", "click", "fill", "wait"}:
                        return AddonResult("invalid", "Each step action must be open, click, fill, or wait.")
                    action = step["action"]
                    try:
                        if action == "open":
                            page.goto(safe_public_url(step.get("url", "")), wait_until="domcontentloaded")
                        elif action == "click":
                            page.locator(step.get("selector", "")).click(timeout=self.ACTION_TIMEOUT_MS)
                        elif action == "fill":
                            page.locator(step.get("selector", "")).fill(
                                str(step.get("value", "")), timeout=self.ACTION_TIMEOUT_MS
                            )
                        else:
                            page.wait_for_timeout(min(int(step.get("milliseconds", 500)), 5_000))
                    except Exception:
                        # Most often: that selector isn't on the page anymore —
                        # the page changed, or (now that logins persist) this
                        # URL shows different content than when it was last
                        # read, e.g. an already-authenticated dashboard instead
                        # of a login form.
                        return AddonResult(
                            "invalid",
                            f"Step {index + 1} ({action}) didn't find or couldn't use "
                            f"{step.get('selector', step.get('url', ''))!r} — the page may not "
                            "be what read_page last saw. Re-read the page before trying again.",
                            {"failed_step": index, "url": page.url},
                        )
                title, url = page.title(), page.url
                self._remember_context(context, session_key)
            finally:
                browser.close()
        return AddonResult("complete", f"Completed approved browser steps on {title}.", {"url": url, "title": title})
