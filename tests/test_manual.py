"""수동 큐레이션 로더 검증 (키·네트워크 불필요).

    python tests/test_manual.py
"""
import json
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import load_manual  # noqa: E402

KST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 22, 13, 0, tzinfo=KST)


def _write(payload):
    f = Path(tempfile.mkdtemp()) / "manual_items.json"
    f.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return f


def test_missing_file_is_soft():
    items, warn = load_manual(Path("/nonexistent/manual.json"), at=NOW)
    assert items == [] and warn, "파일이 없으면 빈 목록 + 경고"


def test_valid_item_normalized():
    f = _write({"items": [{
        "platform": "toss", "name": "테스트 크림", "price": 9900,
        "base_price": 19900, "url": "https://example.com/x",
        "category": "뷰티", "image": "", "memo": "메모",
    }]})
    items, warn = load_manual(f, at=NOW)
    assert len(items) == 1 and not warn, warn
    it = items[0]
    assert it["drop_pct"] == 50, it["drop_pct"]
    assert it["platform"] == "toss" and it["manual"] is True
    assert it["source"] == "manual"


def test_expired_item_dropped():
    past = (NOW - timedelta(days=1)).isoformat()
    f = _write({"items": [{
        "platform": "kakao", "name": "지난 특가", "price": 1000,
        "url": "https://example.com/y", "ends_at": past,
    }]})
    items, warn = load_manual(f, at=NOW)
    assert items == [] and any("마감" in w for w in warn), warn


def test_bad_rows_are_skipped_not_fatal():
    f = _write({"items": [
        {"platform": "naver", "name": "플랫폼 오타", "price": 1000, "url": "https://e.com/a"},
        {"platform": "toss", "name": "", "price": 1000, "url": "https://e.com/b"},
        {"platform": "toss", "name": "링크 없음", "price": 1000, "url": ""},
        {"platform": "toss", "name": "정상", "price": 5000, "url": "https://e.com/c"},
    ]})
    items, warn = load_manual(f, at=NOW)
    assert len(items) == 1 and items[0]["name"] == "정상", items
    assert len(warn) == 3, warn


def test_base_below_price_is_clamped():
    f = _write({"items": [{
        "platform": "coupang", "name": "이상한 기준가", "price": 20000,
        "base_price": 10000, "url": "https://e.com/d",
    }]})
    items, _ = load_manual(f, at=NOW)
    assert items[0]["base_price"] == 20000 and items[0]["drop_pct"] == 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok -", fn.__name__)
    print(f"\n{len(fns)}개 통과")
