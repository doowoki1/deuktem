# 득템 — 쿠팡 특가 자동 수집 사이트

쿠팡파트너스 **공식 API**로 특가를 모아 정적 사이트로 배포하는 세트입니다.
크롤링하지 않으므로 차단·약관 위험이 없고, 서버·DB 없이 GitHub Actions + Pages로만 돌아갑니다.

```
collect.py ──▶ data/deals.json ──▶ build.py ──▶ docs/index.html ──▶ GitHub Pages
   (API)          (캐시·가격이력)      (HTML 렌더)      (정적)
```

## 1. 준비 (10분)

1. **쿠팡파트너스 가입** → https://partners.coupang.com/ → 승인 후
   마이페이지 > **API 키 발급**(Access Key / Secret Key)과 **추천인 ID(subId)** 확인
2. 이 폴더를 그대로 GitHub 저장소로 올립니다(Public이면 Pages 무료).
3. 저장소 **Settings > Secrets and variables > Actions** 에 3개 등록:

   | Secret | 값 |
   |---|---|
   | `COUPANG_ACCESS_KEY` | 액세스 키 |
   | `COUPANG_SECRET_KEY` | 시크릿 키 |
   | `COUPANG_PARTNER_ID` | 추천인 ID(예: `AF0000000`) |

4. **Settings > Pages** → Source 를 `GitHub Actions` 로 변경.
5. **Actions > 특가 갱신 > Run workflow** 로 1회 수동 실행 → `docs/index.html` 생성 및 배포.

> 로컬에서 키 없이 화면만 보고 싶으면:
> ```bash
> pip install -r requirements.txt
> python collect.py --demo   # 샘플 데이터
> python build.py            # docs/index.html 생성
> ```

## 2. 설정은 `config.yaml` 하나로

```yaml
collect:
  max_calls_per_hour: 8      # 시간당 API 예산 (실제 한도 10)
  goldbox: true              # 오늘의 골드박스 (1콜)
  use_deeplink: true         # 제휴 단축링크 일괄 변환 (1콜)
  per_call: 20               # 호출당 상품 수
  max_items: 60              # 노출 상품 수
  best_categories: []        # 카테고리 베스트 ID (선택)
  keywords:
    - { q: "무선 가습기", cat: "생활" }
```

키워드를 추가하면 그만큼 호출이 늘어납니다. **`keywords` 개수 + 2 ≤ 8** 을 지키세요.
`python collect.py --dry-run` 으로 호출 계획을 먼저 확인할 수 있습니다.

## 3. 호출 한도 — 이 코드가 지키는 방식

쿠팡 검색 API는 **시간당 10회**이며, 초과하면 `403` → **24시간 정지**, 3회 누적 시 계정 제한입니다.
그래서:

- 크론은 **1시간에 1회**(`cron: "7 * * * *"`)만 돕니다.
- `data/state.json` 에 요청 시각을 남기고, 60분 창에서 예산(기본 8콜)을 넘으면 **스스로 중단**합니다.
- `403`/`429` 를 받으면 즉시 루프를 빠져나와 **캐시된 데이터로 빌드**합니다. 사이트는 죽지 않습니다.
- API가 전부 실패해도 마지막 정상 데이터가 그대로 배포됩니다.

> GitHub Actions 의 schedule 은 부하에 따라 수 분~수십 분 지연될 수 있습니다. 정확한 시각이 필요하면 외부 크론에서 `workflow_dispatch` 를 호출하세요. 또한 60일간 저장소 활동이 없으면 스케줄이 자동 비활성화됩니다.

## 4. 가격·할인율을 어떻게 계산하나

쿠팡 검색 API는 **정가를 주지 않습니다.** 그래서 `base_price` 를 지어내지 않고,
매 수집 가격을 `history` 에 쌓아 **관측 최고가 대비 하락률**을 표시합니다.
카드 하단 스파크라인도 이 이력에서 그립니다. 처음 본 상품은 `관측 최저` 배지가 붙습니다.

