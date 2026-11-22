#!/usr/bin/env bash
# GitHub 저장소 생성 → push → Pages 활성화 → 시크릿 등록까지 한 번에.
#
#   bash setup-github.sh <github-사용자명> [저장소명]
#
# 사전 준비:  gh auth login   (또는 export GH_TOKEN=...)
set -euo pipefail

OWNER="${1:?사용법: bash setup-github.sh <github-사용자명> [저장소명]}"
REPO="${2:-deuktem}"
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "▶ 1/6 저장소 생성: $OWNER/$REPO"
if gh repo view "$OWNER/$REPO" >/dev/null 2>&1; then
  echo "  이미 존재 — 그대로 사용합니다."
else
  gh repo create "$OWNER/$REPO" --public --description "쿠팡·애드픽 특가 자동 수집" --disable-wiki
fi

echo "▶ 2/6 git 초기화 및 push"
if [ ! -d .git ]; then
  git init -q
  git branch -M main
fi
git remote remove origin 2>/dev/null || true
git remote add origin "https://github.com/$OWNER/$REPO.git"
git add -A
git -c user.name="deuktem" -c user.email="deuktem@users.noreply.github.com" \
    commit -q -m "feat: 특가 수집 파이프라인 최초 커밋" 2>/dev/null || echo "  커밋할 변경 없음"
git push -u origin main

echo "▶ 3/6 애드픽 affid 시크릿 등록"
gh secret set ADPICK_AFFID --body "6ad2b6" --repo "$OWNER/$REPO"

echo "▶ 4/6 쿠팡 키 확인 (없으면 건너뜀)"
for k in COUPANG_ACCESS_KEY COUPANG_SECRET_KEY COUPANG_PARTNER_ID; do
  v="${!k:-}"
  if [ -n "$v" ]; then
    printf '%s' "$v" | gh secret set "$k" --repo "$OWNER/$REPO"
    echo "  등록: $k"
  else
    echo "  건너뜀: $k (나중에 Settings > Secrets 에서 추가)"
  fi
done

echo "▶ 5/6 GitHub Pages 활성화 (Source = GitHub Actions)"
gh api -X POST "repos/$OWNER/$REPO/pages" \
  -f "build_type=workflow" >/dev/null 2>&1 \
  && echo "  Pages 활성화 완료" \
  || gh api -X PUT "repos/$OWNER/$REPO/pages" -f "build_type=workflow" >/dev/null 2>&1 \
     && echo "  Pages 설정 갱신" \
     || echo "  ! Pages 자동 설정 실패 — Settings > Pages 에서 Source 를 'GitHub Actions' 로 직접 선택하세요."

echo "▶ 6/6 첫 수집 실행"
gh workflow run update.yml --repo "$OWNER/$REPO" 2>/dev/null && echo "  워크플로 시작됨" || echo "  ! Actions 탭에서 직접 Run workflow 하세요."

cat <<EOF

────────────────────────────────────────────
완료. 확인할 것:

  Actions   https://github.com/$OWNER/$REPO/actions
  Pages     https://github.com/$OWNER/$REPO/settings/pages
  사이트    https://$OWNER.github.io/$REPO/

워크플로가 끝나면 사이트 주소가 열립니다. (첫 배포는 1~2분)
매시간 7분에 자동으로 수집·빌드·배포됩니다.
────────────────────────────────────────────
EOF
