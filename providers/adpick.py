"""애드픽(Adpick) Open API — 여러 제휴몰을 한 키로 검색.

문서: https://biz.adpick.co.kr/?ac=api&sub=guide

  GET https://biz.adpick.co.kr/api/{apikey}/{function}?{params}
  · malls     제휴몰 목록            분당 60회
  · link      상품 URL → 커미션 링크  분당 60회
  · search?q={검색어}&limit=&cp_code=  분당 10회  (cp_code 최대 5개, 쉼표 구분)
  · best?area=today|commission|pick|popular&limit=  분당 10회 (limit 1~10)

  ※ search 파라미터명은 keyword 가 아니라 **q** 다.
  ※ 엔드포인트마다 한도가 달라서(60 vs 10) 스로틀을 함수별로 둔다.

키가 URL 경로에 들어가므로 **응답 로그·에러 메시지에 키를 남기지 않는다.**
이 API로 토스쇼핑·카카오 계열 몰이 실제로 잡히는지는
    python collect.py --malls
로 확인할 수 있다(목록에 없으면 그 몰은 애드픽 경유 불가).
"""
from __future__ import annotations

import os
import time
import urllib.parse

import requests

BASE = "https://biz.adpick.co.kr/api"
CP_TO_PLATFORM = {
    "COUPANG": ("coupang", "쿠팡"),
    "TOSS": ("toss", "토스쇼핑"),
    "TOSSSHOPPING": ("toss", "토스쇼핑"),
    "KAKAO": ("kakao", "톡딜"),
    "KAKAOCOMMERCE": ("kakao", "톡딜"),
}


def _num(v) -> int:
    try:
        return int(float(str(v).replace(",", "").replace("원", "").strip()))
    except (TypeError, ValueError):
        return 0


class Adpick:
    # 엔드포인트별 분당 한도
    LIMITS = {"malls": 60, "link": 60, "directlink": 60, "search": 10, "best": 10, "report": 10}

    def __init__(self, apikey: str, timeout: float = 20.0):
        self.key = apikey
        self.timeout = timeout
        self.session = requests.Session()
        self._last: dict[str, float] = {}

    def _throttle(self, fn: str) -> None:
        per_min = self.LIMITS.get(fn, 10)
        gap = 60.0 / per_min + 0.15
        wait = gap - (time.time() - self._last.get(fn, 0.0))
        if wait > 0:
            time.sleep(wait)
        self._last[fn] = time.time()

    def _get(self, fn: str, params: dict | None = None) -> dict:
        self._throttle(fn)
        q = "&".join(f"{k}={urllib.parse.quote(str(v))}" for k, v in (params or {}).items() if v not in (None, ""))
        url = f"{BASE}/{self.key}/{fn}" + (f"?{q}" if q else "")
        r = self.session.get(url, timeout=self.timeout)
        if r.status_code >= 300:
            # 키가 URL에 있으므로 예외 메시지에 URL을 넣지 않는다
            raise RuntimeError(f"adpick {fn} HTTP {r.status_code}")
        return r.json()

    def malls(self, reward_only: bool = False) -> list[dict]:
        d = self._get("malls", {"rewardmalls": str(bool(reward_only)).lower(), "order": "commission"})
        return d.get("data") or []

    def search(self, q: str, cp_code: str = "", limit: int = 20) -> list[dict]:
        """상품 검색. 파라미터명은 q. cp_code 는 쉼표로 최대 5개."""
        d = self._get("search", {"q": q, "cp_code": cp_code, "limit": max(1, min(20, limit))})
        data = d.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for k in ("items", "products", "list"):
                if isinstance(data.get(k), list):
                    return data[k]
        return []

    def best(self, area: str = "today", limit: int = 10) -> list[dict]:
        """베스트/추천 상품. area: today(실시간 베스트) | commission | pick | popular."""
        d = self._get("best", {"area": area, "limit": max(1, min(10, limit))})
        data = d.get("data")
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            for k in ("items", "products", "list"):
                if isinstance(data.get(k), list):
                    return data[k]
        return []

    def link(self, url: str) -> str:
        d = self._get("link", {"url": url})
        return ((d.get("data") or {}).get("commissionlink") or "")


def normalize(r: dict, at) -> dict | None:
    url = r.get("productUrl") or r.get("url") or r.get("link") or ""
    name = r.get("productName") or r.get("name") or r.get("title") or ""
    price = _num(r.get("price") or r.get("salePrice"))
    if not url or not name or price <= 0:
        return None
    cp = str(r.get("cp_code") or r.get("cpCode") or "").upper()
    plat, label = CP_TO_PLATFORM.get(cp, ("other", r.get("mallName") or "기타"))
    base = _num(r.get("originalPrice") or r.get("listPrice")) or price
    img = r.get("image") or r.get("imageUrl") or r.get("thumbnail") or ""
    if isinstance(img, dict):
        img = img.get("url", "")
    pid = str(r.get("productId") or r.get("id") or abs(hash(url)))
    return {
        "id": f"adpick-{cp.lower()}-{pid}",
        "name": str(name).strip(),
        "price": price,
        "base_price": max(base, price),
        "image": str(img),
        "url": url,                     # 커미션 링크로 교체됨
        "category": str(r.get("categoryName") or r.get("category") or "기타"),
        "keyword": "",
        "source": "adpick",
        "platform": plat,
        "platform_label": label,
        "rocket": False,
        "free_shipping": False,
        "first_seen": "",
        "last_seen": at.isoformat(timespec="seconds"),
        "history": [],
    }


