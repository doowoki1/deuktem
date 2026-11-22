"""토스쇼핑 쉐어링크 Open API.

문서: https://sharelink-docs.toss.im/developers/open-api

인증  OAuth2 client_credentials
      POST https://oauth2.cert.toss.im/token
      scope: "sharelink:read sharelink:write"
상품  GET  /openapi/products/best-selling?size=N
링크  POST /openapi/links   {publisherId, landingType, tacaItemId}

주의
  · 상품 조회는 **토스쇼핑이 인증한 크리에이터**만 가능하다(미인증 시 PARTNER_NOT_AUTHORIZED).
    링크 발급만 필요하면 인증 없이도 된다.
  · **출발지 IP 등록이 필수**다. GitHub Actions 는 IP가 매번 바뀌므로
    고정 IP 러너(VPS/self-hosted)에서 돌려야 한다. → ACCESS_DENIED 가 뜨면 이 원인.
  · 응답의 productUrl 은 추적 불가. 게시에는 반드시 발급된 shortUrl 을 쓴다.
  · 토큰은 캐시해서 재사용한다(매 호출 재발급 시 제한될 수 있음).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

TOKEN_URL = "https://oauth2.cert.toss.im/token"
BASE = "https://sharelink.toss.im/openapi"
SCOPE = "sharelink:read sharelink:write"
TOKEN_CACHE = Path(__file__).resolve().parent.parent / "data" / ".toss_token.json"


class TossError(RuntimeError):
    def __init__(self, status: int, payload, code: str = ""):
        super().__init__(f"HTTP {status} {code}: {str(payload)[:240]}")
        self.status = status
        self.code = code


def _num(v) -> int:
    try:
        return int(float(str(v).replace(",", "").replace("원", "").strip()))
    except (TypeError, ValueError):
        return 0


class Sharelink:
    def __init__(self, access_key: str, secret_key: str, publisher_id: str,
                 sub_tag_id: str = "", timeout: float = 20.0):
        self.access_key = access_key
        self.secret_key = secret_key
        self.publisher_id = publisher_id
        self.sub_tag_id = sub_tag_id
        self.timeout = timeout
        self.session = requests.Session()
        self._token = self._load_token()

    # ---------------------------------------------------------------- token
    def _load_token(self) -> str:
        try:
            t = json.loads(TOKEN_CACHE.read_text(encoding="utf-8"))
            if t.get("token") and t.get("exp", 0) > time.time() + 120:
                return t["token"]
        except (OSError, json.JSONDecodeError):
            pass
        return ""

    def token(self, force: bool = False) -> str:
        if self._token and not force:
            return self._token
        r = self.session.post(
            TOKEN_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": self.access_key,
                "client_secret": self.secret_key,
                "scope": SCOPE,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=self.timeout,
        )
        if r.status_code >= 300:
            raise TossError(r.status_code, r.text, "TOKEN")
        d = r.json()
        self._token = d.get("access_token", "")
        if not self._token:
            raise TossError(r.status_code, d, "TOKEN_EMPTY")
        try:
            TOKEN_CACHE.parent.mkdir(parents=True, exist_ok=True)
            TOKEN_CACHE.write_text(json.dumps(
                {"token": self._token, "exp": time.time() + int(d.get("expires_in", 3600))}
            ), encoding="utf-8")
        except OSError:
            pass
        return self._token

    # ------------------------------------------------------------------ call
    def _call(self, method: str, path: str, params=None, body=None) -> dict:
        headers = {"Authorization": f"Bearer {self.token()}"}
        r = self.session.request(method, BASE + path, headers=headers,
                                 params=params, json=body, timeout=self.timeout)
        if r.status_code == 401:
            headers = {"Authorization": f"Bearer {self.token(force=True)}"}
            r = self.session.request(method, BASE + path, headers=headers,
                                     params=params, json=body, timeout=self.timeout)
        try:
            d = r.json()
        except ValueError:
            raise TossError(r.status_code, r.text, "NOT_JSON")
        if r.status_code >= 300 or d.get("resultType") == "FAIL":
            err = d.get("error") or {}
            raise TossError(r.status_code, d, err.get("errorCode") or "")
        return d

    # ------------------------------------------------------------- endpoints
    def health(self) -> dict:
        return self._call("GET", "/health")

    def best_selling(self, size: int = 20) -> list[dict]:
        d = self._call("GET", "/products/best-selling", {"size": max(1, min(100, size))})
        return _rows(d)

    def links(self, targets: list[dict]) -> dict:
        """[{tacaItemId, ...}] → {tacaItemId: shortUrl}. landingType PRODUCT."""
        out = {}
        for t in targets[:20]:
            body = {"publisherId": self.publisher_id, "landingType": "PRODUCT"}
            if t.get("tacaItemId"):
                body["tacaItemId"] = t["tacaItemId"]
            elif t.get("tacaId"):
                body["tacaId"] = t["tacaId"]
            else:
                continue
            if self.sub_tag_id:
                body["subTagId"] = self.sub_tag_id
            try:
                d = self._call("POST", "/links", body=body)
                s = d.get("success") or {}
                url = s.get("shortUrl") or ""
                if url:
                    out[str(t.get("tacaItemId") or t.get("tacaId"))] = url
            except TossError:
                continue
        return out

    def landing_link(self, landing: str = "SHOPPING_DEALS") -> str:
        d = self._call("POST", "/links", body={"publisherId": self.publisher_id, "landingType": landing})
        return (d.get("success") or {}).get("shortUrl", "")


def _rows(d: dict) -> list[dict]:
    """응답에서 상품 배열만 방어적으로 추출 (success/items, data/items 등)."""
    for root in (d.get("success"), d.get("data"), d):
        if isinstance(root, list):
            return root
        if isinstance(root, dict):
            for k in ("items", "products", "content", "list"):
                v = root.get(k)
                if isinstance(v, list):
                    return v
    return []


def normalize(r: dict, at) -> dict | None:
    tid = r.get("tacaItemId") or r.get("tacaId") or r.get("id")
    name = r.get("name") or r.get("productName") or r.get("title") or ""
    price = _num(r.get("price") or r.get("salePrice") or r.get("finalPrice"))
    if not tid or not name or price <= 0:
        return None
    img = r.get("imageUrl") or r.get("image") or r.get("thumbnail") or ""
    if isinstance(img, dict):
        img = img.get("url", "")
    base = _num(r.get("originalPrice") or r.get("listPrice")) or price
    return {
        "id": f"toss-{tid}",
        "name": str(name).strip(),
        "price": price,
        "base_price": max(base, price),
        "image": str(img),
        "url": "",                       # 링크는 links() 로 채운다 (productUrl 은 추적 불가)
        "category": str(r.get("categoryName") or r.get("category") or "토스특가"),
        "keyword": "",
        "source": "toss",
        "platform": "toss",
        "platform_label": "토스쇼핑",
        "rocket": False,
        "free_shipping": False,
        "tacaItemId": tid,
        "first_seen": "",
        "last_seen": at.isoformat(timespec="seconds"),
        "history": [],
    }


def collect(cfg: dict, at) -> tuple[list[dict], list[str]]:
    p = cfg.get("providers", {}).get("toss", {}) or {}
    warn: list[str] = []
    if not p.get("enabled"):
        return [], []
    ak = os.environ.get("TOSS_ACCESS_KEY", "")
    sk = os.environ.get("TOSS_SECRET_KEY", "")
    pub = os.environ.get("TOSS_PUBLISHER_ID", "") or p.get("publisher_id", "")
    if not (ak and sk and pub):
        return [], ["toss: TOSS_ACCESS_KEY/SECRET_KEY/PUBLISHER_ID 미설정 — 건너뜀"]

    cli = Sharelink(ak, sk, pub, os.environ.get("TOSS_SUB_TAG_ID", "") or p.get("sub_tag_id", ""))
    size = int(p.get("size", 20))
    raw, code = [], ""
    try:
        raw = cli.best_selling(size=size)
    except TossError as e:
        code = e.code
        if e.code == "SHARELINK_OPENAPI_PARTNER_NOT_AUTHORIZED":
            warn.append("toss: 크리에이터 인증 필요(상품 조회 불가) — 링크만 사용 가능")
        elif e.code == "SHARELINK_OPENAPI_ACCESS_DENIED":
            warn.append("toss: 출발지 IP 미등록 — 고정 IP 러너에서 실행해야 함")
        else:
            warn.append(f"toss: 상품 조회 실패 {e.status} {e.code}")
        return [], warn

    items = [n for n in (normalize(r, at) for r in raw) if n]
    # 추적 링크 발급 (shortUrl 필수)
    if items and p.get("issue_links", True):
        mapping = cli.links([{"tacaItemId": i["tacaItemId"]} for i in items])
        for i in items:
            i["url"] = mapping.get(str(i["tacaItemId"]), "")
        missing = sum(1 for i in items if not i["url"])
        if missing:
            warn.append(f"toss: 링크 {missing}건 미발급 — 해당 카드는 원문 링크 없음")
    items = [i for i in items if i["url"]]
    return items, warn
