#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 2 ]]; then
  echo "usage: $0 KIT_ROOT OUTPUT_DIR" >&2
  exit 2
fi

kit_root="$(cd "$1" && pwd)"
output_dir="$2"

if [[ "$output_dir" != /* ]]; then
  output_dir="$(pwd)/$output_dir"
fi

mkdir -p "$output_dir"
manifest="$output_dir/manifest.tsv"
checksums="$output_dir/SHA256SUMS"
summary="$output_dir/storage.txt"

if command -v sha256sum >/dev/null 2>&1; then
  hash_command=(sha256sum)
elif command -v shasum >/dev/null 2>&1; then
  hash_command=(shasum -a 256)
else
  echo "sha256sum or shasum is required" >&2
  exit 1
fi

printf 'relative_path\tsize_bytes\tsha256\n' > "$manifest"
: > "$checksums"
unsorted_manifest="$(mktemp)"
trap 'rm -f "$unsorted_manifest"' EXIT

while IFS= read -r -d '' file; do
  relative_path="${file#"$kit_root"/}"
  if [[ "$file" == "$output_dir"/* ]]; then
    continue
  fi

  if stat --version >/dev/null 2>&1; then
    size_bytes="$(stat -c '%s' "$file")"
  else
    size_bytes="$(stat -f '%z' "$file")"
  fi

  hash_output="$("${hash_command[@]}" "$file")"
  sha256="${hash_output%% *}"
  printf '%s\t%s\t%s\n' "$relative_path" "$size_bytes" "$sha256" >> "$unsorted_manifest"
  printf '%s  %s\n' "$sha256" "$relative_path" >> "$checksums"
done < <(find "$kit_root" -path '*/.git' -prune -o -type f -print0)

LC_ALL=C sort "$unsorted_manifest" >> "$manifest"
LC_ALL=C sort -o "$checksums" "$checksums"

{
  echo "kit_root=$kit_root"
  echo "generated_utc=$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  echo "file_count=$(($(wc -l < "$manifest") - 1))"
  echo
  df -h "$kit_root"
  echo
  du -sh "$kit_root"
} > "$summary"

echo "wrote $manifest"
echo "wrote $checksums"
echo "wrote $summary"
