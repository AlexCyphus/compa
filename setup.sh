#!/bin/bash
# One-time setup: Python venv, dependencies, the Silero VAD model, and the `compa` command on your PATH.
set -euo pipefail
cd "$(dirname "$0")"
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
mkdir -p models
[ -f models/silero_vad.onnx ] || curl -sL -o models/silero_vad.onnx \
  https://github.com/snakers4/silero-vad/raw/066409f3d9db45a30d21dfcbf9147826ffdd7052/src/silero_vad/data/silero_vad.onnx
mkdir -p ~/.local/bin && ln -sf "$PWD/bin/compa" ~/.local/bin/compa
echo "Done. Run: compa spanish"
