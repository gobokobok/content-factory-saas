#!/usr/bin/env bash
# Local environment setup for Content Factory.
# Run once after cloning: bash scripts/bootstrap.sh

set -euo pipefail

echo "→ Content Factory: local environment setup"

# Check Python version
python_version=$(python3 --version 2>&1 | awk '{print $2}')
required="3.11"
if [[ "$python_version" != 3.11* ]]; then
  echo "  WARNING: Python $python_version detected. Python 3.11 required."
fi

# Create virtualenv if not present
if [ ! -d ".venv" ]; then
  echo "→ Creating virtual environment..."
  python3 -m venv .venv
fi

# Activate and install dependencies
echo "→ Installing dependencies..."
source .venv/bin/activate
pip install --upgrade pip --quiet
pip install -r requirements.txt --quiet

# Create .env.local if not present
if [ ! -f ".env.local" ]; then
  cp .env.example .env.local
  echo "→ Created .env.local from .env.example"
  echo "  ACTION REQUIRED: fill in .env.local with your API keys and Drive folder ID"
else
  echo "→ .env.local already exists — skipping"
fi

echo ""
echo "✓ Setup complete."
echo ""
echo "Next steps:"
echo "  1. Fill in .env.local (see ENV.md for descriptions)"
echo "  2. Set up a GCP service account and add base64 JSON to GOOGLE_SERVICE_ACCOUNT_JSON"
echo "  3. Create your Google Drive root folder and add its ID to GOOGLE_DRIVE_ROOT_ID"
echo "  4. Run: source .venv/bin/activate"
echo "  5. Run: uvicorn src.main:app --reload"
echo "  6. Health check: curl http://localhost:8000/health"
