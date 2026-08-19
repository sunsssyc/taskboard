#!/bin/zsh
set -euo pipefail

script_dir="${0:A:h}"
repo_root="${script_dir:h:h}"
output_dir="${OUTPUT_DIR:-${repo_root}/dist}"
app_dir="${output_dir}/Taskboard.app"
board_executable="${TASKBOARD_BOARD_EXECUTABLE:-}"

if [[ -z "${board_executable}" ]]; then
  board_executable="$(command -v board || true)"
fi
if [[ -z "${board_executable}" || ! -x "${board_executable}" ]]; then
  print -u2 "找不到可执行的 board 命令；可设置 TASKBOARD_BOARD_EXECUTABLE=/absolute/path/to/board"
  exit 1
fi

swift build --package-path "${script_dir}" -c release
binary_dir="$(swift build --package-path "${script_dir}" -c release --show-bin-path)"
icon_path="$("${script_dir}/Scripts/make_icns.sh")"

rm -rf "${app_dir}"
mkdir -p "${app_dir}/Contents/MacOS"
mkdir -p "${app_dir}/Contents/Resources"
install -m 755 "${binary_dir}/TaskboardMenuBar" "${app_dir}/Contents/MacOS/TaskboardMenuBar"
install -m 644 "${script_dir}/Resources/Info.plist" "${app_dir}/Contents/Info.plist"
install -m 644 "${icon_path}" "${app_dir}/Contents/Resources/AppIcon.icns"
plutil -replace TaskboardBoardExecutable -string "${board_executable}" \
  "${app_dir}/Contents/Info.plist"
codesign --force --deep --sign - "${app_dir}"

print "${app_dir}"
