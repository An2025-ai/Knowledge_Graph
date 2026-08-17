"""Collect configured public, JavaScript-rendered pages with Playwright."""
from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path
from queue import Empty
from types import SimpleNamespace

from .storage import DATASETS, upsert_jsonl


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "browser-sources.json"
DATA_ROOT = ROOT / "data"
USER_AGENT = "BrandAtlasResearch/0.1 (+public, low-frequency research)"
DEFAULT_EXTRACT_TIMEOUT_MS = 8000
BLOCKER_PATTERNS = (
    "captcha",
    "verify you are human",
    "access denied",
    "just a moment",
    "访问验证",
    "安全验证",
    "请完成验证",
    "登录后继续",
    "请登录后",
    "sign in to continue",
)
FAILURE_PATTERNS = ("404", "page not found", "页面已经搬家", "页面不存在", "未找到页面")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_sources(path: Path, dataset: str, limit: int | None) -> list[dict]:
    sources = json.loads(path.read_text(encoding="utf-8-sig"))
    selected = [
        source
        for source in sources
        if source.get("enabled", True)
        and source.get("dataset") in DATASETS
        and (dataset == "all" or source["dataset"] == dataset)
    ]
    return selected[:limit] if limit else selected


def robots_allowed(url: str) -> tuple[bool, str]:
    parsed = urllib.parse.urlsplit(url)
    robots_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/robots.txt", "", ""))
    request = urllib.request.Request(robots_url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            body = response.read().decode(response.headers.get_content_charset() or "utf-8", "replace")
    except urllib.error.HTTPError as exc:
        if 400 <= exc.code < 500:
            return True, f"robots returned HTTP {exc.code}"
        return False, f"robots returned HTTP {exc.code}"
    except Exception as exc:
        return False, f"robots unavailable: {exc}"
    parser = urllib.robotparser.RobotFileParser()
    parser.set_url(robots_url)
    parser.parse(body.splitlines())
    allowed = parser.can_fetch(USER_AGENT, url)
    return allowed, "robots allowed" if allowed else "robots disallowed"


def extract_page(page, source: dict) -> dict:
    selector = source.get("content_selector") or "body"
    timeout_ms = int(source.get("extract_timeout_ms") or DEFAULT_EXTRACT_TIMEOUT_MS)
    payload = page.evaluate(
        r"""selector => {
          const pick = (...selectors) => {
            for (const value of selectors) {
              const node = document.querySelector(value);
              const content = node?.getAttribute('content') || node?.getAttribute('datetime') || node?.textContent;
              if (content && content.trim()) return content.trim();
            }
            return '';
          };
          const root = document.querySelector(selector) || document.body;
          return {
            title: document.title || '',
            canonical: document.querySelector('link[rel="canonical"]')?.href || location.href,
            published: pick('meta[property="article:published_time"]', 'meta[name="date"]',
                            'meta[name="datePublished"]', 'time[datetime]')
          };
        }""",
        selector,
    )
    payload["text"] = page.locator(selector).or_(page.locator("body")).first.inner_text(timeout=timeout_ms)
    payload["text"] = re.sub(r"\s+", " ", payload["text"]).strip()
    payload["final_url"] = page.url
    return payload


def configure_page_timeouts(page, timeout_seconds: int) -> None:
    timeout_ms = max(1, int(timeout_seconds)) * 1000
    page.set_default_timeout(timeout_ms)
    page.set_default_navigation_timeout(timeout_ms)


def _fetch_page_worker(params: dict, queue) -> None:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        queue.put({"ok": False, "error": "Playwright is not installed. Run .\\install-browser-collector.ps1 first."})
        return

    source = params["source"]
    browser_args = SimpleNamespace(
        profile=Path(params["profile"]) if params.get("profile") else None,
        headed=bool(params.get("headed")),
        browser_channel=params.get("browser_channel") or "auto",
    )
    with sync_playwright() as playwright:
        browser, context, browser_engine = launch_context(playwright, browser_args)
        try:
            page = context.new_page()
            configure_page_timeouts(page, params["timeout_seconds"])
            payload: dict = {}
            try:
                response = page.goto(
                    params["url"],
                    wait_until=source.get("wait_until", "domcontentloaded"),
                    timeout=params["timeout_seconds"] * 1000,
                )
                if source.get("wait_for"):
                    page.wait_for_selector(source["wait_for"], timeout=params["timeout_seconds"] * 1000)
                page.wait_for_timeout(source.get("settle_ms", 1500))
                payload = extract_page(page, source)
                payload["http_status"] = response.status if response else None
                queue.put({"ok": True, "payload": payload, "browser": browser_engine})
            except Exception as exc:
                queue.put({"ok": False, "payload": payload, "error": str(exc), "browser": browser_engine})
            finally:
                try:
                    page.close()
                except Exception:
                    pass
        finally:
            context.close()
            if browser:
                browser.close()


def fetch_page_with_hard_timeout(url: str, source: dict, browser_args: argparse.Namespace, timeout_seconds: int) -> dict:
    """Fetch one page in a killable worker so hostile/JS-heavy pages cannot hang the run."""
    hard_timeout = max(timeout_seconds + 8, int(timeout_seconds * 1.5) + 3)
    queue = multiprocessing.Queue()
    params = {
        "url": url,
        "source": source,
        "timeout_seconds": max(1, int(timeout_seconds)),
        "profile": str(browser_args.profile) if getattr(browser_args, "profile", None) else None,
        "headed": bool(getattr(browser_args, "headed", False)),
        "browser_channel": getattr(browser_args, "browser_channel", "auto"),
    }
    process = multiprocessing.Process(target=_fetch_page_worker, args=(params, queue), daemon=True)
    process.start()
    process.join(hard_timeout)
    if process.is_alive():
        process.terminate()
        process.join(5)
        if process.is_alive():
            process.kill()
            process.join(5)
        return {"ok": False, "payload": {}, "error": f"page hard timeout after {hard_timeout}s"}
    try:
        return queue.get_nowait()
    except Empty:
        return {"ok": False, "payload": {}, "error": f"page worker exited without result, code {process.exitcode}"}


def blocker_reason(title: str, text: str) -> str | None:
    sample = f"{title}\n{text[:6000]}".lower()
    return next((pattern for pattern in BLOCKER_PATTERNS if pattern in sample), None)


def failure_reason(title: str, text: str) -> str | None:
    sample = f"{title}\n{text[:2000]}".lower()
    return next((pattern for pattern in FAILURE_PATTERNS if pattern in sample), None)


def content_quality_error(text: str, minimum: int = 80) -> str | None:
    return None if len(text) >= minimum else f"insufficient extracted text: {len(text)} characters"


def make_record(source: dict, payload: dict, status: str, error: str | None = None) -> dict:
    canonical = payload.get("canonical") or payload.get("final_url") or source["url"]
    record_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]
    text = payload.get("text", "")
    record = {
        "id": record_id,
        "source": source["name"],
        "dataset": source["dataset"],
        "category": source.get("category", source["dataset"]),
        "title": payload.get("title") or source["name"],
        "url": canonical,
        "requested_url": source["url"],
        "final_url": payload.get("final_url", source["url"]),
        "http_status": payload.get("http_status"),
        "published_at": payload.get("published") or None,
        "collected_at": utc_now(),
        "collector": "playwright",
        "status": status,
        "requires_login": bool(source.get("requires_login")),
        "summary": text[:2000],
        "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None,
    }
    if error:
        record["error"] = error
    return record