## 5. 파일 구조

```
coupang.py            HMAC 서명 + API 클라이언트 (goldbox / search / best / deeplink)
collect.py            수집·정규화·중복제거·가격이력·예산 가드
build.py              data/deals.json → docs/index.html (서버렌더 + JSON 임베드)
template.html         사이트 템플릿 ({{...}} 치환)
assets/base.css       스타일
data/deals.json       현재 상품 (커밋됨 — 캐시 역할)
data/state.json       호출 예산 기록 (커밋됨)
docs/                 배포 산출물 (Pages 루트)
tests/test_signature.py  서명 로직 테스트 (키 불필요)
```

## 6. 반드시 해야 하는 법적 처리

1. **대가성 고지** — 상단 띠 + 푸터에 이미 들어 있습니다. 지우지 마세요.
   공정위 「추천·보증 등에 관한 표시·광고 심사지침」 위반 소지가 있습니다.
2. **사업자등록·과세** — 제휴 수수료는 소득입니다. 규모가 커지면 사업자 등록과
   통신판매 관련 신고 필요 여부를 세무사에게 확인하세요.
3. **가격 정확성** — "최저가" 단정 대신 "수집 시점 기준"으로 표기(템플릿에 반영됨).
   `docs/index.html` 푸터의 사업자 정보 플레이스홀더를 실제 값으로 바꾸세요.
4. **이미지** — 상품 이미지는 API가 주는 URL을 그대로 씁니다(제휴 회원 약관 범위).
   직접 내려받아 재호스팅하지 마세요.

## 7. 다음 확장

- 토스쇼핑·톡딜은 블로거용 상품 API가 확인되지 않아 자동 수집 대상에서 제외했습니다.
  대신 `data/manual_items.json` 같은 수동 큐레이션 파일을 추가해 `build.py` 에서 합치는 방식이 현실적입니다.
- 상품 상세 페이지·카테고리별 랜딩을 만들려면 `build.py` 를 확장해 상품별 HTML을 생성하세요(SEO 유리).
- 방문자 분석은 GA4 또는 Cloudflare Web Analytics(무료·쿠키 없음)를 `template.html` 에 추가.

## 8. 알려진 제약

- 골드박스/베스트 응답 필드는 쿠팡이 예고 없이 바꿀 수 있습니다. `collect.py --dry-run` 후
  첫 실행 로그의 `→ N건` 이 0이면 `normalize()` 의 필드명을 확인하세요.
- 검색 API는 **가격 필터를 지원하지 않습니다.** 키워드를 좁혀서 해결합니다.
- `subId` 를 비우면 링크는 생성되지만 수익이 집계되지 않습니다.

## 9. 수동 큐레이션 (토스쇼핑·카카오톡딜)

토스쇼핑·톡딜은 블로거용 상품 API가 확인되지 않아 자동 수집에서 뺐습니다.
대신 `data/manual_items.json` 에 링크를 넣으면 `build.py` 가 합쳐서 렌더합니다.
**API 키 없이도 이 파일만으로 사이트를 운영할 수 있습니다.**

```json
{
  "items": [
    {
      "platform": "toss",              // coupang | toss | kakao | other
      "name": "저자극 수분 크림 80ml",
      "price": 11900,                 // 필수, 숫자
      "base_price": 29000,            // 비교 기준가 (없으면 price)
      "image": "assets/manual/cream.jpg",   // URL 또는 로컬 경로
      "url": "https://sharelink.toss.im/...",  // 필수, http(s)
      "category": "뷰티",
      "ends_at": "2026-11-23T23:59:59+09:00",  // 지나면 자동 제외, null 가능
      "memo": "토스 제휴링크 · 가격 직접 확인",
      "pinned": false                 // true면 그리드 맨 앞
    }
  ]
}
```

동작 규칙:

