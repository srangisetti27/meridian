# Meridian Pipeline Intelligence — Setup Guide

This guide covers installation, configuration, and troubleshooting for Meridian.

## Prerequisites

- **Python 3.9+** (check with `python --version`)
- **pip** package manager (included with Python)
- **Git** (for cloning the repository)
- **API Key** (optional, for AI narration feature)

## Installation Methods

### Method 1: Automated Setup (Recommended)

The fastest way to get started:

```bash
cd meridian-sales-intelligence
python setup.py
```

This script will:
- ✓ Verify Python version
- ✓ Create a virtual environment
- ✓ Install all dependencies
- ✓ Validate data integrity
- ✓ Report LLM availability
- ✓ Run 37 validation tests

### Method 2: Manual Setup

If you prefer manual control:

```bash
# Navigate to the project directory
cd meridian-sales-intelligence

# Create virtual environment
python -m venv .venv

# Activate it
# On macOS/Linux:
source .venv/bin/activate
# On Windows (PowerShell):
.venv\Scripts\Activate.ps1
# On Windows (Command Prompt):
.venv\Scripts\activate.bat

# Install dependencies
pip install -r requirements.txt

# Verify installation
python -m pytest tests/ -v
```

### Method 3: Docker

Perfect for production and consistent environments:

```bash
# Copy environment template
cp .env.example .env

# Edit .env and add your API keys
# Then start the container:
docker compose up

# Access at http://localhost:8501
```

---

## Configuration

### Optional: Enable AI Narration

The app works perfectly in deterministic mode. To add AI-powered narration:

#### Option A: Environment Variable

```bash
# Get your key at https://console.anthropic.com/account/keys
export ANTHROPIC_API_KEY=sk-ant-...

# Restart the app
streamlit run app.py
```

#### Option B: .env File

```bash
# Copy the example file
cp .env.example .env

# Edit .env and add your key
ANTHROPIC_API_KEY=sk-ant-...

# The app will load it automatically on startup
streamlit run app.py
```

#### Option C: Docker

```bash
# Edit .env with your API keys
docker compose up

# Container loads .env automatically
```

### Alternative LLM Providers

If you don't have Anthropic API access, try Google Gemini:

```bash
# Set GEMINI_API_KEY instead
export GEMINI_API_KEY=...
streamlit run app.py
```

---

## Running the Application

### Standard Launch

```bash
# Deterministic mode (no LLM required)
streamlit run app.py

# With API key for AI narration
export ANTHROPIC_API_KEY=sk-ant-...
streamlit run app.py
```

### Using the Run Script

```bash
# Applies theme settings automatically
./run.sh
```

### Docker

```bash
docker compose up

# Stop with Ctrl+C or:
docker compose down
```

---

## Accessing the App

Once started, open your browser:

```
http://localhost:8501
```

You should see:
- Data validation status in the sidebar
- Progress bar showing Q2 completion (35% as of May 2, 2026)
- Chat interface for asking questions about pipeline

---

## Verification

### Quick Health Check

```bash
# Test that everything is installed correctly
python -c "
import config as C
import data_loader
import analytics
import llm_layer

print('✓ Core modules loaded')
print(f'✓ LLM: {llm_layer.provider_label()}')
"
```

### Run Tests

```bash
# Run all 37 validation tests
python -m pytest tests/ -v

# Run specific test category
python -m pytest tests/test_analytics.py -v
python -m pytest tests/test_router.py -v
```

### Check LLM Availability

```bash
python -c "
import llm_layer
print(f'API Key Present: {bool(__import__(\"os\").environ.get(\"ANTHROPIC_API_KEY\"))}')
print(f'LLM Available: {llm_layer.is_llm_available()}')
print(f'Provider: {llm_layer.provider_label()}')
"
```

---

## Troubleshooting

### "Python not found"
Install Python 3.9+ from https://python.org

### "AI Narration Unavailable" message
This is normal! The app works fine without it. To enable:
1. Get an API key: https://console.anthropic.com/account/keys
2. Set it: `export ANTHROPIC_API_KEY=sk-ant-...`
3. Restart the app
4. Refresh your browser

### "Module not found" error
Dependencies didn't install correctly:
```bash
pip install -r requirements.txt --force-reinstall
```

### Data validation fails
Ensure CSV files exist:
```bash
ls data/Q1/deals.csv data/Q1/reps.csv data/Q2/deals.csv data/Q2/reps.csv
```

### Port 8501 already in use
```bash
# Use a different port
streamlit run app.py --server.port=8502
```

### Docker build fails
```bash
# Clean up and rebuild
docker compose down
docker system prune
docker compose build --no-cache
docker compose up
```

---

## Project Structure

```
meridian-sales-intelligence/
├── app.py                  Main Streamlit application
├── setup.py               Automated setup script
├── env_loader.py          Environment variable loader
├── config.py              All configuration and constants
├── data_loader.py         CSV validation and loading
├── analytics.py           Metric computation engine
├── question_router.py     Intent classification
├── llm_layer.py           Optional Claude integration
├── observability.py       Logging and audit trail
│
├── requirements.txt        Python dependencies
├── .env.example           Environment template
├── docker-compose.yml     Docker setup
├── Dockerfile             Container definition
│
├── data/                  Data files (Q1 and Q2)
├── tests/                 37 validation tests
├── .streamlit/            Streamlit config
├── docs/                  Detailed documentation
└── logs/                  Query audit trail (created at runtime)
```

---

## Getting Help

1. **Check the in-app Methodology tab** for metric definitions
2. **Read docs/** folder for detailed architecture
3. **See README.md** for overview
4. **Run setup.py** for diagnostics
5. **Check logs/queries.jsonl** for query history

---

## Next Steps

After installation:
1. ✓ Ask a question about Q2 pipeline
2. ✓ Review the source records (the actual rows)
3. ✓ Check the trust badge and assumptions
4. ✓ Explore "Data issues" in the sidebar
5. ✓ See how narration degrades gracefully if you try to break it

Enjoy exploring your pipeline! 🚀
