#!/usr/bin/env bash
# Phase 3 — Transcribe both Zoom H1n tracks (normalized -16 LUFS if available) with whisper -> edit/transcript.json.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT_DIR="${REPO_ROOT}/.cache/whisper"
MODEL="${WHISPER_MODEL:-base.en}"

mkdir -p "${OUT_DIR}"

for BASE in ZOOM0030 ZOOM0031; do
  JSON_OUT="${OUT_DIR}/${BASE}.json"
  if [[ -f "${JSON_OUT}" ]]; then
    echo "Skipping ${BASE} (cached at ${JSON_OUT})"
    continue
  fi
  SRC="${REPO_ROOT}/edit/assets/audio_norm/${BASE}.m4a"
  if [[ ! -f "${SRC}" ]]; then
    SRC="${REPO_ROOT}/edit/assets/audio/${BASE}.WAV"
  fi
  echo "=== Transcribing ${BASE} from $(basename "${SRC}") with whisper (model=${MODEL}) ==="
  whisper "${SRC}" \
    --model "${MODEL}" \
    --language en \
    --condition_on_previous_text False \
    --word_timestamps True \
    --output_format json \
    --output_dir "${OUT_DIR}" \
    --verbose False
done

uv run "${REPO_ROOT}/scripts/merge_transcript.py"