- `ends_at` 이 지난 항목은 **빌드에서 자동으로 빠집니다**(파일은 그대로 둬도 됨).
- 한 항목이 잘못돼도 사이트는 죽지 않습니다. 해당 줄만 건너뛰고 `[manual] #3 ...` 경고를 출력합니다.
- 파일이 없거나 JSON이 깨져도 빌드는 계속됩니다(경고만).
- `platform` 값에 따라 카드 배지·플랫폼 필터가 자동 생성됩니다.
- 수동 항목은 가격 이력이 없으므로 스파크라인 대신 `memo` 와 `ends_at` 이 표시됩니다.

검증:

```bash
python tests/test_manual.py     # 형식·만료·오타 처리 5개 케이스
python build.py                 # [manual] 경고가 나오면 해당 줄을 확인
```

이미지는 `assets/manual/` 에 넣고 상대 경로로 참조하세요. 외부 URL을 써도 되지만
상대 경로가 배포 후 깨지지 않아 안전합니다. **타사 상품 이미지를 재호스팅하는 것은
제휴 약관 위반일 수 있으니**, 직접 촬영·제작한 이미지나 공식 제휴 소재만 쓰세요.

## 10. 정정 — 토스쇼핑은 자동 수집 가능합니다

앞선 버전에서 "토스·카카오는 API가 없다"고 적었는데 **토스는 틀렸습니다.** 실제로 확인된 경로:

### 10-1. 토스쇼핑 쉐어링크 Open API (공식, 상품 조회 + 링크 발급)

문서: https://sharelink-docs.toss.im/developers/open-api

```bash
# 1) 토큰 (client_credentials)
POST https://oauth2.cert.toss.im/token
  grant_type=client_credentials&client_id=ACCESS&client_secret=SECRET
  &scope=sharelink:read sharelink:write

# 2) 상품 조회 (인증 크리에이터만)
GET https://sharelink.toss.im/openapi/products/best-selling?size=20

# 3) 추적 링크 발급 (수익은 이 링크로만 집계)
POST https://sharelink.toss.im/openapi/links
  { "publisherId": "...", "landingType": "PRODUCT", "tacaItemId": 12345 }
```

`config.yaml`:
```yaml
providers:
  toss:
    enabled: true
    size: 20
    issue_links: true
```

시크릿: `TOSS_ACCESS_KEY` / `TOSS_SECRET_KEY` / `TOSS_PUBLISHER_ID` / `TOSS_SUB_TAG_ID`(선택)

**두 가지 실제 제약 (코드로 우회 불가):**

| 제약 | 증상 | 대응 |
|---|---|---|
| **출발지 IP 등록 필수** | `SHARELINK_OPENAPI_ACCESS_DENIED` | GitHub Actions 러너는 IP가 매번 바뀝니다. **고정 IP VPS / self-hosted runner**에서 실행하세요. |
| 상품 조회는 인증 크리에이터만 | `SHARELINK_OPENAPI_PARTNER_NOT_AUTHORIZED` | 어드민에서 크리에이터 인증 신청. 미인증이면 **링크 발급만** 가능(수동 URL에 shortUrl 생성). |

응답의 `productUrl` 은 추적되지 않습니다. 반드시 발급된 `shortUrl` 을 게시해야 수익이 잡힙니다 — 코드가 이걸 강제합니다(`url` 비어 있으면 카드 제외).

### 10-2. 애드픽 — 여러 제휴몰을 한 키로 (토스·카카오 포함 여부 확인 가능)

문서: https://biz.adpick.co.kr/?ac=api&sub=guide

```
GET https://biz.adpick.co.kr/api/{apikey}/malls?order=commission
GET https://biz.adpick.co.kr/api/{apikey}/search?keyword=가습기&cp_code=KAKAO
GET https://biz.adpick.co.kr/api/{apikey}/link?url={상품URL}
```

**먼저 제휴몰 목록을 확인하세요.** 애드픽에 토스/카카오가 없으면 이 경로로도 안 됩니다:

```bash
export ADPICK_API_KEY=발급받은키
python collect.py --malls        # cp_code 목록 출력
```

