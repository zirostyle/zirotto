#!/bin/bash
# Lotto Auto Purchase - Main Workflow Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
# Use VENV_PYTHON if set, otherwise default to .venv python
if [ -z "$VENV_PYTHON" ]; then
    VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
fi

echo "🎰 Lotto Auto Purchase"
echo "========================================"
date "+%Y-%m-%d %H:%M:%S"
echo ""

# Send start notification
"$VENV_PYTHON" "$PROJECT_DIR/src/notify_telegram.py" start || true

# Run integrated auto purchase script (single browser session, single login)
echo "🚀 Starting integrated purchase workflow..."
if ! "$VENV_PYTHON" "$PROJECT_DIR/src/auto_purchase.py" 2>&1; then
    echo "❌ Error: Auto purchase failed"
    "$VENV_PYTHON" "$PROJECT_DIR/src/notify_telegram.py" error "Auto purchase workflow failed" || true
    exit 1
fi

echo ""
echo "✅ All tasks completed successfully!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Send completion notification
"$VENV_PYTHON" "$PROJECT_DIR/src/notify_telegram.py" complete
