#!/bin/bash
# 로또 자동 구매 진입 스크립트
#
# 알림 전송 실패가 구매 자체를 막지 않도록 start/complete 알림은
# 실패를 허용하지만, 결과는 로그에 남깁니다.
# (기존에는 `|| true` 로 조용히 무시되어 알림 미동작을 인지할 수 없었습니다)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

if [ -z "${VENV_PYTHON:-}" ]; then
    VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
fi

if ! command -v "$VENV_PYTHON" >/dev/null 2>&1 && [ ! -x "$VENV_PYTHON" ]; then
    echo "❌ Python 실행 파일을 찾을 수 없습니다: $VENV_PYTHON"
    echo "   VENV_PYTHON 환경변수로 경로를 지정하세요."
    exit 1
fi

export PYTHONPATH="${PYTHONPATH:-$PROJECT_DIR/src}"
export PYTHONUNBUFFERED=1

echo "🎰 Lotto Auto Purchase"
echo "========================================"
date "+%Y-%m-%d %H:%M:%S %Z"
echo "Python: $($VENV_PYTHON --version 2>&1)"
echo "DRY_RUN=${DRY_RUN:-0}  DEBUG=${DEBUG:-0}"
echo ""

notify() {
    # $1: start|complete|error, $2: (선택) 메시지
    if ! "$VENV_PYTHON" "$PROJECT_DIR/src/notify_telegram.py" "$@"; then
        echo "⚠️  '$1' 텔레그램 알림 전송에 실패했습니다 (구매 절차는 계속 진행)."
    fi
}

notify start

echo "🚀 통합 구매 워크플로우 시작"
set +e
"$VENV_PYTHON" "$PROJECT_DIR/src/auto_purchase.py"
EXIT_CODE=$?
set -e

if [ $EXIT_CODE -ne 0 ]; then
    echo ""
    echo "❌ 구매 워크플로우가 실패했습니다 (exit=$EXIT_CODE)"
    notify error "구매 워크플로우 실패 (exit=$EXIT_CODE). Actions 로그를 확인하세요."
    exit $EXIT_CODE
fi

echo ""
echo "✅ 모든 작업이 완료되었습니다."
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 완료 요약 알림은 auto_purchase.py 가 이미 전송합니다.
# 여기서는 스크립트 레벨 종료만 로그로 남깁니다.
exit 0