`cp_code` 가 `KAKAO`면 자동으로 톡딜 배지, `TOSS`면 토스쇼핑 배지가 붙습니다(모르는 몰은 `other` → 회색).
`config.yaml` 의 `providers.adpick.queries` 에 `{ q: "가습기", cp_code: "KAKAO" }` 처럼 넣으면 몰 한정 검색입니다.

분당 60회 제한이라 코드가 1초 간격으로 스로틀합니다. API 키가 URL 경로에 들어가므로 예외 메시지에 URL을 남기지 않도록 처리했습니다.

### 10-3. 카카오톡딜 — 전용 공개 API는 확인되지 않음

카카오는 **선물하기 큐레이터 / 톡어필리에이트**(크리에이터 대상)를 운영하지만, 톡딜 상품을 프로그래밍 방식으로 받아오는 공개 API는 문서에서 확인되지 않았습니다. 현실적인 경로는:

1. 애드픽/링크프라이스에 카카오가 제휴몰로 있으면 → `cp_code` 로 자동 수집 (10-2)
2. 없으면 → `data/manual_items.json` 수동 큐레이션 (9장)
3. 링크프라이스 **핫딜 API** — "각 머천트의 인기상품·최저가를 실시간으로 받는" 서비스가 존재합니다. 머천트 목록에 카카오가 있는지 문의 필요: https://www.linkprice.com/affiliate/views/affiliate_marketing/plus_service_api.html

### 10-4. 인벤 핫딜은 왜 되는가

인벤 핫딜 게시판은 자동 수집이 아니라 **사람이 직접 링크를 올리는 게시판**입니다(작성자·조회수·등록시각이 게시물마다 다름). 즉 "수동 큐레이션을 수천 명이 나눠 하는" 구조입니다. 혼자 운영할 때 같은 결과를 내려면 10-1~10-3 의 API 경로를 쓰거나, 9장 수동 큐레이션 + 크론을 조합해야 합니다.

### 10-5. 프로바이더 구조

```
providers/
├─ __init__.py     REGISTRY (coupang 은 collect.py 내장)
├─ toss.py         OAuth2 + best-selling + /links
└─ adpick.py       malls / search / link + 스로틀
```

새 수집원을 붙이려면 `collect(cfg, at) -> (items, warnings)` 만 구현하고
`providers/__init__.py` 의 `REGISTRY` 에 등록하면 `build.py` 는 손대지 않아도 됩니다.
아이템 스키마는 `platform`, `platform_label` 만 맞추면 나머지는 기존 카드 렌더러가 처리합니다.

## 11. "제휴몰 목록" 확인하는 3가지 방법

`cp_code`(제휴몰 코드)를 알아야 토스·카카오를 지정 검색할 수 있습니다. 편한 순서대로:

### 방법 A — 브라우저만 (터미널 불필요)

1. https://biz.adpick.co.kr/ 로그인 → **[API] > [API KEY]** → 키 생성
2. **[API] > [API 테스트]** 메뉴로 이동
3. 함수 `malls`, 파라미터 `order=commission` 으로 실행
4. 응답 JSON에서 `cp_code` 값을 확인 (`KAKAO`, `TOSS` 등)

애드픽이 제공하는 테스트 페이지를 쓰는 방식이라 설치할 게 없습니다.

### 방법 B — GitHub 버튼

1. 저장소 **Settings > Secrets and variables > Actions** → `ADPICK_API_KEY` 등록
2. **Actions 탭 > "제휴몰 목록 확인" > Run workflow** 클릭
3. 실행 결과의 **Summary** 화면에 표로 정리됩니다 (KAKAO/TOSS 존재 여부 판정 포함)

`.github/workflows/check-malls.yml` 이 담당합니다.

### 방법 C — 터미널

```bash
pip install -r requirements.txt
export ADPICK_API_KEY=발급받은키
python collect.py --malls          # 표 + 판정
python collect.py --malls --json   # 원본 JSON
```

