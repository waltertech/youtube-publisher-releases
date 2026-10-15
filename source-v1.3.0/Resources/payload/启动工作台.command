#!/bin/zsh
cd -- "${0:A:h}" || exit 1
if [[ ! -x .venv/bin/python ]]; then
 python3 -m venv .venv || exit 1
 .venv/bin/python -m pip install -r requirements.txt || exit 1
fi
if [[ ! -f 本机配置.json ]]; then
 .venv/bin/python setup_local.py || exit 1
fi
.venv/bin/python dashboard.py
