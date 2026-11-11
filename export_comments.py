#!/usr/bin/env python3
"""Export TikTok video comments to CSV or JSON Lines: text, likes, replies, author and time.

No TikTok login, no browser, no scraping on your machine: data comes from the okdata API
(https://okdata.online), $0.002 per page of about 50 comments. Python 3.9+, standard library only.
The key goes in the OKDATA_API_KEY environment variable.

    python3 export_comments.py https://www.tiktok.com/@user/video/7305085486984858894 --pages 4
    python3 export_comments.py --file videos.txt --format jsonl -o comments.jsonl
"""
from __future__ import annotations

import argparse
import csv
import http.client
import json
import os
import re
import sys
import time
import uuid
from decimal import Decimal
from typing import Any, Callable, Dict, Iterator, List, Optional, TextIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

VERSION = "0.1.0"
SOURCE = "gh-tiktok-comments-export"
SIGN_UP = f"https://okdata.online/signup/?src={SOURCE}"
API = os.environ.get("OKDATA_BASE_URL", "https://api.okdata.online").rstrip("/")
# Fallback prices (USD) if the free catalog cannot be read; the live catalog wins.
PRICES = {"tiktok.videos.comments.list": Decimal("0.002"), "tiktok.videos.get": Decimal("0.002")}
VIDEO_ID = re.compile(r"^\d{15,22}$")
VIDEO_IN_URL = re.compile(r"/(?:video|photo)/(\d{15,22})")
FIELDS = ["video_id", "comment_id", "parent_id", "text", "likes", "replies", "published_at", "author_username", "author_name"]
RETRY_STATUSES = {429, 500, 502, 503, 504}


class ApiError(Exception):
    def __init__(self, code: str, message: str, *, charged: Optional[bool] = False, retry: str = "no",
                 retry_after: Optional[float] = None) -> None:
        super().__init__(f"{code}: {message}")
        self.code, self.charged, self.retry, self.retry_after = code, charged, retry, retry_after


class Okdata:
    """The two okdata calls this script needs, with safe retries and a hard spending cap."""

    def __init__(self, key: str, budget: Optional[Decimal] = None, sleep: Callable[[float], None] = time.sleep) -> None:
        self.key = key
        self.budget = budget
        self.sleep = sleep
        self.spent = Decimal("0")
        self.caps = dict(PRICES)

    def _headers(self, idempotency_key: Optional[str]) -> Dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": f"{SOURCE}/{VERSION}"}
        if self.key:
            headers["Authorization"] = f"Bearer {self.key}"
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def prices(self) -> Dict[str, Decimal]:
        """Current prices from the free catalog (no key, no charge); the built-in table if it cannot be read."""
        try:
            data = request_json(f"{API}/v1/catalog", self._headers(None), self.sleep)["data"]
            live = {e["id"]: Decimal(e["maxCharge"]) for e in data["endpoints"]}
            self.caps = {k: live.get(k, v) for k, v in PRICES.items()}
        except (ApiError, KeyError, TypeError, ValueError, ArithmeticError):
            self.caps = dict(PRICES)
        return self.caps

    def call(self, endpoint: str, **params: Any) -> Dict[str, Any]:
        cap = self.caps.get(endpoint, Decimal("0"))
        if self.budget is not None and self.spent + cap > self.budget:
            raise ApiError("budget_reached", f"the next call could cost ${cap} and pass the --budget of ${self.budget}")
        query = urlencode({k: v for k, v in params.items() if v is not None})
        body = request_json(f"{API}/v1/{endpoint.replace('.', '/')}?{query}", self._headers(str(uuid.uuid4())), self.sleep)
        self.spent += Decimal((body.get("meta") or {}).get("billing", {}).get("amount", "0"))
        return body


