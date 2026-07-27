#!/bin/zsh
# Launch Meridian Pipeline Intelligence. Runs from the correct directory AND
# passes the light theme explicitly on the command line, so the app renders
# light no matter where it is launched from or what the OS dark-mode says.
cd "$(dirname "$0")"
source .venv/bin/activate
exec streamlit run app.py \
  --theme.base light \
  --theme.primaryColor "#7C3AED" \
  --theme.backgroundColor "#F5F5F7" \
  --theme.secondaryBackgroundColor "#FFFFFF" \
  --theme.textColor "#1D1D1F"
