#!/usr/bin/env bash
# macOS / Linux 入口。Windows 請用 run.bat。
exec bash "$(cd "$(dirname "$0")" && pwd)/app/launcher.sh" "$@"