def save_record(record: dict, text: str) -> None:
    dataset_dir = DATA_ROOT / record["dataset"]
    if text:
        pages_dir = dataset_dir / "pages"
        pages_dir.mkdir(parents=True, exist_ok=True)
        content_path = pages_dir / f"{record['id']}.txt"
        content_path.write_text(text, encoding="utf-8")
        record["content_path"] = str(content_path.relative_to(ROOT))
    upsert_jsonl(dataset_dir / "browser-items.jsonl", [record])


def launch_context(playwright, args: argparse.Namespace):
    channels = [None, "msedge"] if args.browser_channel == "auto" else [args.browser_channel]
    errors = []
    for channel in channels:
        options = {"headless": not args.headed, "user_agent": USER_AGENT}
        if channel:
            options["channel"] = channel
        try:
            if args.profile:
                return None, playwright.chromium.launch_persistent_context(str(args.profile), **options), channel or "chromium"
            browser_options = {"headless": options.pop("headless")}
            if channel:
                browser_options["channel"] = options.pop("channel")
            browser = playwright.chromium.launch(**browser_options)
            return browser, browser.new_context(**options), channel or "chromium"
        except Exception as exc:
            errors.append(f"{channel or 'chromium'}: {exc}")
    raise RuntimeError("No Playwright browser is available. " + " | ".join(errors))


