#!/usr/bin/env python3
"""Setup checker for Meridian Pipeline Intelligence.

This script validates prerequisites and guides through setup.
"""
import os
import sys
import subprocess
from pathlib import Path


def check_python_version():
    """Ensure Python 3.9+"""
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 9):
        print(f"[FAIL] Python 3.9+ required (you have {version.major}.{version.minor})")
        return False
    print(f"[OK] Python {version.major}.{version.minor} detected")
    return True


def check_venv():
    """Check if virtual environment exists."""
    if Path(".venv").exists():
        print("[OK] Virtual environment exists (.venv)")
        return True
    print("[WARN] Virtual environment not found (.venv)")
    print("    Run: python -m venv .venv")
    return False


def check_imports():
    """Verify all required packages can be imported."""
    required = {
        "streamlit": "Streamlit UI",
        "pandas": "Data manipulation",
        "plotly": "Charting",
        "anthropic": "Anthropic Claude API",
        "pytest": "Testing framework",
    }

    print("\nChecking installed packages...")
    all_ok = True
    for package, description in required.items():
        try:
            __import__(package)
            print(f"  [OK] {package:20} {description}")
        except ImportError:
            print(f"  [FAIL] {package:20} {description} NOT INSTALLED")
            all_ok = False

    return all_ok


def check_data_files():
    """Verify data files exist."""
    print("\nChecking data files...")
    required = {
        "data/Q1/deals.csv": "Q1 deals",
        "data/Q1/reps.csv": "Q1 reps",
        "data/Q2/deals.csv": "Q2 deals",
        "data/Q2/reps.csv": "Q2 reps",
    }

    all_ok = True
    for file_path, desc in required.items():
        if Path(file_path).exists():
            print(f"  [OK] {file_path}")
        else:
            print(f"  [FAIL] {file_path} MISSING")
            all_ok = False

    return all_ok


def check_llm():
    """Check LLM availability."""
    print("\nChecking LLM configuration...")
    try:
        import llm_layer
        if llm_layer.is_llm_available():
            print(f"  [OK] LLM Available: {llm_layer.provider_label()}")
            return True
        else:
            print("  [WARN] LLM not available (app works without it)")
            print("         To enable: export ANTHROPIC_API_KEY=sk-ant-...")
            return False
    except Exception as e:
        print(f"  [WARN] Could not check LLM: {e}")
        return False


def run_tests():
    """Run pytest."""
    print("\nRunning tests...")
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-q"],
        capture_output=True,
        text=True
    )

    if result.returncode == 0:
        output = result.stdout.strip().split('\n')[-1]
        print(f"  [OK] {output}")
        return True
    else:
        print(f"  [FAIL] Tests failed")
        return False


def print_setup_guide():
    """Print setup instructions."""
    print("\n" + "=" * 60)
    print("SETUP INSTRUCTIONS")
    print("=" * 60)

    print("\n1. CREATE VIRTUAL ENVIRONMENT (if not done):")
    print("   python -m venv .venv")

    print("\n2. ACTIVATE VIRTUAL ENVIRONMENT:")
    if sys.platform == "win32":
        print("   .venv\\Scripts\\activate")
    else:
        print("   source .venv/bin/activate")

    print("\n3. INSTALL DEPENDENCIES:")
    print("   pip install -r requirements.txt")

    print("\n4. VERIFY INSTALLATION:")
    print("   python -m pytest tests/ -v")

    print("\n5. (OPTIONAL) ENABLE AI NARRATION:")
    print("   export ANTHROPIC_API_KEY=sk-ant-...")
    print("   (Get key at: https://console.anthropic.com/account/keys)")

    print("\n6. RUN THE APP:")
    print("   streamlit run app.py")
    print("   OR")
    print("   ./run.sh")

    print("\n7. OPEN IN BROWSER:")
    print("   http://localhost:8501")


def main():
    """Run diagnostics and print setup guide."""
    print("\n" + "=" * 60)
    print("MERIDIAN PIPELINE INTELLIGENCE - SETUP CHECKER")
    print("=" * 60 + "\n")

    # Run checks
    all_ok = True
    all_ok = check_python_version() and all_ok
    all_ok = check_venv() and all_ok
    all_ok = check_data_files() and all_ok

    # These are optional - don't fail setup if missing
    check_imports()
    check_llm()

    # Try to run tests if everything is ready
    if Path(".venv").exists() and Path("requirements.txt").exists():
        try:
            run_tests()
        except Exception:
            print("  [SKIP] Could not run tests")

    # Print guide
    print_setup_guide()

    print("\n" + "=" * 60)
    print("Questions? See:")
    print("  - README.md (architecture overview)")
    print("  - SETUP_GUIDE.md (detailed instructions)")
    print("  - IMPROVEMENTS.md (what's new)")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
