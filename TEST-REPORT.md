# 테스트 실행 결과

- 실행 일시: 2026-11-22 14:00:38 KST
- Python: Python 3.12.3
- 방식: pytest 없이 표준 라이브러리만으로 실행 (네트워크·API 키 불필요)

```
===== tests/test_signature.py =====
ok - test_header_shape
ok - test_message_includes_datetime_prefix
ok - test_missing_keys_raise
ok - test_query_is_sorted_and_encoded
ok - test_signature_changes_with_input
ok - test_signature_stable
ok - test_signed_date_format

7개 통과

===== tests/test_providers.py =====
ok - test_adpick_cp_mapping
ok - test_adpick_limits_are_per_endpoint
ok - test_adpick_normalize_kakao
ok - test_adpick_search_uses_q_param
ok - test_adpick_unknown_mall_falls_back_to_other
ok - test_providers_off_by_default
ok - test_toss_normalize_basic
ok - test_toss_normalize_rejects_incomplete
ok - test_toss_row_extraction_variants

9개 통과

===== tests/test_manual.py =====
ok - test_bad_rows_are_skipped_not_fatal
ok - test_base_below_price_is_clamped
ok - test_expired_item_dropped
ok - test_missing_file_is_soft
ok - test_valid_item_normalized

5개 통과
```

## 요약

| 파일 | 통과 |
|---|---|
| tests/test_signature.py | 7 |
| tests/test_providers.py | 9 |
| tests/test_manual.py | 5 |
| **합계** | **21개 통과** |

## 통과 항목

| 파일 | 검증 내용 |
|---|---|
| test_signature.py | HMAC 서명 문자열·헤더 형식·쿼리 정렬 |
| test_providers.py | 토스/애드픽 응답 정규화·엔드포인트 한도·파라미터명 |
| test_manual.py | 수동 큐레이션 형식·만료·오타 처리 |

## 이번 수정에서 추가된 테스트

- `test_message_includes_datetime_prefix` — 쿠팡 공식 예제대로 `datetime + method + path + query` 로 서명하는지 고정합니다.
  (수정 전에는 `method + path + query` 라 실제 키를 넣어도 401이 났습니다.)
- `test_adpick_search_uses_q_param` — 애드픽 search 파라미터가 `keyword` 가 아니라 `q` 인지 확인합니다.
- `test_adpick_limits_are_per_endpoint` — link·malls 60회 / search·best 10회 분리 확인
