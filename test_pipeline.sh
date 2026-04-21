#!/usr/bin/env bash
# test_pipeline.sh — local testing entrypoint for PulseQuant Phase 2 validation
# Usage:
#   ./test_pipeline.sh                    # unit tests only
#   RUN_INTEGRATION=1 ./test_pipeline.sh  # unit tests + fetch + replay
#
# Requirements:
#   pip install pytest
#
# Exit codes: 0 = all passed, non-zero = failure

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${REPO_ROOT}"

# ── Resolve Python interpreter ─────────────────────────────────────────────────
# Prefer the active virtual-env's python, then python3/python on PATH.
if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
    PYTHON="${VIRTUAL_ENV}/bin/python"
elif command -v python3 &>/dev/null; then
    PYTHON="python3"
elif command -v python &>/dev/null; then
    PYTHON="python"
else
    echo "ERROR: No Python interpreter found. Activate a virtualenv or install Python 3." >&2
    exit 1
fi
echo "Using Python: ${PYTHON} ($(${PYTHON} --version 2>&1))"

echo "=== PulseQuant Phase 2 CI Pipeline ==="
echo ""

# ── 1. Unit tests ─────────────────────────────────────────────────────────────
echo "[1/3] Running Python unit tests..."
"${PYTHON}" -m pytest test/test_replay_engine.py -v --tb=short
echo "[1/3] Unit tests PASSED."
echo ""

# ── 2. Integration: fetch + replay (optional, gated by env var) ───────────────
if [[ "${RUN_INTEGRATION:-0}" == "1" ]]; then
    # 2024-03-30 is the earliest confirmed date for ORDIUSDC and SUIUSDC bookTicker
    FETCH_DATE="${INTEGRATION_DATE:-2024-03-30}"
    echo "[2/3] Fetching one-day slice from Binance Vision (${FETCH_DATE})..."
    "${PYTHON}" tools/fetch_vision_data.py \
        --symbols ORDIUSDC SUIUSDC \
        --start-date "${FETCH_DATE}" \
        --end-date "${FETCH_DATE}" \
        --cache-dir .cache/vision
    echo "[2/3] Fetch DONE."
    echo ""

    CAPTURE="test/resources/captures/ORDIUSDC_SUIUSDC_vision_${FETCH_DATE}_${FETCH_DATE}.jsonl"
    if [[ ! -f "${CAPTURE}" ]]; then
        echo "ERROR: expected capture file not found: ${CAPTURE}"
        exit 1
    fi

    # Guard: skip replay if fetch returned no events (e.g. network blocked)
    EVENT_COUNT=$(wc -l < "${CAPTURE}" | tr -d ' ')
    if [[ "${EVENT_COUNT}" -eq 0 ]]; then
        echo "WARNING: capture file is empty (Binance Vision may be unreachable). Skipping replay."
    else
        echo "[3/3] Running replay on ${EVENT_COUNT} events..."
        "${PYTHON}" tools/replay.py \
            --input "${CAPTURE}" \
            --target ORDIUSDC \
            --feature SUIUSDC \
            --slippage-bps 10
        echo "[3/3] Replay DONE."
    fi
else
    echo "[2/3] Skipping integration fetch+replay (set RUN_INTEGRATION=1 to enable)."
    echo "[3/3] Skipped."
fi

echo ""
echo "[4/4] Running Playwright E2E tests..."
npm run test:e2e
echo "[4/4] E2E tests PASSED."

echo ""
echo "=== Pipeline PASSED ==="
