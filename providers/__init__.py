"""수집 프로바이더 레지스트리.

각 프로바이더는 collect(cfg, at) -> (items, warnings) 를 구현하고,
아이템은 build.py 가 이해하는 공통 스키마(dict)로 돌려준다.
"""
from . import adpick, adpick_sdk, toss  # noqa: F401

REGISTRY = {
    "coupang": None,        # collect.py 안에 내장 (HMAC 서명)
    "adpick_sdk": adpick_sdk.collect,   # 개인회원 핫딜 피드 (affid 만 필요)
    "toss": toss.collect,               # 토스 공식 쉐어링크 Open API
    "adpick": adpick.collect,           # 비즈 API (키·승인·IP 등록 필요)
}
