"""쿠팡파트너스( affiliates ) Open API 클라이언트.

HMAC-SHA256 서명 인증만 구현한 최소 의존성 클라이언트.
공식 문서: https://developers.coupang.com/ (파트너스 > API 문서)

서명 규칙 (쿠팡 공식 예제 기준)
    datetime  = yyMMdd'T'HHmmss'Z'  (UTC)
    message   = datetime + METHOD + PATH + QUERY     ← 날짜가 맨 앞에 붙는다!
    signature = hex( HMAC-SHA256(secret_key, message) )
    header    = "CEA algorithm=HmacSHA256, access-key={ACCESS_KEY}, "
                "signed-date={datetime}, signature={signature}"

  ※ message 앞에 datetime 을 붙이는 것이 핵심이다. method+path 만 서명하면
     쿠팡이 401/403 을 돌려준다(재현율 높은 실수).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse
from dataclasses import dataclass
from typing import Any, Iterable

import requests

API_HOST = "https://api-gateway.coupang.com"

PATH_SEARCH = "/v2/providers/affiliate_open_api/apis/openapi/v1/products/search"
PATH_GOLDBOX = "/v2/providers/affiliate_open_api/apis/openapi/v1/products/goldbox"
PATH_BEST = "/v2/providers/affiliate_open_api/apis/openapi/v1/products/bestcategories/{cid}"
PATH_DEEPLINK = "/v2/providers/affiliate_open_api/apis/openapi/v1/deeplink"


class CoupangError(RuntimeError):
    """API가 2xx가 아닌 응답을 돌려줬을 때."""

    def __init__(self, status: int, body: str, code: str = ""):
        super().__init__(f"HTTP {status} {code}: {body[:300]}")
        self.status = status
        self.body = body
        self.code = code

    @property
    def rate_limited(self) -> bool:
        # 403 은 시간당 호출 한도 초과, 429 는 분당 한도 초과.
        return self.status in (403, 429)


@dataclass
class Usage:
    """이번 실행에서 실제로 나간 요청 수 (한도 계산용)."""

    requests: int = 0

    def hit(self) -> None:
        self.requests += 1


def signed_date(epoch: float | None = None) -> str:
    """yyMMdd'T'HHmmss'Z' (GMT) — 쿠팡이 요구하는 형식."""
    return time.strftime("%y%m%dT%H%M%SZ", time.gmtime(epoch if epoch is not None else time.time()))


def build_query(params: dict[str, Any]) -> str:
    """쿼리스트링을 알파벳순으로 고정한다.

    서명은 이 문자열 그대로 계산되므로, 호출과 서명이 같은 순서를 쓰는 게
    중요하다. dict 순서에 의존하지 않도록 정렬해서 만든다.
    """
    flat = {k: v for k, v in params.items() if v is not None and v != ""}
    return "&".join(f"{k}={urllib.parse.quote(str(v), safe='')}" for k, v in sorted(flat.items()))


def sign(secret_key: str, method: str, path: str, query: str, at: float | None = None) -> tuple[str, str]:
    """(Authorization 헤더 값, signed-date) 반환.

    message = datetime + method + path + query  (구분자 없이 그대로 이어붙임)
    """
    dt = signed_date(at)
    message = dt + method + path + (query or "")
    sig = hmac.new(secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()
    header = (
        f"CEA algorithm=HmacSHA256, access-key={{key}}, "
        f"signed-date={dt}, signature={sig}"
    )
    return header, dt


class CoupangPartners:
    def __init__(
        self,
        access_key: str,
        secret_key: str,
        sub_id: str = "",
        timeout: float = 20.0,
        session: requests.Session | None = None,
    ):
        if not access_key or not secret_key:
            raise ValueError("COUPANG_ACCESS_KEY / COUPANG_SECRET_KEY 가 필요합니다.")
        self.access_key = access_key
        self.secret_key = secret_key
        self.sub_id = sub_id
        self.timeout = timeout
        self.usage = Usage()
        self.session = session or requests.Session()
        self.session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})

    # ------------------------------------------------------------------ core
    def _headers(self, method: str, path: str, query: str) -> dict[str, str]:
        tpl, _ = sign(self.secret_key, method, path, query)
        return {"Authorization": tpl.format(key=self.access_key)}

    def _call(self, method: str, path: str, params: dict | None = None, body: dict | None = None) -> dict:
        query = build_query(params or {}) if method == "GET" else ""
        url = API_HOST + path + (f"?{query}" if query else "")
        headers = self._headers(method, path, query)
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8") if body else None

        for attempt in range(3):
            resp = self.session.request(method, url, headers=headers, data=payload, timeout=self.timeout)
            self.usage.hit()
            if resp.status_code < 300:
                return resp.json()
            # 서명 만료(401/403 중 시각 오차)나 일시 오류는 1회 재시도.
            if resp.status_code in (500, 502, 503, 504) and attempt < 2:
                time.sleep(2 * (attempt + 1))
                headers = self._headers(method, path, query)  # 서명 시각 갱신
                continue
            try:
                code = resp.json().get("rCode", "")
            except Exception:
                code = ""
            raise CoupangError(resp.status_code, resp.text, code)
        raise CoupangError(resp.status_code, resp.text)  # pragma: no cover

    # ------------------------------------------------------------- endpoints
    def search(self, keyword: str, limit: int = 20) -> list[dict]:
        """키워드 검색. 상위 limit개 (1~100)."""
        data = self._call(
            "GET",
            PATH_SEARCH,
            {"keyword": keyword, "limit": max(1, min(100, limit)), "subId": self.sub_id or None},
        )
        return _products(data)

    def goldbox(self, limit: int = 30) -> list[dict]:
        """오늘의 골드박스 (매일 자정 갱신되는 특가)."""
        data = self._call("GET", PATH_GOLDBOX, {"limit": max(1, min(100, limit)), "subId": self.sub_id or None})
        return _products(data)

    def best_category(self, category_id: int, limit: int = 20) -> list[dict]:
        """카테고리별 베스트. categoryId는 골드박스 응답의 categoryId 또는 API 문서에서 확인."""
        data = self._call(
            "GET",
            PATH_BEST.format(cid=category_id),
            {"limit": max(1, min(100, limit)), "subId": self.sub_id or None},
        )
        return _products(data)

    def deeplink(self, coupang_urls: Iterable[str]) -> dict[str, str]:
        """상품 URL 목록 → 제휴 단축 링크 매핑 {원본: 단축}.

        한 번에 최대 100개. 링크 1개당 1회 호출보다 훨씬 저렴하다.
        """
        urls = [u for u in coupang_urls if u][:100]
        if not urls:
            return {}
        data = self._call("POST", PATH_DEEPLINK, body={"coupangUrls": urls, "subId": self.sub_id or None})
        out: dict[str, str] = {}
        for row in data.get("data") or []:
            src = row.get("originalUrl") or row.get("coupangUrl") or ""
            dst = row.get("shortenUrl") or row.get("landingUrl") or ""
            if src and dst:
                out[src] = dst
        return out


def _products(data: dict) -> list[dict]:
    """응답에서 상품 배열만 뽑아낸다 (data.productData 형태)."""
    if not isinstance(data, dict):
        return []
    rows = data.get("data")
    if isinstance(rows, list):
        return rows
    if isinstance(rows, dict):
        for key in ("productData", "products", "item"):
            v = rows.get(key)
            if isinstance(v, list):
                return v
    return []