def _http_error(exc: HTTPError) -> ApiError:
    try:
        body = json.loads(exc.read().decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        body = None
    if isinstance(body, dict) and "code" in body:
        return ApiError(str(body["code"]), str(body.get("message")), charged=body.get("charged", False),
                        retry=str(body.get("retry", "no")), retry_after=body.get("retry_after_seconds"))
    return ApiError(f"http_{exc.code}", str(exc.reason), charged=None, retry="yes" if exc.code in RETRY_STATUSES else "no")


def request_json(url: str, headers: Dict[str, str], sleep: Callable[[float], None] = time.sleep) -> Dict[str, Any]:
    """GET with up to 2 retries on the same Idempotency-Key, so a retry is never charged twice. After a lost
    answer the call may still be running on the server: wait for it, and if we give up, say the charge is unknown."""
    retries, waits, ambiguous = 0, 0, False
    while True:
        try:
            with urlopen(Request(url, headers=headers), timeout=90) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            if isinstance(body, dict) and body.get("code") == "ok":
                return body
            err = (ApiError(str(body.get("code")), str(body.get("message"))) if isinstance(body, dict)
                   else ApiError("bad_response", "unexpected answer", charged=None, retry="same_key"))
        except HTTPError as exc:
            err = _http_error(exc)
        except (OSError, ValueError, http.client.HTTPException) as exc:  # network, timeout, cut-off or non-JSON body
            err = ApiError("connection_error", str(exc), charged=None, retry="same_key")
        ambiguous = ambiguous or err.charged is None
        if ambiguous and err.code == "rate_limited" and waits < 5:
            waits += 1
            sleep(_wait(err.retry_after, 1.0))
            continue
        if err.retry not in ("yes", "same_key") or retries == 2:
            if ambiguous and err.charged is False:
                err.charged = None  # an earlier attempt may still finish and be billed
            raise err
        sleep(_wait(err.retry_after, 2.0 ** retries))
        retries += 1


def _wait(value: Any, default: float) -> float:
    """Seconds to sleep: the server's hint if it is a sane number, capped at 30."""
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return default
    return min(max(seconds, 0.0), 30.0)


def use_utf8() -> None:
    """Chinese text in and out, also on Windows consoles and pipes."""
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace" if stream is sys.stderr else "strict")


def cell(value: Any) -> Any:
    """Text that starts like a spreadsheet formula gets a leading ' so Excel shows it instead of running it."""
    return "'" + value if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def video_id(ok: Okdata, target: str) -> str:
    """A video id from an id, a full link, or a short vm/vt.tiktok.com link (one $0.002 lookup)."""
    target = target.strip()
    if VIDEO_ID.match(target):
        return target
    found = VIDEO_IN_URL.search(target)
    if found:
        return found.group(1)
    if not target.startswith(("https://", "http://")):
        raise ApiError("invalid_params", f"not a TikTok video link or id: {target!r}")
    return str(ok.call("tiktok.videos.get", url=target, view="compact")["data"]["item"]["id"])


def comments(ok: Okdata, vid: str, pages: int) -> Iterator[Dict[str, Any]]:
    cursor = None
    for _ in range(pages):
        body = ok.call("tiktok.videos.comments.list", id=vid, cursor=cursor, view="compact")
        for c in body["data"]["items"]:
            author = c.get("author") or {}
            yield {"video_id": vid, "comment_id": c.get("id"), "parent_id": c.get("parent_id"), "text": c.get("text"),
                   "likes": c.get("likes"), "replies": c.get("replies"), "published_at": c.get("published_at"),
                   "author_username": author.get("username"), "author_name": author.get("name")}
        cursor = (body.get("page") or {}).get("next_cursor")
        if not cursor:
            return


def read_targets(args: argparse.Namespace) -> List[str]:
    targets = list(args.videos)
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            targets += [line.strip() for line in f if line.strip() and not line.startswith("#")]
    return targets


def write(rows: Iterator[Dict[str, Any]], fmt: str, out: TextIO) -> int:
    n = 0
    writer = csv.DictWriter(out, fieldnames=FIELDS) if fmt == "csv" else None
    if writer:
        writer.writeheader()
    for row in rows:
        if writer:
            writer.writerow({k: cell(v) for k, v in row.items()})
        else:
            out.write(json.dumps(row, ensure_ascii=False) + "\n")
        n += 1
    return n


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description="Export TikTok video comments to CSV or JSON Lines (okdata API, $0.002 per page).")
    p.add_argument("videos", nargs="*", help="video links or ids")
    p.add_argument("--file", help="a text file with one video link or id per line")
    p.add_argument("--pages", type=int, default=2, help="pages per video, about 50 comments each (default 2)")
    p.add_argument("--format", choices=["csv", "jsonl"], default="csv")
    p.add_argument("-o", "--output", help="output file (default: stdout)")
    p.add_argument("--budget", type=Decimal, default=Decimal("1"), help="refuse runs that could cost more (USD, default 1)")
    p.add_argument("--dry-run", action="store_true", help="print the most it can cost and stop")
    use_utf8()
    args = p.parse_args(argv)
    targets = read_targets(args)
    if not targets:
        p.error("give at least one video link or id, or --file")
    if args.pages < 1:
        p.error("--pages must be 1 or more")

    key = os.environ.get("OKDATA_API_KEY", "").strip()
    ok = Okdata(key, budget=args.budget)
    caps = ok.prices()
    short = sum(1 for t in targets if not (VIDEO_ID.match(t.strip()) or VIDEO_IN_URL.search(t)))
    most = caps["tiktok.videos.comments.list"] * len(targets) * args.pages + caps["tiktok.videos.get"] * short
    print(f"plan: {len(targets)} video(s) x up to {args.pages} page(s){f' + {short} short-link lookup(s)' if short else ''}; "
          f"at most ${most}", file=sys.stderr)
    if args.dry_run:
        return 0
    if most > args.budget:
        print(f"over the --budget of ${args.budget}; raise it or use fewer --pages", file=sys.stderr)
        return 3
    if not key:
        print(f"OKDATA_API_KEY is not set. Get a key at {SIGN_UP}", file=sys.stderr)
        return 2

    # Write next to the target and rename at the end, so a failed run never wipes an earlier export.
    part = f"{args.output}.part" if args.output else None
    out = open(part, "w", newline="", encoding="utf-8") if part else sys.stdout
    n = 0
    try:
        def rows() -> Iterator[Dict[str, Any]]:
            for target in targets:
                try:
                    yield from comments(ok, video_id(ok, target), args.pages)
                except ApiError as err:
                    if err.code in ("unauthorized", "insufficient_balance", "budget_reached"):
                        raise
                    print(f"skipped {target}: {err} (charged: {err.charged})", file=sys.stderr)

        n = write(rows(), args.format, out)
    except ApiError as err:
        print(f"stopped: {err} (charged: {err.charged})", file=sys.stderr)
        return 1
    finally:
        if part:
            out.close()
            if n:
                os.replace(part, args.output)
            else:
                os.remove(part)
        print(f"{n} comments from {len(targets)} video(s); spent ${ok.spent}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