출력 예:

```
제휴몰 42곳

  cp_code           이름            수수료
  --------------------------------------------
  COUPANG           쿠팡            3.0%
  KAKAO             카카오톡딜      5.0%
  ...

====================================================
토스쇼핑 : 없음
카카오    : 있음 → KAKAO
====================================================
config.yaml 의 providers.adpick.queries 에 아래처럼 넣으세요:
  - { q: "무선 가습기", cp_code: "KAKAO" }
providers.adpick.enabled: true 도 함께 켜야 합니다.
```

### 애드픽 가입이 막히면

`biz.adpick.co.kr` 는 **매체(사이트)를 보유한 비즈 회원** 대상으로 안내되어 있습니다.
개인 회원으로 가입이 어렵거나 사업자 정보를 요구받으면, 애드픽을 건너뛰고
**토스 공식 API(`providers.toss`)로 직결**하는 편이 빠릅니다.
카카오는 링크프라이스 핫딜 API 머천트 목록에 있는지 문의하거나
`data/manual_items.json` 수동 큐레이션으로 처리하세요.

## 12. 쿠팡을 API 없이 등록하기 (add.py)

쿠팡파트너스 API는 **최종 승인 + 15만원 이상 매출** 이후에 키가 나옵니다.
그 전에도 쿠팡 특가를 사이트에 올리는 방법이 있습니다 — **파트너스 웹에서 링크를 만들어 `add.py` 로 넣는 것**.

### 링크 만드는 곳 (승인 전에도 가능)

1. https://partners.coupang.com/ 로그인
2. 좌측 **링크 생성 > 상품 링크**
3. 상품 검색 → 링크 아이콘 클릭 → **복사**

> 승인 전에도 링크 생성이 됩니다. 15만원 매출을 만들어야 최종 승인 심사에 들어가므로,
> 링크 생성 자체는 그 이전 단계에서 가능해야 합니다.

### 등록 (한 줄)

```bash
python add.py -u "https://link.coupang.com/a/xxxxx" \
              -n "무선 미니 가습기 500ml" \
              -p 15900 -b 39900 -c 생활 \
              -m "골드박스 특가 · 오늘 23시 마감" \
              --pinned --build
```

| 옵션 | 의미 |
|---|---|
| `-u` | 제휴 링크 (필수) |
| `-n` | 상품명 (필수) |
| `-p` | 판매가 (필수) |
| `-b` | 정가 (없으면 판매가와 동일 → 할인율 0%) |
| `-c` | 카테고리 (기본 `생활`) — 필터 탭에 그대로 노출 |
| `-i` | 이미지 URL (없으면 회색 박스) |
| `-m` | 카드 하단 한 줄 메모 |
| `-e` | 마감 시각 ISO8601 — 지나면 빌드에서 자동 제외 |
| `--pinned` | 그리드 맨 앞으로 |
| `--build` | 등록 직후 `build.py` 실행 |

옵션을 비우면 **대화형으로 물어봅니다.** 링크만 붙여넣고 엔터엔터 하면 됩니다.

### 관리 명령

```bash
python add.py --list       # 등록 목록 (할인율·플랫폼·카테고리)
python add.py --remove 3   # 3번 삭제
python add.py --check      # 형식 검사 (경고 0건이면 정상)
```

- 같은 링크는 **중복 등록되지 않습니다.**
- `http(s)` 가 아닌 링크, 0원 이하 가격은 거부합니다.
- 등록하면 `data/manual_items.json` 에 저장되고, 다음 빌드부터 카드로 나옵니다.

### 현실적인 운영 팁

골드박스는 **매일 오전 7시**에 갱신됩니다. 하루 3~5개만 골라 등록해도
사이트가 "매일 새 특가가 올라오는 곳"으로 보입니다. 완전 자동보다 전환율이 높습니다.
크론으로 자동 갱신되는 애드픽 피드(11번가·홈쇼핑)와 섞이면 상품 구성도 다양해집니다.
