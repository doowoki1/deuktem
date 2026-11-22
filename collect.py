"""특가 수집기 — 쿠팡파트너스 API → data/deals.json

설계 원칙
  1. 크롤링하지 않는다. 공식 제휴 API만 쓴다.
  2. 시간당 호출 한도(검색 API 10회)를 코드가 스스로 지킨다.
     → data/state.json 에 요청 시각을 남기고, 60분 창에서 예산을 넘으면
       이번 실행을 조용히 끝내고 캐시된 데이터로 빌드한다.
  3. API가 죽어도 사이트는 살아 있다. 마지막 정상 데이터를 유지한다.

사용
  python collect.py                 # 실제 수집
  python collect.py --demo          # 키 없이 샘플 데이터 생성 (빌드 확인용)
  python collect.py --dry-run       # 호출 계획만 출력
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

from coupang import CoupangError, CoupangPartners
from providers import adpick, adpick_sdk, toss

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
CACHE = DATA / "deals.json"
STATE = DATA / "state.json"
KST = timezone(timedelta(hours=9))
WINDOW = 3600  # 초


# --------------------------------------------------------------------- utils
def now_kst() -> datetime:
    return datetime.now(KST)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def load_config(path: Path) -> dict:
    with path.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


# ------------------------------------------------------------------- budget
class Budget:
    """60분 슬라이딩 윈도우 안에서 나간 API 호출 수를 추적한다."""

    def __init__(self, limit: int, state_path: Path):
        self.limit = limit
        self.path = state_path
        state = load_json(state_path, {"calls": []})
        cutoff = time.time() - WINDOW
        self.calls = [t for t in state.get("calls", []) if isinstance(t, (int, float)) and t > cutoff]

    def remaining(self) -> int:
        return max(0, self.limit - len(self.calls))

    def take(self) -> bool:
        if self.remaining() <= 0:
            return False
        self.calls.append(time.time())
        self.save()
        return True

    def save(self) -> None:
        save_json(self.path, {"calls": self.calls})


# ---------------------------------------------------------------- transform
def to_int(v, default: int = 0) -> int:
    try:
        return int(float(str(v).replace(",", "").replace("원", "").strip()))
    except (TypeError, ValueError):
        return default


def normalize(raw: dict, category: str, keyword: str, source: str) -> dict | None:
    """쿠팡 응답 1건 → 사이트 스키마."""
    pid = str(raw.get("productId") or "").strip()
    name = str(raw.get("productName") or "").strip()
    price = to_int(raw.get("productPrice"))
    if not pid or not name or price <= 0:
        return None

    image = str(raw.get("productImage") or "").strip()
    if image.startswith("//"):
        image = "https:" + image

    return {
        "id": pid,
        "name": name,
        "price": price,
        "base_price": 0,          # 검색 API는 정가를 주지 않는다 → 추적 이력으로 계산
        "image": image,
        "url": str(raw.get("productUrl") or "").strip(),
        "rocket": bool(raw.get("isRocket")),
        "free_shipping": bool(raw.get("isFreeShipping")),
        "category": category,
        "keyword": keyword,
        "source": source,          # goldbox | search | best
        "first_seen": "",
        "last_seen": "",
        "low": price,              # 관측된 최저가
        "high": price,             # 관측된 최고가
        "history": [],             # [[ts, price], ...] 최근 40개
    }


def merge(cache: dict[str, dict], fresh: list[dict], at: datetime) -> dict[str, dict]:
    """새로 받은 상품을 캐시에 합치고, 가격 이력을 남긴다."""
    ts = at.isoformat(timespec="seconds")
    for item in fresh:
        old = cache.get(item["id"])
        if old:
            item["first_seen"] = old.get("first_seen") or ts
            item["low"] = min(old.get("low", item["price"]), item["price"])
            item["high"] = max(old.get("high", item["price"]), item["price"])
            item["history"] = (old.get("history") or [])[-39:]
            if not item["history"] or item["history"][-1][1] != item["price"]:
                item["history"].append([ts, item["price"]])
            # 오래된 링크/이미지가 비어 있으면 기존 값 유지
            for f in ("image", "url"):
                if not item[f] and old.get(f):
                    item[f] = old[f]
            item["source"] = item["source"] or old.get("source", "")
        else:
            item["history"] = [[ts, item["price"]]]
            item.setdefault("low", item["price"])
            item.setdefault("high", item["price"])
        item["last_seen"] = ts
        cache[item["id"]] = item
    return cache


def prune(cache: dict[str, dict], at: datetime, hours: int = 48) -> dict[str, dict]:
    cutoff = at - timedelta(hours=hours)
    out = {}
    for pid, item in cache.items():
        try:
            seen = datetime.fromisoformat(item["last_seen"])
        except (KeyError, ValueError):
            continue
        if seen >= cutoff:
            out[pid] = item
    return out


def derive(item: dict) -> dict:
    """표시용 파생 필드 (할인율·가격 변동)."""
    price, high = item["price"], item.get("high") or item["price"]
    drop = max(0, high - price)
    item["drop"] = drop
    item["drop_pct"] = round(drop / high * 100) if high > 0 and drop > 0 else 0
    # 쿠팡 검색 API에 정가가 없으므로 "관측 최고가 대비"를 할인 근거로 쓴다.
    item["best_price"] = item["price"] <= (item.get("low") or item["price"])
    return item


# -------------------------------------------------------------------- output
def write_output(cache: dict[str, dict], cfg: dict, at: datetime, note: str = "") -> dict:
    items = [derive(v) for v in cache.values()]
    # 노출 우선순위: 골드박스 > 로켓배송 > 나머지, 그 다음 가격 하락 폭
    rank = {"goldbox": 0, "best": 1, "search": 2}
    items.sort(key=lambda i: (rank.get(i.get("source", ""), 3), -i.get("drop_pct", 0), i["price"]))

    limit = int(cfg.get("collect", {}).get("max_items", 60))
    items = items[:limit]

    prices = [i["price"] for i in items] or [0]
    discounted = [i for i in items if i.get("drop_pct", 0) > 0]
    payload = {
        "generated_at": at.isoformat(timespec="seconds"),
        "generated_at_label": at.strftime("%m.%d %H:%M"),
        "source": "coupang-partners",
        "note": note,
        "stats": {
            "count": len(items),
            "rocket": sum(1 for i in items if i.get("rocket")),
            "drops": len(discounted),
            "avg_drop": round(sum(i["drop_pct"] for i in discounted) / len(discounted)) if discounted else 0,
            "min_price": min(prices),
            "cheapest": next((i["name"] for i in sorted(items, key=lambda x: x["price"])), ""),
        },
        "items": items,
    }
    save_json(CACHE, payload)
    return payload


# ---------------------------------------------------------------------- demo
def demo_payload(at: datetime) -> dict:
    """키 없이 빌드를 확인할 때 쓰는 고정 샘플. 실제 배포에는 쓰지 않는다."""
    fx = load_json(DATA / "demo_items.json", {"items": []})
    items = []
    for i in fx.get("items", []):
        it = dict(i)
        it.setdefault("first_seen", at.isoformat(timespec="seconds"))
        it["last_seen"] = at.isoformat(timespec="seconds")
        it.setdefault("low", it["price"])
        it.setdefault("high", it.get("base_price") or it["price"])
        it.setdefault("history", [[it["first_seen"], it["high"]], [it["last_seen"], it["price"]]])
        it.setdefault("source", "goldbox")
        it.setdefault("rocket", True)
        it.setdefault("free_shipping", True)
        items.append(derive(it))
    payload = {
        "generated_at": at.isoformat(timespec="seconds"),
        "generated_at_label": at.strftime("%m.%d %H:%M"),
        "source": "demo",
        "note": "DEMO — 샘플 데이터입니다. 실제 판매 정보가 아닙니다.",
        "items": items,
    }
    discounted = [i for i in items if i.get("drop_pct", 0) > 0]
    payload["stats"] = {
        "count": len(items),
        "rocket": sum(1 for i in items if i.get("rocket")),
        "drops": len(discounted),
        "avg_drop": round(sum(i["drop_pct"] for i in discounted) / len(discounted)) if discounted else 0,
        "min_price": min([i["price"] for i in items] or [0]),
        "cheapest": min(items, key=lambda x: x["price"])["name"] if items else "",
    }
    save_json(CACHE, payload)
    return payload


# --------------------------------------------------------------------- main
def plan(cfg: dict) -> list[tuple[str, str, str]]:
    """(source, 인자, 카테고리) 호출 계획."""
    c = cfg.get("collect", {})
    steps: list[tuple[str, str, str]] = []
    if c.get("goldbox", True):
        steps.append(("goldbox", "goldbox", "오늘의특가"))
    for cid in c.get("best_categories") or []:
        steps.append(("best", str(cid), ""))
    for kw in c.get("keywords") or []:
        if isinstance(kw, str):
            steps.append(("search", kw, ""))
        else:
            steps.append(("search", str(kw.get("q", "")), str(kw.get("cat", ""))))
    return [s for s in steps if s[1]]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--demo", action="store_true", help="API 없이 샘플 데이터 생성")
    ap.add_argument("--dry-run", action="store_true", help="호출 계획만 출력")
    ap.add_argument("--allow-empty", action="store_true", help="수집 0건이어도 성공 처리")
    ap.add_argument("--malls", action="store_true", help="애드픽 제휴몰 목록 조회(cp_code 확인)")
    ap.add_argument("--json", action="store_true", help="--malls 결과를 JSON으로도 출력")
    args = ap.parse_args()

    if args.malls:
        return adpick.print_malls(as_json=args.json)

    cfg = load_config(Path(args.config))
    at = now_kst()
    steps = plan(cfg)
    prov = cfg.get("providers", {}) or {}
    prov_on = {k: bool((prov.get(k) or {}).get("enabled")) for k in ("adpick_sdk", "toss", "adpick")}

    if args.demo:
        p = demo_payload(at)
        print(f"[demo] {p['stats']['count']}건 → {CACHE}")
        return 0

    if args.dry_run:
        budget_n = int(cfg.get("collect", {}).get("max_calls_per_hour", 8))
        print(f"쿠팡 계획 {len(steps)}콜 / 시간당 예산 {budget_n}콜")
        for s_ in steps:
            print("  -", s_)
        if len(steps) > budget_n:
            print("  ! 예산 초과 — config.yaml 의 키워드를 줄이세요.")
        for k, on in prov_on.items():
            print(f"  · {k}: {'ON' if on else 'off'}")
        return 0

    access = os.environ.get("COUPANG_ACCESS_KEY", "")
    secret = os.environ.get("COUPANG_SECRET_KEY", "")
    sub_id = os.environ.get("COUPANG_PARTNER_ID", "") or cfg.get("partner_id", "")

    cache = load_json(CACHE, {"items": []})
    prior = {i["id"]: i for i in cache.get("items", []) if i.get("id")}

    fresh: list[dict] = []
    errors: list[str] = []

    # ---------------------------------------------------------------- 쿠팡
    if access and secret:
        client = CoupangPartners(access, secret, sub_id=sub_id)
        budget = Budget(int(cfg.get("collect", {}).get("max_calls_per_hour", 8)), STATE)
        limit = int(cfg.get("collect", {}).get("per_call", 20))

        for i, (kind, arg, cat) in enumerate(steps):
            if budget.remaining() <= 0:
                print(f"[budget] 한도 소진 — {i}/{len(steps)} 단계에서 중단")
                break
            if i and kind == "search":
                time.sleep(1.2)
            try:
                budget.take()
                if kind == "goldbox":
                    raw, label = client.goldbox(limit=limit), "오늘의특가"
                elif kind == "best":
                    raw, label = client.best_category(int(arg), limit=limit), cat or "베스트"
                else:
                    raw, label = client.search(arg, limit=limit), cat or arg
                got = [n for n in (normalize(r, label, arg if kind == "search" else "", kind) for r in raw) if n]
                for g in got:
                    g.setdefault("platform", "coupang")
                    g.setdefault("platform_label", "쿠팡")
                fresh.extend(got)
                print(f"[ok] coupang:{kind}:{arg} → {len(got)}건")
            except CoupangError as e:
                errors.append(f"{kind}:{arg} {e.status}")
                print(f"[err] coupang:{kind}:{arg} → {e}", file=sys.stderr)
                if e.rate_limited:
                    print("[stop] 쿠팡 호출 한도/차단 — 즉시 중단", file=sys.stderr)
                    break
            except Exception as e:
                errors.append(f"{kind}:{arg} {type(e).__name__}")
                print(f"[err] coupang:{kind}:{arg} → {type(e).__name__}: {e}", file=sys.stderr)

        if fresh and cfg.get("collect", {}).get("use_deeplink", True) and budget.remaining() > 0:
            targets = [f["url"] for f in fresh if f.get("url")][:100]
            if targets:
                try:
                    budget.take()
                    mapping = client.deeplink(targets)
                    for f in fresh:
                        f["url"] = mapping.get(f["url"], f["url"])
                    print(f"[ok] coupang deeplink {len(mapping)}/{len(targets)}")
                except CoupangError as e:
                    print(f"[warn] deeplink 실패({e.status}) — 원본 URL 유지", file=sys.stderr)
    else:
        print("[skip] 쿠팡 키 미설정 — 쿠팡 수집 생략", file=sys.stderr)

    # ------------------------------------------------- 토스쇼핑 / 애드픽
    for key, fn in (("adpick_sdk", adpick_sdk.collect), ("toss", toss.collect), ("adpick", adpick.collect)):
        if not prov_on.get(key):
            continue
        try:
            got, warns = fn(cfg, at)
            for w in warns:
                print(f"[{key}] {w}", file=sys.stderr)
            fresh.extend(got)
            print(f"[ok] {key} → {len(got)}건")
        except Exception as e:
            errors.append(f"{key} {type(e).__name__}")
            print(f"[err] {key} → {type(e).__name__}: {e}", file=sys.stderr)

    # ------------------------------------------------------------- 저장
    merged = prune(merge(prior, fresh, at), at)
    if not merged and not args.allow_empty:
        print("[fail] 수집 결과 0건 — 기존 데이터도 없음", file=sys.stderr)
        return 1

    p = write_output(merged, cfg, at, note="일부 호출 실패" if errors else "")
    print(f"[done] {p['stats']['count']}건 (신규 {len(fresh)}) → {CACHE}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
