#!/bin/sh
# Starts the IPO Form Filler on macOS / Linux and opens it in your browser.
# Run:  ./start.sh   (or: sh start.sh)   Keep the window open; Ctrl+C stops it.
cd "$(dirname "$0")" || exit 1

if command -v python3 >/dev/null 2>&1; then
  PY=python3
elif command -v python >/dev/null 2>&1; then
  PY=python
else
  echo "Python 3 is needed to run IPO Form Filler."
  echo "Install it from https://www.python.org/downloads/ and run this again."
  exit 1
fi

exec "$PY" server.py
