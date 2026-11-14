"""예의 있는 HTTP 클라이언트 (표준 라이브러리만 사용).

- 같은 호스트에 대한 요청 사이 최소 간격을 강제한다.
- 쿠키를 유지한다(세션이 필요한 예약 사이트 대비).
"""
from __future__ import annotations

import http.cookiejar
import json
import os
import time
import urllib.parse
import urllib.request

USER_AGENT = "Mozilla/5.0 (personal tennis-court availability viewer)"
MIN_INTERVAL_SEC = 1.5


class PoliteClient:
    def __init__(self, min_interval: float = MIN_INTERVAL_SEC, timeout: float = 20):
        self.min_interval = min_interval
        self.timeout = timeout
        self._last: dict[str, float] = {}
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())
        )

    # 사이트별 최소 간격(초). 용인은 짧은 시간에 25~30건이 몰리면 IP를 차단한다고 알려져 있음.
    # GitHub Actions 에서는 YONGIN_INTERVAL 로 줄인다 (차단돼도 집 IP가 아니라 실행 서버가 막힘).
    HOST_INTERVALS = {"publicsports.yongin.go.kr": float(os.environ.get("YONGIN_INTERVAL", "5.0"))}

    def _wait(self, url: str) -> None:
        host = urllib.parse.urlsplit(url).netloc
        gap = max(self.min_interval, self.HOST_INTERVALS.get(host, 0))
        elapsed = time.monotonic() - self._last.get(host, 0)
        if elapsed < gap:
            time.sleep(gap - elapsed)
        self._last[host] = time.monotonic()

    def request(self, url: str, *, method: str = "GET", params: dict | None = None,
                data: dict | None = None, json_body: dict | None = None,
                headers: dict | None = None) -> str:
        if params:
            url += ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        body = None
        hdrs = {"User-Agent": USER_AGENT, **(headers or {})}
        if json_body is not None:
            body = json.dumps(json_body).encode()
            hdrs["Content-Type"] = "application/json"
        elif data is not None:
            body = urllib.parse.urlencode(data).encode()
            hdrs["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
        self._wait(url)
        req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
        with self._opener.open(req, timeout=self.timeout) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            return resp.read().decode(charset, errors="replace")

    def get(self, url: str, **kw) -> str:
        return self.request(url, **kw)

    def post(self, url: str, **kw) -> str:
        return self.request(url, method="POST", **kw)

    def get_json(self, url: str, **kw):
        return json.loads(self.request(url, **kw))