def collect(cfg: dict, at) -> tuple[list[dict], list[str]]:
    p = cfg.get("providers", {}).get("adpick", {}) or {}
    warn: list[str] = []
    if not p.get("enabled"):
        return [], []
    key = os.environ.get("ADPICK_API_KEY", "") or p.get("api_key", "")
    if not key:
        return [], ["adpick: ADPICK_API_KEY 미설정 — 건너뜀"]

    cli = Adpick(key)
    limit = int(p.get("limit", 20))
    items: list[dict] = []

    # 1) 베스트/추천 상품 (핫딜 지면에 가장 가까운 API)
    for area in p.get("best_areas") or []:
        try:
            rows = cli.best(area=str(area), limit=min(10, limit))
        except Exception as e:
            warn.append(f"adpick: best({area}) 실패 {e}")
            continue
        got = [n for n in (normalize(r, at) for r in rows) if n]
        for g in got:
            g["keyword"] = f"베스트:{area}"
        items.extend(got)

    # 2) 키워드 검색
    for q in p.get("queries") or []:
        kw = q if isinstance(q, str) else q.get("q", "")
        cp = "" if isinstance(q, str) else str(q.get("cp_code") or "")
        if not kw:
            continue
        try:
            rows = cli.search(kw, cp_code=cp, limit=min(20, limit))
        except Exception as e:
            warn.append(f"adpick: 검색 '{kw}' 실패 {e}")
            continue
        got = [n for n in (normalize(r, at) for r in rows) if n]
        items.extend(got)

    # 상품 URL → 커미션 링크 (실패 시 원본 유지)
    if items and p.get("convert_links", True):
        for it in items:
            try:
                link = cli.link(it["url"])
                if link:
                    it["url"] = link
            except Exception as e:
                warn.append(f"adpick: 링크 변환 실패 1건 {e}")
                break
    return items, warn


def print_malls(as_json: bool = False) -> int:
    """제휴몰 목록을 출력하고, 토스/카카오 존재 여부를 한 줄로 판정한다."""
    import json as _json

    key = os.environ.get("ADPICK_API_KEY", "")
    if not key:
        print("ADPICK_API_KEY 환경변수가 필요합니다.")
        print("  1) https://biz.adpick.co.kr/ 로그인")
        print("  2) [API] > [API KEY] 에서 키 생성")
        print("  3) export ADPICK_API_KEY=발급받은키  (또는 GitHub Secrets 등록)")
        return 1

    try:
        rows = Adpick(key).malls()
    except Exception as e:
        print(f"조회 실패: {e}")
        print("  키 오류 또는 네트워크 문제일 수 있습니다. API 테스트 페이지에서 먼저 확인하세요.")
        return 1

    if as_json:
        print(_json.dumps(rows, ensure_ascii=False, indent=1))

    codes = {str(r.get("cp_code", "")).upper(): r for r in rows}
    if not as_json:
        print(f"제휴몰 {len(rows)}곳\n")
        print(f"  {'cp_code':<18}{'이름':<16}{'수수료'}")
        print("  " + "-" * 44)
        for r in sorted(rows, key=lambda x: str(x.get("cp_code", ""))):
            print(f"  {str(r.get('cp_code','?')):<18}{str(r.get('name','')):<16}{r.get('commission_per','')}%")

    def has(*keys):
        return [k for k in keys if k in codes]

    toss_hit = has("TOSS", "TOSSSHOPPING", "TOSSPAY")
    kakao_hit = has("KAKAO", "KAKAOCOMMERCE", "KAKAOTALK", "KAKAOSTORE")

    print()
    print("=" * 52)
    print(f"토스쇼핑 : {'있음 → ' + ', '.join(toss_hit) if toss_hit else '없음'}")
    print(f"카카오    : {'있음 → ' + ', '.join(kakao_hit) if kakao_hit else '없음'}")
    print("=" * 52)
    if toss_hit or kakao_hit:
        print("config.yaml 의 providers.adpick.queries 에 아래처럼 넣으세요:")
        for k in (toss_hit + kakao_hit)[:2]:
            print(f'  - {{ q: "무선 가습기", cp_code: "{k}" }}')
        print("providers.adpick.enabled: true 도 함께 켜야 합니다.")
    else:
        print("이 애드픽 계정의 제휴몰에 토스/카카오가 없습니다.")
        print("  → 토스는 공식 쉐어링크 API(providers.toss)로 직결하세요.")
        print("  → 카카오는 링크프라이스 핫딜 API 머천트 목록을 문의하세요.")
        print("  (제휴몰은 계정 등급·승인 상태에 따라 다를 수 있습니다.)")
    return 0
