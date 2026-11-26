"""data/deals.json → docs/index.html (정적 사이트 빌드)

  python build.py                  # docs/ 생성
  python build.py --demo-preview   # 빈 데이터로도 미리보기 생성

카드는 서버에서 HTML로 렌더링한다(SEO·광고 심사 대응). 필터/정렬만
클라이언트 JS가 처리하며, 데이터는 JSON으로도 함께 임베드한다.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import shutil
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))
ESC = lambda s: html.escape(str(s or ""), quote=True)  # noqa: E731

_IMG_CACHE: dict[str, str] = {}


def img_src(p) -> str:
    """http(s) URL은 그대로, 로컬 파일은 data URI로 인라인 (데모 미리보기용)."""
    p = str(p or "")
    if p.startswith(("http://", "https://", "data:")):
        return html.escape(p, quote=True)
    fp = ROOT / p
    if fp.is_file():
        import base64
        import mimetypes
        if p not in _IMG_CACHE:
            mime = mimetypes.guess_type(p)[0] or "image/jpeg"
            _IMG_CACHE[p] = f"data:{mime};base64," + base64.b64encode(fp.read_bytes()).decode()
        return _IMG_CACHE[p]
    return html.escape(p, quote=True)



# ------------------------------------------------------- manual curation
# 토스쇼핑·카카오톡딜은 블로거용 상품 API가 없어 자동 수집하지 않는다.
# 대신 data/manual_items.json 에 사람이 링크를 넣고, 빌드가 합쳐서 렌더한다.
PLAT_NAMES = {"coupang": "쿠팡", "toss": "토스쇼핑", "kakao": "톡딜", "other": "기타"}
PLAT_CLASS = {"coupang": "coupang", "toss": "toss", "kakao": "kakao"}
PLAT_ORDER = ["coupang", "toss", "kakao", "other"]
MANUAL_DEFAULT = ROOT / "data" / "manual_items.json"


def _parse_dt(v):
    if not v:
        return None
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=KST)


def load_manual(path: Path = MANUAL_DEFAULT, at: datetime | None = None) -> tuple[list[dict], list[str]]:
    """수동 큐레이션 파일 → 사이트 스키마.

    반환: (items, warnings). 파일이 없으면 빈 목록 — 빌드는 계속된다.
    잘못된 항목은 버리고 경고만 남긴다(한 줄 오타로 사이트 전체가 죽지 않게).
    """
    at = at or datetime.now(KST)
    warn: list[str] = []
    if not path.is_file():
        return [], [f"{path.name} 없음 — 수동 큐레이션 건너뜀"]

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        return [], [f"{path.name} JSON 오류: {e}"]

    rows = raw.get("items") if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        return [], [f"{path.name} 형식 오류 — items 배열이 필요합니다"]

    out: list[dict] = []
    for n, r in enumerate(rows, 1):
        if not isinstance(r, dict):
            warn.append(f"#{n} 객체 아님")
            continue
        plat = str(r.get("platform", "")).lower().strip()
        if plat not in PLAT_NAMES:
            warn.append(f"#{n} platform 값 오류({plat!r}) — coupang|toss|kakao|other")
            continue
        name = str(r.get("name") or "").strip()
        url = str(r.get("url") or "").strip()
        price = to_int(r.get("price"))
        if not name or not url.startswith(("http://", "https://")) or price < 0:
            warn.append(f"#{n} 필수값 누락(name/price/http url)")
            continue

        ends = _parse_dt(r.get("ends_at"))
        if ends and ends < at:
            warn.append(f"#{n} 마감 지남({r.get('ends_at')}) — 제외")
            continue

        base = to_int(r.get("base_price")) or price
        if base < price:
            base = price
        drop = round((1 - price / base) * 100) if base > price else 0
        label = ""
        if ends:
            label = "~" + ends.astimezone(KST).strftime("%m.%d %H:%M") + " 마감"

        out.append({
            "id": f"manual-{plat}-{n}",
            "price_unknown": price == 0,
            "original_price": to_int(r.get("original_price")) or None,
            "image_kind": str(r.get("image_kind") or ""),
            "name": name,
            "price": price,
            "base_price": base,
            "high": base,
            "low": price,
            "drop": base - price,
            "drop_pct": drop,
            "image": (str(r.get("image_embedded")) if isinstance(r.get("image_embedded"), str) and len(r["image_embedded"]) <= 1400000 and re.fullmatch(r"data:image/(?:jpeg|png|webp);base64,[A-Za-z0-9+/]+={0,2}", r["image_embedded"]) else str(r.get("image") or "").strip()),
            "url": url,
            "category": str(r.get("category") or "기타").strip(),
            "keyword": "",
            "source": "manual",
            "platform": plat,
            "manual": True,
            "pinned": bool(r.get("pinned")),
            "memo": str(r.get("memo") or "").strip(),
            "ends_at": ends.isoformat(timespec="seconds") if ends else "",
            "ends_label": label,
            "rocket": False,
            "free_shipping": False,
            "first_seen": "",
            "last_seen": at.isoformat(timespec="seconds"),
            "history": [],
        })
    return out, warn



# ------------------------------------------------------------------ helpers
def to_int(v, default: int = 0) -> int:
    try:
        return int(float(str(v).replace(",", "").replace("원", "").strip()))
    except (TypeError, ValueError):
        return default


def won(n: int) -> str:
    return f"{int(n or 0):,}"

def display_price(item: dict) -> str:
    return won(item.get("price")) + "원" if item.get("price") else "가격은 쿠팡에서 확인"


def label_for(item: dict) -> tuple[str, str]:
    """(상단 배지, 하단 표기)"""
    src = item.get("source", "")
    if src == "manual":
        return ("직접등록", item.get("category") or "수동")
    if src == "goldbox":
        return ("골드박스", "오늘의특가")
    if src == "best":
        return ("베스트", item.get("category") or "베스트")
    return ("특가", item.get("keyword") or item.get("category") or "검색")


def spark(history: list, w: int = 96, h: int = 18) -> str:
    pts = [p for _, p in (history or [])][-20:]
    if len(pts) < 2:
        return '<svg class="sp" viewBox="0 0 96 18" aria-hidden="true"></svg>'
    lo, hi = min(pts), max(pts)
    if hi == lo:
        hi = lo + 1
    step = w / (len(pts) - 1)
    xy = " ".join(
        f"{round(i*step,1)},{round(h-2-(p-lo)/(hi-lo)*(h-4),1)}" for i, p in enumerate(pts)
    )
    return (
        f'<svg class="sp" viewBox="0 0 {w} {h}" preserveAspectRatio="none" aria-hidden="true">'
        f'<polyline points="{xy}" fill="none" stroke="currentColor" stroke-width="1.5" '
        f'vector-effect="non-scaling-stroke" stroke-linejoin="round"/></svg>'
    )


def price_panel(item: dict) -> tuple[str, float]:
    current = to_int(item.get("price"))
    original = to_int(item.get("original_price"))
    basis = "입력 정가" if item.get("manual") else "판매처 제공 정가"
    if not original and item.get("source") == "adpick_sdk":
        original = to_int(item.get("base_price"))
    if current <= 0:
        return '<div class="deal-pricing"><div class="deal-missing">가격은 판매처에서 확인</div></div>', 0
    if original > current:
        saved = original - current
        rate = (saved * 1000 // original) / 10
        return (f'<div class="reference-price"><div class="reference-line"><span class="reference-current num">{won(current)}원</span><del class="reference-original num" title="{basis}">{won(original)}원</del></div>'
                f'<div class="reference-saving num">{won(saved)}원 할인</div></div>'), rate

    high = to_int(item.get("high"))
    note = f'관측 최고가 {won(high)}원 대비 {won(high-current)}원 하락' if high > current else '정가 정보 미제공'
    return (f'<div class="reference-price"><div class="reference-line"><span class="reference-current num">{won(current)}원</span></div><div class="reference-note">{note}</div></div>'), 0



def card(item: dict, eager: bool = False) -> str:
    badge, sub = label_for(item)
    plat = item.get("platform") or "coupang"
    pcls = plat if plat in PLAT_CLASS else "other"
    pname = item.get("platform_label") or PLAT_NAMES.get(plat, plat.upper())
    drop = item.get("drop_pct", 0) or 0
    high = item.get("high") or item.get("base_price") or item.get("price")
    seen = (item.get("last_seen") or "")[11:16]
    flags = []
    if item.get("rocket"):
        flags.append('<span class="ship">로켓배송</span>')
    if item.get("free_shipping"):
        flags.append("<span>무료배송</span>")
    flags.append(f'<span class="mono">{seen} 확인</span>')
    meta = '<span class="sepdot"></span>'.join(flags)

    pricing, drop = price_panel(item)
    sale_badge = f'<span class="reference-badge num">{drop:g}% 특가</span>' if drop else ""
    if item.get("manual"):
        tail = item.get("ends_label") or "직접 확인"
        sparkrow = (
            '<div class="sparkrow"><span class="manualnote">'
            f'{ESC(item.get("memo") or "직접 등록한 특가")}</span>'
            f'<span class="sparklab">{ESC(tail)}</span></div>'
        )
    else:
        sparkrow = (
            '<div class="sparkrow">'
            f'{spark(item.get("history"))}'
            f'<span class="sparklab">{won(item.get("low") or item["price"])}원 최저</span>'
            '</div>'
        )
    image_url = img_src(item.get('image'))
    image_attrs = f'src="{image_url}" loading="eager"' if eager else f'data-src="{image_url}" class="preload-image"'
    fallback = '' if eager else f'<noscript><img src="{image_url}" alt="{ESC(item["name"])}" loading="lazy" decoding="async"></noscript>'
    thumb_class = "thumb banner-thumb" if item.get("image_kind") == "affiliate_banner" else "thumb"
    return f"""      <article class="card" data-cat="{ESC(item.get('category'))}" data-price="{item['price']}" data-drop="{drop}" data-ts="{ESC(item.get('last_seen'))}" data-plat="{plat}">
        <a class="card-link" href="{ESC(item.get('url'))}" target="_blank" rel="nofollow sponsored noopener" aria-label="{ESC(item['name'])}">
          <div class="{thumb_class}">
            <span class="thumb-fallback" aria-hidden="true"><span class="tf-icon"></span>이미지 준비 중</span>
            <img {image_attrs} alt="{ESC(item['name'])}" decoding="async" referrerpolicy="no-referrer">{fallback}
            <span class="pbadge {pcls}"><i></i>{pname}</span>
            {sale_badge}
          </div>
          <div class="cbody">
            <p class="ctitle">{ESC(item['name'])}</p>
            {pricing}
            <div class="meta">{meta}</div>
            {sparkrow}
          </div>
        </a>
      </article>"""


def hero(item: dict) -> str:
    pricing, rate = price_panel(item)
    sale_badge = f'<span class="reference-badge num">{rate:g}% 특가</span>' if rate else ""
    platform = item.get("platform_label") or PLAT_NAMES.get(item.get("platform"), "특가")
    return f"""<a class="feature" href="{ESC(item.get('url'))}" target="_blank" rel="nofollow sponsored noopener">
      <div class="ftop"><span class="feature-kicker">오늘 눈여겨볼 특가</span><span class="feature-platform">{ESC(platform)}</span></div>
      <div class="fimg"><span class="thumb-fallback" aria-hidden="true"><span class="tf-icon"></span>이미지 준비 중</span>{sale_badge}<img src="{img_src(item.get('image'))}" alt="{ESC(item['name'])}" loading="eager" fetchpriority="high" decoding="async" referrerpolicy="no-referrer"></div>
      <p class="ftitle">{ESC(item['name'])}</p>
      {pricing}
      <div class="feature-action">판매처에서 상품 확인 <span aria-hidden="true">→</span></div>
    </a>"""


def ranks(items: list[dict]) -> str:
    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(it.get("category") or "기타", []).append(it)
    top = sorted(groups.items(), key=lambda kv: -len(kv[1]))[:3]
    cols = []
    def rank_discount(r):
        rate = price_panel(r)[1]
        return f"{rate:g}% 할인" if rate else ""
    for cat, rows in top:
        rows = sorted(rows, key=lambda x: (-(x.get("drop_pct") or 0), (x.get("price") or float("inf"))))[:3]
        body = "".join(
            f"""<a class="rrow" href="{ESC(r.get('url'))}" target="_blank" rel="nofollow sponsored noopener">
            <span class="rk">{n+1}</span><img src="{img_src(r.get('image'))}" alt="" loading="lazy" decoding="async">
            <div><div class="rt">{ESC(r['name'])}</div>
            <div class="rp num">{display_price(r)} <span class="rp-drop">{rank_discount(r)}</span></div></div></a>"""
            for n, r in enumerate(rows)
        )
        cols.append(f'<div class="rankcol"><h3>{ESC(cat)} <span>TOP 3</span></h3>{body}</div>')
    return "".join(cols)


# --------------------------------------------------------------------- main
def _site_base(site: dict) -> str:
    """canonical·OG에 쓸 절대 주소. config 값이 예시면 GitHub 저장소에서 유추한다."""
    base = str(site.get("base_url") or "").strip()
    if (not base) or ("example." in base):
        repo = os.environ.get("GITHUB_REPOSITORY", "")
        if "/" in repo:
            owner, name = repo.split("/", 1)
            base = f"https://{owner}.github.io/{name}"
        else:
            base = "https://example.github.io/deuktem"
    return base.rstrip("/") + "/"


def jsonld(items: list[dict], base: str, title: str) -> str:
    """검색엔진용 구조화 데이터(WebSite + ItemList). 상위 30건만 넣어 페이지 크기를 줄인다."""
    rows = []
    for n, it in enumerate(items[:30], 1):
        price = to_int(it.get("price"))
        url = str(it.get("url") or "")
        node = {"@type": "Product", "name": str(it.get("name") or ""), "url": url}
        image = str(it.get("image") or "")
        if image.startswith("https://"):
            node["image"] = image
        if price > 0:
            node["offers"] = {
                "@type": "Offer", "price": str(price), "priceCurrency": "KRW",
                "availability": "https://schema.org/InStock", "url": url,
            }
        rows.append({"@type": "ListItem", "position": n, "item": node})
    ld = {
        "@context": "https://schema.org",
        "@graph": [
            {"@type": "WebSite", "name": title.split(" — ")[0], "url": base, "inLanguage": "ko-KR"},
            {"@type": "ItemList", "name": title, "numberOfItems": len(items), "itemListElement": rows},
        ],
    }
    return json.dumps(ld, ensure_ascii=False).replace("</", "<\\/")


FAVICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="득템">'
    '<rect width="64" height="64" rx="15" fill="#0B4A3B"/>'
    '<text x="32" y="45" font-size="34" font-weight="700" text-anchor="middle" fill="#D8F25E"'
    ' font-family="system-ui,-apple-system,sans-serif">득</text></svg>'
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--out", default=str(ROOT / "docs"))
    ap.add_argument("--demo-preview", action="store_true")
    ap.add_argument("--manual", default=str(MANUAL_DEFAULT), help="수동 큐레이션 JSON 경로")
    args = ap.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8")) or {}
    site = cfg.get("site", {})
    data = json.loads((ROOT / "data" / "deals.json").read_text(encoding="utf-8"))
    api_items = data.get("items") or []

    at_guess = datetime.fromisoformat(data["generated_at"]) if data.get("generated_at") else datetime.now(KST)
    manual_items, manual_warn = load_manual(Path(args.manual), at=at_guess)
    for w in manual_warn:
        print(f"[manual] {w}")
    # 고정(pinned) 수동 항목을 맨 앞에, 나머지는 API 수집분 뒤에 붙인다.
    items = [i for i in manual_items if i["pinned"]] + api_items + [i for i in manual_items if not i["pinned"]]

    if not items and not args.demo_preview:
        print("[fail] data/deals.json 에 상품이 없습니다. collect.py 를 먼저 실행하세요.")
        return 1

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tpl = (ROOT / "template.html").read_text(encoding="utf-8")
    css = (ROOT / "assets" / "base.css").read_text(encoding="utf-8")
    css += "\n.banner-thumb img{object-fit:contain;height:100%;width:100%}.banner-thumb{background:#fff}.card:hover .banner-thumb img{transform:none}"

    at = datetime.fromisoformat(data["generated_at"]) if data.get("generated_at") else datetime.now(KST)
    cats = sorted({i.get("category") for i in items if i.get("category")})
    seen_plat = {(i.get("platform") or "coupang") for i in items}
    plats = [p for p in PLAT_ORDER if p in seen_plat]
    if len(plats) > 1 and "other" in plats and len(seen_plat) == 1:
        plats = ["other"]
    stats = data.get("stats") or {}
    top = next((i for i in items if i.get("source") == "goldbox"), items[0] if items else None)

    tick = "".join(
        f'<span><b>{ESC((i.get("last_seen") or "")[11:16])}</b>{ESC(label_for(i)[0])} · {ESC(i["name"][:26])} '
        f'{display_price(i)}</span>'
        for i in items[:9]
    )

    base = _site_base(site)
    page_title = f"{site.get('name','득템')} — {site.get('tagline','오늘의 특가')}"
    og_desc = (f"쿠팡 골드박스·카테고리 베스트를 매시간 수집해 하락 폭이 큰 특가부터 보여줍니다. "
               f"{len(items)}건 · {at.strftime('%m.%d %H:%M')} 갱신.")
    repl = {
        "{{CSS}}": css,
        "{{TITLE}}": ESC(page_title),
        "{{SITE}}": ESC(site.get("name", "득템")),
        "{{TAGLINE}}": ESC(site.get("tagline", "")),
        "{{CANON}}": ESC(base),
        "{{OG_DESC}}": ESC(og_desc),
        "{{OG_IMAGE}}": ESC(base + "assets/og-cover.png"),
        "{{JSONLD}}": jsonld(items, base, page_title),
        "{{UPDATED}}": at.strftime("%m.%d %H:%M"),
        "{{DATE_LABEL}}": at.strftime("%Y.%m.%d %H:%M"),
        "{{SCHEDULE}}": ESC(cfg.get("schedule_label", "매시간")),
        "{{YEAR}}": str(at.year),
        "{{COUNT}}": str(len(items)),
        "{{NOTE}}": ESC(data.get("note") or ""),
        "{{CARD_COUNT}}": f"{len(items)}건",
        "{{HERO}}": hero(top) if top else "",
        "{{CARDS}}": "\n".join(card(i, eager=n < 8) for n, i in enumerate(items)) if items else '<p class="empty">표시할 특가가 없습니다. 다음 수집을 기다려 주세요.</p>',
        "{{RANKS}}": ranks(items) if items else "",
        "{{TICKER}}": tick + tick if tick else "",
        "{{PLAT_FILTERS}}": "".join(
            f'<button data-plat="{pl}" aria-pressed="false">'
            + ((next((i.get("platform_label") for i in items if (i.get("platform") or "coupang") == pl and i.get("platform_label")), None) or pl.upper()) if pl != "other" else "기타")
            + '</button>' for pl in plats
        ),
        "{{CATS}}": "".join(f'<button data-filter="{ESC(c)}" aria-pressed="false">{ESC(c)}</button>' for c in cats),
        "{{STATS}}": (
            f'<div class="stat"><div class="v num">{stats.get("count", len(items))}<small>건</small></div>'
            f'<div class="k">수집된 특가</div></div>'
            f'<div class="stat"><div class="v num">{stats.get("rocket", 0)}<small>건</small></div>'
            f'<div class="k">로켓배송</div></div>'
            f'<div class="stat"><div class="v num">{stats.get("avg_drop", 0)}<small>%</small></div>'
            f'<div class="k">평균 가격 하락</div></div>'
            + (f'<div class="stat"><div class="v num">{len(manual_items)}<small>건</small></div>'
               f'<div class="k">직접 등록</div></div>' if manual_items else "")
        ),
        "{{DATA_JSON}}": json.dumps(data, ensure_ascii=False).replace("</", "<\\/"),
    }

    page = tpl
    for k, v in repl.items():
        page = page.replace(k, v)

    (out / "index.html").write_text(page, encoding="utf-8")
    (out / "data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")

    # 검색 노출·공유용 부속 파일
    (out / "favicon.svg").write_text(FAVICON, encoding="utf-8")
    (out / "robots.txt").write_text(
        "User-agent: *\nAllow: /\nDisallow: /admin.html\n\n"
        f"Sitemap: {base}sitemap.xml\n", encoding="utf-8")
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
        f"  <url><loc>{base}</loc><lastmod>{at.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S+00:00')}</lastmod>"
        "<changefreq>hourly</changefreq><priority>1.0</priority></url>\n"
        "</urlset>\n", encoding="utf-8")
    for asset in ("og-cover.png", "apple-touch-icon.png"):
        src = ROOT / "assets" / asset
        if src.is_file():
            (out / "assets").mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, out / "assets" / asset)
    if (ROOT / "admin.html").is_file():
        shutil.copy2(ROOT / "admin.html", out / "admin.html")
    if Path(args.manual).is_file():
        shutil.copy2(Path(args.manual), out / "manual_items.json")

    demo_assets = ROOT / "assets" / "demo"
    if demo_assets.is_dir():
        shutil.copytree(demo_assets, out / "assets" / "demo", dirs_exist_ok=True)

    left = ["{{"] if "{{" in page else []
    print(f"[build] {out/'index.html'} · {len(items)}건 · {len(page)//1024}KB" + (f" · 미치환 {left}" if left else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
