#!/bin/bash
# Launch Meridian Pipeline Intelligence
#
# This script:
# 1. Loads environment variables from .env file (if present)
# 2. Activates the Python virtual environment
# 3. Starts the Streamlit app with light theme settings

set -e

# Get script directory and change to it
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load .env file if it exists (optional)
if [ -f .env ]; then
    echo "📁 Loading environment from .env..."
    set -a
    source .env
    set +a
fi

# Verify virtual environment exists
if [ ! -d .venv ]; then
    echo "❌ Virtual environment not found. Run: python setup.py"
    exit 1
fi

# Activate virtual environment
echo "🐍 Activating Python environment..."
source .venv/bin/activate

# Display startup info
if [ -n "$ANTHROPIC_API_KEY" ]; then
    echo "✅ ANTHROPIC_API_KEY is set — AI narration enabled"
else
    echo "ℹ️  ANTHROPIC_API_KEY not set — running in deterministic mode"
fi

# Start Streamlit with theme configuration
echo "🚀 Starting Meridian Pipeline Intelligence..."
echo "📱 Open: http://localhost:8501"
echo ""

exec streamlit run app.py \
  --theme.base light \
  --theme.primaryColor "#7C3AED" \
  --theme.backgroundColor "#F5F5F7" \
  --theme.secondaryBackgroundColor "#FFFFFF" \
  --theme.textColor "#1D1D1F"
