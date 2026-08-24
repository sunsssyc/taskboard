#!/bin/zsh
set -euo pipefail

script_dir="${0:A:h}"
package_dir="${script_dir:h}"
source_png="${1:-${package_dir}/Resources/AppIcon.png}"
output_icns="${2:-${package_dir}/.build/AppIcon.icns}"
iconset_dir="${output_icns:r}.iconset"

rm -rf "${iconset_dir}"
mkdir -p "${iconset_dir}" "${output_icns:h}"

sips -z 16 16 "${source_png}" --out "${iconset_dir}/icon_16x16.png" >/dev/null
sips -z 32 32 "${source_png}" --out "${iconset_dir}/icon_16x16@2x.png" >/dev/null
sips -z 32 32 "${source_png}" --out "${iconset_dir}/icon_32x32.png" >/dev/null
sips -z 64 64 "${source_png}" --out "${iconset_dir}/icon_32x32@2x.png" >/dev/null
sips -z 128 128 "${source_png}" --out "${iconset_dir}/icon_128x128.png" >/dev/null
sips -z 256 256 "${source_png}" --out "${iconset_dir}/icon_128x128@2x.png" >/dev/null
sips -z 256 256 "${source_png}" --out "${iconset_dir}/icon_256x256.png" >/dev/null
sips -z 512 512 "${source_png}" --out "${iconset_dir}/icon_256x256@2x.png" >/dev/null
sips -z 512 512 "${source_png}" --out "${iconset_dir}/icon_512x512.png" >/dev/null
cp "${source_png}" "${iconset_dir}/icon_512x512@2x.png"

iconutil -c icns "${iconset_dir}" -o "${output_icns}"
rm -rf "${iconset_dir}"
print "${output_icns}"
