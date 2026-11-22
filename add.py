"""쿠팡 특가를 수동으로 등록하는 CLI (API 키 불필요).

쿠팡파트너스 웹에서 [링크 생성]으로 만든 제휴 링크를 그대로 넣으면 됩니다.
같은 일을 반복하지 않도록 대화형 입력·중복 검사·즉시 빌드까지 붙였습니다.

  python add.py                                  # 대화형으로 한 건 추가
  python add.py -u URL -n "상품명" -p 15900 -b 39900 -c 생활
  python add.py -u URL -n "상품명" -p 15900 --pinned --build
  python add.py --list                           # 등록된 항목 보기
  python add.py --remove 3                       # 3번 항목 삭제
  python add.py --check                          # 형식 검사만

링크 만드는 곳: partners.coupang.com → 링크 생성 → 상품 링크 → 검색 → 복사
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MANUAL = ROOT / "data" / "manual_items.json"
KST = timezone(timedelta(hours=9))

SCHEMA = {
    "version": 1,
    "updated_at": "",
    "_schema": {
        "platform": "coupang | toss | kakao | other (필수)",
        "name": "상품명 (필수)",
        "price": "판매가 숫자 (필수)",
        "base_price": "비교 기준가. 없으면 price와 동일하게 처리",
        "image": "이미지 URL 또는 로컬 경로 assets/... (없으면 회색 박스)",
        "url": "제휴/공유 링크 http(s) 필수",
        "category": "사이트 필터에 그대로 노출됨",
        "ends_at": "ISO8601. 지나면 빌드에서 자동 제외. null 가능",
        "memo": "카드 하단에 표시할 한 줄 설명",
        "pinned": "true면 그리드 맨 앞으로",
    },
}


def load() -> dict:
    if MANUAL.is_file():
        try:
            d = json.loads(MANUAL.read_text(encoding="utf-8"))
            if isinstance(d, dict) and isinstance(d.get("items"), list):
                return d
        except json.JSONDecodeError as e:
            print(f"! {MANUAL.name} JSON 오류: {e}", file=sys.stderr)
            sys.exit(1)
    return dict(SCHEMA, items=[])


def save(d: dict) -> None:
    d["updated_at"] = datetime.now(KST).isoformat(timespec="seconds")
    d.pop("_schema", None) if False else None
    MANUAL.parent.mkdir(parents=True, exist_ok=True)
    MANUAL.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")


def ask(label: str, default: str = "", required: bool = False) -> str:
    while True:
        hint = f" [{default}]" if default else (" (필수)" if required else " (엔터=건너뜀)")
        v = input(f"{label}{hint}: ").strip()
        if v:
            return v
        if default:
            return default
        if not required:
            return ""
        print("  값을 입력해 주세요.")


def build_item(a) -> dict:
    url = a.url
    name = a.name
    price = a.price
    base = a.base
    cat = a.category
    img = a.image or ""
    memo = a.memo or ""
    ends = a.ends or ""

    if not url:
        print("\n[쿠팡 파트너스 링크를 붙여넣으세요]")
        url = ask("제휴 링크", required=True)
    if not name:
        name = ask("상품명", required=True)
    if not price:
        while True:
            v = ask("판매가(원)", required=True)
            if v.replace(",", "").isdigit():
                price = v
                break
            print("  숫자만 입력하세요.")
    if not base:
        base = ask("정가(원, 모르면 엔터)")
    if not cat:
        cat = ask("카테고리", default="생활")
    if not memo:
        memo = ask("한 줄 메모")

    p = int(str(price).replace(",", ""))
    b = int(str(base).replace(",", "")) if str(base or "").replace(",", "").isdigit() else p
    if b < p:
        b = p
    if not url.startswith(("http://", "https://")):
        print("! 링크는 http(s)로 시작해야 합니다.", file=sys.stderr)
        sys.exit(1)
    if p <= 0:
        print("! 판매가는 0보다 커야 합니다.", file=sys.stderr)
        sys.exit(1)

    drop = round((1 - p / b) * 100) if b > p else 0
    return {
        "platform": "coupang",
        "name": name.strip(),
        "price": p,
        "base_price": b,
        "image": img.strip(),
        "url": url.strip(),
        "category": cat.strip() or "생활",
        "ends_at": ends or None,
        "memo": memo.strip() or ("-" + str(drop) + "% 특가" if drop else "쿠팡 특가"),
        "pinned": bool(getattr(a, "pinned", False)),
    }


def printable(it: dict, i: int) -> str:
    p, b = it.get("price", 0), it.get("base_price", 0) or it.get("price", 0)
    drop = round((1 - p / b) * 100) if b > p else 0
    flag = "★" if it.get("pinned") else " "
    return (f"{flag}{i:>2}. {p:>7,}원 (-{drop:>2}%) {it.get('platform',''):<8}"
            f"{it.get('category',''):<6}{it.get('name','')[:34]}")


def main() -> int:
    ap = argparse.ArgumentParser(description="쿠팡 특가 수동 등록 (API 키 불필요)")
    ap.add_argument("-u", "--url", help="쿠팡 파트너스 제휴 링크")
    ap.add_argument("-n", "--name", help="상품명")
    ap.add_argument("-p", "--price", help="판매가(원)")
    ap.add_argument("-b", "--base", help="정가(원)")
    ap.add_argument("-c", "--category", help="카테고리 (기본 생활)")
    ap.add_argument("-i", "--image", help="이미지 URL (없으면 빈 박스)")
    ap.add_argument("-m", "--memo", help="카드 하단 한 줄 메모")
    ap.add_argument("-e", "--ends", help="마감 시각 ISO8601 (지나면 자동 제외)")
    ap.add_argument("--pinned", action="store_true", help="그리드 맨 앞으로")
    ap.add_argument("--build", action="store_true", help="등록 후 build.py 실행")
    ap.add_argument("--list", action="store_true", help="등록 목록 보기")
    ap.add_argument("--remove", type=int, metavar="N", help="N번 항목 삭제")
    ap.add_argument("--check", action="store_true", help="형식 검사만 (사이트 빌드 없이)")
    args = ap.parse_args()

    d = load()

    if args.list:
        items = d.get("items") or []
        if not items:
            print("등록된 항목이 없습니다.")
            return 0
        print(f"수동 등록 {len(items)}건  (마지막 수정: {d.get('updated_at','-')})\n")
        for i, it in enumerate(items, 1):
            print(printable(it, i))
        return 0

    if args.remove is not None:
        items = d.get("items") or []
        if not 1 <= args.remove <= len(items):
            print(f"! 1~{len(items)} 사이를 지정하세요.", file=sys.stderr)
            return 1
        gone = items.pop(args.remove - 1)
        d["items"] = items
        save(d)
        print(f"삭제: {gone.get('name','')[:40]}  (남은 {len(items)}건)")
        return 0

    if args.check:
        from build import load_manual
        items, warns = load_manual(MANUAL, at=datetime.now(KST))
        print(f"유효 {len(items)}건 / 경고 {len(warns)}건")
        for w in warns:
            print("  -", w)
        return 0 if not warns else 1

    item = build_item(args)
    items = d.get("items") or []
    if any(it.get("url") == item["url"] for it in items):
        print("! 이미 등록된 링크입니다 — 건너뜁니다.", file=sys.stderr)
        return 0
    items.append(item)
    d["items"] = items
    save(d)

    print(f"\n등록 완료 → {len(items)}건")
    print("  " + printable(item, len(items)))
    print(f"  링크: {item['url'][:70]}")

    if args.build:
        print("\n빌드 중...")
        r = subprocess.run([sys.executable, str(ROOT / "build.py")], cwd=ROOT)
        if r.returncode != 0:
            print("! 빌드 실패", file=sys.stderr)
            return r.returncode
    else:
        print("\n반영하려면: python build.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
