#!/usr/bin/env bash
set -u

external_root=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --external-root)
      external_root="${2:-}"
      shift 2
      ;;
    -h|--help)
      echo "usage: $0 [--external-root PATH]"
      exit 0
      ;;
    *)
      echo "unknown argument: $1" >&2
      exit 2
      ;;
  esac
done

section() {
  printf '\n## %s\n\n' "$1"
}

run() {
  local label="$1"
  shift
  printf '### %s\n\n```text\n' "$label"
  "$@" 2>&1 || true
  printf '```\n\n'
}

status() {
  local command_name="$1"
  if command -v "$command_name" >/dev/null 2>&1; then
    printf -- '- [x] `%s`: `%s`\n' "$command_name" "$(command -v "$command_name")"
  else
    printf -- '- [ ] `%s`: missing\n' "$command_name"
  fi
}

echo "# GB10 Doctor"
echo
echo "Generated UTC: $(date -u '+%Y-%m-%dT%H:%M:%SZ')"

section "Host"
run "Kernel and architecture" uname -a
if [[ -r /etc/os-release ]]; then
  run "Operating system" cat /etc/os-release
fi
run "Memory" sh -c 'command -v free >/dev/null && free -h || vm_stat'
run "Root storage" df -h /

section "GPU and CUDA"
if command -v nvidia-smi >/dev/null 2>&1; then
  run "GPU identity" nvidia-smi --query-gpu=name,compute_cap,driver_version --format=csv,noheader
  run "GPU summary" nvidia-smi
else
  printf '%s\n' '- [ ] `nvidia-smi`: missing'
fi
if command -v nvcc >/dev/null 2>&1; then
  run "CUDA compiler" nvcc --version
else
  printf '%s\n' '- [ ] `nvcc`: missing'
fi

section "Required commands"
for command_name in git curl jq python3 docker node npm nemoclaw openclaw openshell; do
  status "$command_name"
done

section "Runtime versions"
command -v python3 >/dev/null 2>&1 && run "Python" python3 --version
command -v docker >/dev/null 2>&1 && run "Docker" docker version
command -v nemoclaw >/dev/null 2>&1 && run "NemoClaw" nemoclaw --version
command -v openclaw >/dev/null 2>&1 && run "OpenClaw" openclaw --version
command -v openshell >/dev/null 2>&1 && run "OpenShell" openshell --version

section "Local inference endpoint"
if command -v curl >/dev/null 2>&1; then
  run "GET http://127.0.0.1:8000/v1/models" \
    curl --max-time 5 --fail --silent --show-error http://127.0.0.1:8000/v1/models
fi

section "External storage"
if [[ -n "$external_root" ]]; then
  if [[ -d "$external_root" ]]; then
    run "Storage for $external_root" df -h "$external_root"
    if [[ -w "$external_root" ]]; then
      echo "- [x] External root is writable: \`$external_root\`"
    else
      echo "- [ ] External root is not writable: \`$external_root\`"
    fi
  else
    echo "- [ ] External root does not exist: \`$external_root\`"
  fi
else
  echo "No external root supplied. Re-run with \`--external-root PATH\`."
fi

section "Interpretation"
cat <<'EOF'
- Attach this complete report to GitHub issue #3.
- A missing command is a setup result, not a reason to edit the report.
- Do not include environment variables, tokens, or container secrets.
EOF
