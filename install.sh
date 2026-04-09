#!/usr/bin/env bash
# cokac 설치 스크립트
set -e
COKAC_DIR="$HOME/.cokac"
cd "$COKAC_DIR"

echo "=== cokac 설치 ==="

# 1. 가상환경
if [ ! -d ".venv" ]; then
  python3 -m venv .venv
  echo "✅ 가상환경 생성됨"
fi
source .venv/bin/activate

# 2. 의존성 설치
pip install -q -r requirements.txt
echo "✅ 패키지 설치됨"

# 3. .env 파일 확인
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo "⚠️  ~/.cokac/.env 파일에 TELEGRAM_BOT_TOKEN을 입력하세요"
  echo "   nano ~/.cokac/.env"
else
  echo "✅ .env 파일 존재"
fi

# 4. 데이터 디렉토리
mkdir -p data uploads
echo "✅ 디렉토리 준비됨"

# 5. launchd 등록
PLIST_TMPL="$COKAC_DIR/com.cokac.plist.template"
PLIST_SRC="$COKAC_DIR/com.cokac.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.cokac.plist"
sed "s|{HOME}|$HOME|g" "$PLIST_TMPL" > "$PLIST_SRC"
if [ -f "$PLIST_DST" ]; then
  launchctl unload "$PLIST_DST" 2>/dev/null || true
fi
cp "$PLIST_SRC" "$PLIST_DST"
launchctl load "$PLIST_DST"
echo "✅ launchd 등록됨 (자동 시작 설정)"

echo ""
echo "=== 완료 ==="
echo "봇 시작: launchctl start com.cokac"
echo "봇 중지: launchctl stop com.cokac"
echo "로그 확인: tail -f ~/.cokac/bot.log"
echo "수동 실행: cd ~/.cokac && source .venv/bin/activate && python bot.py"
