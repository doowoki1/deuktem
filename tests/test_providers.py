"""토스/애드픽 정규화 로직 검증 (네트워크 불필요).

    python tests/test_providers.py
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from providers import adpick, toss  # noqa: E402

AT = datetime(2026, 11, 22, 13, 0, tzinfo=timezone(timedelta(hours=9)))


def test_toss_normalize_basic():
    r = {"tacaItemId": 12345, "name": "테스트 크림", "price": 11900,
         "originalPrice": 29000, "imageUrl": "https://img/x.jpg", "categoryName": "뷰티"}
    it = toss.normalize(r, AT)
    assert it and it["platform"] == "toss" and it["platform_label"] == "토스쇼핑"
    assert it["price"] == 11900 and it["base_price"] == 29000
    assert it["id"] == "toss-12345"


def test_toss_normalize_rejects_incomplete():
    assert toss.normalize({"name": "이름만", "price": 1000}, AT) is None
    assert toss.normalize({"tacaItemId": 1, "name": "", "price": 1000}, AT) is None
    assert toss.normalize({"tacaItemId": 1, "name": "가격없음"}, AT) is None


def test_toss_row_extraction_variants():
    for payload in (
        {"success": {"items": [{"a": 1}]}},
        {"data": {"products": [{"a": 1}]}},
        {"items": [{"a": 1}]},
    ):
        assert toss._rows(payload) == [{"a": 1}], payload


def test_adpick_cp_mapping():
    assert adpick.CP_TO_PLATFORM["KAKAO"] == ("kakao", "톡딜")
    assert adpick.CP_TO_PLATFORM["TOSS"] == ("toss", "토스쇼핑")


def test_adpick_normalize_kakao():
    r = {"cp_code": "KAKAO", "productName": "톡딜 니트", "price": "19,800",
         "productUrl": "https://example.com/p", "image": "https://img/y.jpg"}
    it = adpick.normalize(r, AT)
    assert it and it["platform"] == "kakao" and it["price"] == 19800
    assert it["platform_label"] == "톡딜"


def test_adpick_unknown_mall_falls_back_to_other():
    r = {"cp_code": "UNKNOWNMALL", "mallName": "처음보는몰", "productName": "상품",
         "price": 5000, "productUrl": "https://example.com/q"}
    it = adpick.normalize(r, AT)
    assert it["platform"] == "other" and it["platform_label"] == "처음보는몰"


def test_adpick_limits_are_per_endpoint():
    assert adpick.Adpick.LIMITS["search"] == 10
    assert adpick.Adpick.LIMITS["link"] == 60
    assert adpick.Adpick.LIMITS["malls"] == 60


def test_adpick_search_uses_q_param():
    import inspect
    src = inspect.getsource(adpick.Adpick.search)
    assert '"q"' in src and "keyword" not in src, "search 파라미터는 q 여야 함"


def test_providers_off_by_default():
    cfg = {"providers": {"toss": {"enabled": False}, "adpick": {"enabled": False}}}
    assert toss.collect(cfg, AT) == ([], [])
    assert adpick.collect(cfg, AT) == ([], [])


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok -", fn.__name__)
    print(f"\n{len(fns)}개 통과")