def collect(args: argparse.Namespace) -> int:
    try:
        import playwright  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "Playwright is not installed. Run .\\install-browser-collector.ps1 first."
        ) from exc

    if args.include_login and (not args.profile or not args.headed):
        raise SystemExit("Login sources require both --profile PATH and --headed.")
    sources = load_sources(args.config, args.dataset, args.limit)
    if not sources:
        print("No enabled browser sources matched the selection.")
        return 0

    results: list[dict] = []
    browser_engine = args.browser_channel if args.browser_channel != "auto" else "playwright"
    for source in sources:
        if source.get("requires_login") and not args.include_login:
            record = make_record(source, {}, "skipped", "login profile required")
            save_record(record, "")
            results.append(record)
            continue
        if source.get("respect_robots", True):
            allowed, reason = robots_allowed(source["url"])
            if not allowed:
                record = make_record(source, {}, "blocked", reason)
                save_record(record, "")
                results.append(record)
                continue
        result = fetch_page_with_hard_timeout(source["url"], source, args, args.timeout)
        payload = result.get("payload") or {}
        browser_engine = result.get("browser") or browser_engine
        if result.get("ok"):
            blocker = blocker_reason(payload["title"], payload["text"])
            failure = failure_reason(payload["title"], payload["text"])
            if payload["http_status"] and payload["http_status"] >= 400:
                status, error = "error", f"HTTP {payload['http_status']}"
            elif blocker:
                status, error = "blocked", f"manual browser action required: {blocker}"
            elif failure:
                status, error = "error", f"soft error page detected: {failure}"
            elif quality_error := content_quality_error(payload["text"], source.get("min_text_length", 80)):
                status, error = "error", quality_error
            else:
                status, error = "ok", None
            record = make_record(source, payload, status, error)
        else:
            record = make_record(source, payload, "error", result.get("error", "page fetch failed"))
        save_record(record, payload.get("text", "") if record["status"] == "ok" else "")
        results.append(record)
        time.sleep(args.delay)

    counts = {status: sum(item["status"] == status for item in results) for status in ("ok", "skipped", "blocked", "error")}
    print(json.dumps({"browser": browser_engine, "total": len(results), **counts}, ensure_ascii=False))
    return 1 if counts["error"] else 0


def diagnose() -> int:
    try:
        import playwright
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(json.dumps({"playwright": False, "chromium": False}))
        return 1
    errors = []
    with sync_playwright() as api:
        for channel in (None, "msedge"):
            try:
                browser = api.chromium.launch(headless=True, **({"channel": channel} if channel else {}))
                browser.close()
                print(json.dumps({"playwright": True, "browser": channel or "chromium", "ready": True}))
                return 0
            except Exception as exc:
                errors.append(f"{channel or 'chromium'}: {exc}")
    print(json.dumps({"playwright": True, "browser": None, "ready": False, "errors": errors}, ensure_ascii=False))
    return 1


def login(args: argparse.Namespace) -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise SystemExit("Playwright is not installed. Run .\\install-browser-collector.ps1 first.") from exc
    args.headed = True
    with sync_playwright() as playwright:
        browser, context, browser_engine = launch_context(playwright, args)
        try:
            page = context.pages[0] if context.pages else context.new_page()
            page.goto(args.url, wait_until="domcontentloaded", timeout=args.timeout * 1000)
            print(f"Opened {args.url} with {browser_engine}. Complete login in the browser, then press Enter here.")
            input()
        finally:
            context.close()
            if browser:
                browser.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    collect_parser = subparsers.add_parser("collect", help="Collect configured browser sources")
    collect_parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    collect_parser.add_argument("--dataset", choices=("all", *DATASETS), default="all")
    collect_parser.add_argument("--limit", type=int)
    collect_parser.add_argument("--timeout", type=int, default=35)
    collect_parser.add_argument("--delay", type=float, default=2.0)
    collect_parser.add_argument("--headed", action="store_true")
    collect_parser.add_argument("--profile", type=Path)
    collect_parser.add_argument("--include-login", action="store_true")
    collect_parser.add_argument("--browser-channel", choices=("auto", "chromium", "msedge"), default="auto")
    login_parser = subparsers.add_parser("login", help="Create or update a dedicated login profile")
    login_parser.add_argument("--url", required=True)
    login_parser.add_argument("--profile", type=Path, default=ROOT / ".browser-profile")
    login_parser.add_argument("--timeout", type=int, default=60)
    login_parser.add_argument("--browser-channel", choices=("auto", "chromium", "msedge"), default="auto")
    subparsers.add_parser("diagnose", help="Check Playwright and Chromium availability")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    if args.command == "diagnose":
        return diagnose()
    if args.command == "login":
        return login(args)
    return collect(args)


if __name__ == "__main__":
    raise SystemExit(main())
