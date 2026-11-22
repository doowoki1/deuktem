"""애드픽 개인회원 '쇼핑메이트 핫딜 상품 리스트 API'.

    GET https://adpick.co.kr/apis/sdk_shopping_hotdeal.php?affid={affid}

  · 필요한 건 **회원 아이디(affid) 하나**. API 키·비즈 승인·Whitelist 불필요.
  · 응답: [{ "title", "description", "list": [ {...} ] }]
    상품 필드: product_name, photo, mall, mall_name, mall_icon,
               price_sale, price_org, commission, buyurl
  · buyurl 은 이미 affid 가 박힌 추적 링크 → 가공하지 말고 그대로 쓴다.
  · Referer 없이 호출하면 403 이 날 수 있어 항상 붙인다.
  · 카테고리 정보가 없어 상품명 키워드로 분류한다(근사치, config 로 끌 수 있음).
"""
from __future__ import annotations

import os
import re

import requests

ENDPOINT = "https://adpick.co.kr/apis/sdk_shopping_hotdeal.php"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
    "Referer": "https://adpick.co.kr/",
    "Accept": "application/json, text/plain, */*",
}

# 상품명 키워드 → 사이트 카테고리 (첫 매치 우선)
CAT_RULES = [
    ("식품", ("과자", "커피", "차 ", "음료", "김치", "고기", "삼겹", "닭", "수산", "생선", "쌀", "라면",
              "간식", "빵", "디저트", "과일", "채소", "반찬", "밀키트", "햇반", "통조림", "견과", "홍삼")),
    ("뷰티", ("화장품", "크림", "세럼", "앰플", "로션", "토너", "마스크팩", "샴푸", "린스", "바디", "향수",
              "립", "쿠션", "파운데이션", "선크림", "클렌징", "네일", "헤어")),
    ("패션", ("티셔츠", "셔츠", "니트", "가디건", "자켓", "재킷", "코트", "패딩", "바지", "팬츠", "청바지",
              "원피스", "스커트", "신발", "운동화", "슬리퍼", "가방", "지갑", "양말", "속옷", "모자")),
    ("가전", ("가전", "냉장고", "세탁기", "청소기", "공기청정", "가습기", "선풍기", "히터", "에어컨",
              "전자레인지", "밥솥", "커피머신", "믹서", "토스터", "프라이팬", "냄비", "정수기")),
    ("디지털", ("이어폰", "헤드폰", "키보드", "마우스", "모니터", "노트북", "태블릿", "충전", "케이블",
                "보조배터리", "스피커", "웹캠", "ssd", "usb", "카메라")),
    ("생활", ("휴지", "물티슈", "세제", "섬유유연제", "수납", "정리", "욕실", "주방", "행거", "베개",
              "이불", "매트", "커튼", "방향제", "탈취", "살충", "건전지", "마스크")),
]
MALL_PLATFORM = (
    (("toss.im",), ("toss", "토스쇼핑")),
    (("kakao.com", "kakaotalk", "kakaostore"), ("kakao", "톡딜")),
    (("coupang.com",), ("coupang", "쿠팡")),
)


def price(v) -> int:
    """'8,910' / '12' / 8910 → int. 숫자 없으면 0."""
    s = re.sub(r"[^0-9.]", "", str(v or ""))
    try:
        return int(float(s)) if s else 0
    except ValueError:
        return 0


def category_of(name: str) -> str:
    low = name.lower()
    for cat, keys in CAT_RULES:
        if any(k.strip() in low for k in keys):
            return cat
    return "기타"


def platform_of(mall: str, mall_name: str) -> tuple[str, str]:
    low = (mall + " " + mall_name).lower()
    for keys, val in MALL_PLATFORM:
        if any(k in low for k in keys):
            return val
    return ("other", mall_name or "기타")


def fetch(affid: str, timeout: float = 25.0) -> list[dict]:
    r = requests.get(ENDPOINT, params={"affid": affid}, headers=HEADERS, timeout=timeout)
    if r.status_code == 403:
        raise RuntimeError("403 — Referer/UA 차단 또는 affid 오류")
    if r.status_code >= 300:
        raise RuntimeError(f"HTTP {r.status_code}")
    data = r.json()
    if isinstance(data, dict):
        data = [data]
    out: list[dict] = []
    for grp in data or []:
        if isinstance(grp, dict) and isinstance(grp.get("list"), list):
            out.extend(grp["list"])
    return out


def normalize(r: dict, at) -> dict | None:
    url = str(r.get("buyurl") or "").strip()
    name = str(r.get("product_name") or "").strip()
    p = price(r.get("price_sale"))
    org = price(r.get("price_org")) or p
    if not url or not name or p <= 0:
        return None
    # 데이터 오류 방어: 애드픽 피드에는 '12원', '999원(정가 20,000)' 같은
    # 잘린 가격이 섞여 있다. 90% 넘는 할인에 절대금액까지 낮으면 버린다.
    if p < 100:
        return None
    if org > 0 and p < org * 0.15 and p < 3000:
        return None
    plat, plabel = platform_of(str(r.get("mall", "")), str(r.get("mall_name", "")))
    # id 는 buyurl 전체의 해시. offer 파라미터는 몰 캠페인 단위라 상품마다
    # 겹친다(30건 중 offer 유니크 7개) → 그걸 쓰면 상품이 뭉개진다.
    import hashlib as _hl
    pid = _hl.sha1(url.encode("utf-8")).hexdigest()[:12]
    return {
        "id": f"sdk-{pid}",
        "name": name,
        "price": p,
        "base_price": max(org, p),
        "image": str(r.get("photo") or ""),
        "url": url,
        "category": category_of(name),
        "keyword": "",
        "source": "adpick_sdk",
        "platform": plat,
        "platform_label": plabel,
        "mall_name": str(r.get("mall_name") or ""),
        "commission": str(r.get("commission") or ""),
        "rocket": False,
        "free_shipping": False,
        "first_seen": "",
        "last_seen": at.isoformat(timespec="seconds"),
        "history": [],
    }


def collect(cfg: dict, at) -> tuple[list[dict], list[str]]:
    p = cfg.get("providers", {}).get("adpick_sdk", {}) or {}
    if not p.get("enabled"):
        return [], []
    affid = os.environ.get("ADPICK_AFFID", "") or str(p.get("affid") or "")
    if not affid:
        return [], ["adpick_sdk: ADPICK_AFFID 미설정 — 건너뜀 (애드픽 가이드 화면의 '귀하의 API URL' 참고)"]
    try:
        rows = fetch(affid)
    except Exception as e:
        return [], [f"adpick_sdk: {e}"]
    items = [n for n in (normalize(r, at) for r in rows) if n]
    warn = [] if items else ["adpick_sdk: 상품 0건 — 응답 형식 변경 여부 확인"]
    if p.get("max_items"):
        items = items[: int(p["max_items"])]
    return items, warn
