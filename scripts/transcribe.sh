#!/usr/bin/env bash
# Phase 3 — Transcribe both Zoom H1n WAV files with whisper and merge into edit/transcript.json (master time).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${REPO_ROOT}/.cache/whisper"
MODEL="${WHISPER_MODEL:-base.en}"

mkdir -p "${OUT_DIR}"

for WAV in "${REPO_ROOT}/edit/assets/audio/ZOOM0030.WAV" "${REPO_ROOT}/edit/assets/audio/ZOOM0031.WAV"; do
  BASE="$(basename "${WAV}" .WAV)"
  JSON_OUT="${OUT_DIR}/${BASE}.json"
  if [[ -f "${JSON_OUT}" ]]; then
    echo "Skipping ${BASE} (cached at ${JSON_OUT})"
    continue
  fi
  echo "=== Transcribing ${BASE} with whisper (model=${MODEL}) ==="
  whisper "${WAV}" \
    --model "${MODEL}" \
    --language en \
    --word_timestamps True \
    --output_format json \
    --output_dir "${OUT_DIR}" \
    --verbose False
done

uv run "${REPO_ROOT}/scripts/merge_transcript.py"
