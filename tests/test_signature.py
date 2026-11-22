"""서명·예산 로직 단위 테스트 (키 없이 실행 가능).

    python tests/test_signature.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from coupang import build_query, sign, signed_date, CoupangPartners  # noqa: E402


def test_signed_date_format():
    assert signed_date(0) == "700101T000000Z", signed_date(0)
    s = signed_date(1763000000)
    assert len(s) == 14 and s[6] == "T" and s[13] == "Z", s


def test_query_is_sorted_and_encoded():
    q = build_query({"keyword": "무선 가습기", "limit": 10, "subId": None})
    assert q.startswith("keyword="), q
    assert "subId" not in q, "빈 값은 쿼리에서 제외되어야 함"
    assert q.count("&") == 1, q
    # 공백은 %20 으로 (quote 기본)
    assert "%20" in q, q


def test_message_includes_datetime_prefix():
    """서명 대상 문자열은 datetime + method + path + query 여야 한다."""
    import hmac as _h, hashlib as _hl
    from coupang import signed_date
    at = 1763000000
    dt = signed_date(at)
    expect = _h.new(b"sk", (dt + "GET" + "/v2/x" + "keyword=a").encode(), _hl.sha256).hexdigest()
    hdr, _ = sign("sk", "GET", "/v2/x", "keyword=a", at=at)
    assert hdr.split("signature=")[1] == expect, hdr


def test_signature_stable():
    secret = "test-secret"
    a, dt = sign(secret, "GET", "/v2/x", "keyword=a&limit=10", at=1763000000)
    b, _ = sign(secret, "GET", "/v2/x", "keyword=a&limit=10", at=1763000000)
    assert a == b
    sig = a.split("signature=")[1]
    assert len(sig) == 64 and all(c in "0123456789abcdef" for c in sig), sig
    assert dt in a


def test_signature_changes_with_input():
    s1, _ = sign("k", "GET", "/v2/x", "keyword=a", at=0)
    s2, _ = sign("k", "GET", "/v2/x", "keyword=b", at=0)
    s3, _ = sign("k2", "GET", "/v2/x", "keyword=a", at=0)
    assert s1.split("signature=")[1] != s2.split("signature=")[1]
    assert s1.split("signature=")[1] != s3.split("signature=")[1]


def test_header_shape():
    c = CoupangPartners("AK", "SK", sub_id="affiliate-id")
    h = c._headers("GET", "/v2/x", "keyword=a&limit=10")["Authorization"]
    assert h.startswith("CEA algorithm=HmacSHA256, access-key=AK, signed-date="), h
    assert ", signature=" in h


def test_missing_keys_raise():
    try:
        CoupangPartners("", "")
    except ValueError:
        return
    raise AssertionError("키가 없으면 ValueError 여야 함")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print("ok -", fn.__name__)
    print(f"\n{len(fns)}개 통과")
