#!/usr/bin/env bash
# check-env.sh — can this machine actually run devops-copilot?
#
# Checks are tiered to match the repo:
#   CORE      day 1-2 CLI (copilot-ingest / copilot-triage): python, uv,
#             Ollama + both models, RAM, disk.
#   DAY 3     docker + compose (containerized service + Jaeger)
#   DAY 3/5   kind + kubectl (cluster deploy, incident demos)
#   DAY 4     helm (monitoring), terraform + az (IaC validation), pwsh (scorecard)
#
# Exit codes: 0 = core ready, 1 = core requirement missing.
# Optional gaps only WARN — you can do days 1-2 on a laptop with nothing
# but python, uv and ollama.
#
# Usage: bash scripts/check-env.sh

set -u

PASS=0; WARN=0; FAIL=0

green() { printf '\033[32m%s\033[0m' "$1"; }
yellow(){ printf '\033[33m%s\033[0m' "$1"; }
red()   { printf '\033[31m%s\033[0m' "$1"; }

ok()   { PASS=$((PASS+1)); printf '  [%s] %s\n'  "$(green PASS)" "$1"; }
warn() { WARN=$((WARN+1)); printf '  [%s] %s\n'  "$(yellow WARN)" "$1"; }
fail() { FAIL=$((FAIL+1)); printf '  [%s] %s\n'  "$(red FAIL)" "$1"; }

have() { command -v "$1" >/dev/null 2>&1; }

section() { printf '\n== %s ==\n' "$1"; }

# --------------------------------------------------------------- system ----
section "System resources"

OS="$(uname -s)"
ARCH="$(uname -m)"
printf '  os=%s arch=%s\n' "$OS" "$ARCH"

# RAM: qwen2.5:7b (Q4) wants ~5-6 GB resident; embed model ~0.5 GB; plus the
# OS, Docker and kind. 8 GB is the floor, 16 GB is comfortable.
ram_gb=0
if [ "$OS" = "Darwin" ]; then
  ram_gb=$(( $(sysctl -n hw.memsize) / 1024 / 1024 / 1024 ))
elif [ -r /proc/meminfo ]; then
  ram_gb=$(( $(awk '/MemTotal/{print $2}' /proc/meminfo) / 1024 / 1024 ))
fi
if   [ "$ram_gb" -ge 16 ]; then ok  "RAM: ${ram_gb} GB (comfortable for 7B model + kind + docker)"
elif [ "$ram_gb" -ge 8  ]; then warn "RAM: ${ram_gb} GB — enough for the 7B model, but close Docker/kind while triaging, or use a smaller CHAT_MODEL (e.g. qwen2.5:3b)"
else fail "RAM: ${ram_gb} GB — below the ~8 GB floor for qwen2.5:7b; use qwen2.5:3b or llama3.2:3b (export CHAT_MODEL=...)"
fi

# Disk: ~5 GB models + ~1 GB docker images + kind node image ~1 GB.
disk_gb=$(df -Pk "$HOME" 2>/dev/null | awk 'NR==2{print int($4/1024/1024)}')
disk_gb=${disk_gb:-0}
if   [ "$disk_gb" -ge 15 ]; then ok  "Free disk in \$HOME: ${disk_gb} GB"
elif [ "$disk_gb" -ge 8  ]; then warn "Free disk in \$HOME: ${disk_gb} GB — models (~5 GB) + images will fit, but tightly"
else fail "Free disk in \$HOME: ${disk_gb} GB — need ~8 GB minimum for models + images"
fi

cores=$( (nproc 2>/dev/null || sysctl -n hw.ncpu 2>/dev/null) | head -1 )
if [ "${cores:-0}" -ge 4 ]; then ok "CPU cores: $cores"
else warn "CPU cores: ${cores:-?} — CPU-only inference on a 7B model will be slow (expect 30-90 s per triage)"
fi

if [ "$OS" = "Darwin" ] && [ "$ARCH" = "arm64" ]; then
  ok "Apple Silicon: Ollama uses Metal — inference will be fast"
elif have nvidia-smi && nvidia-smi >/dev/null 2>&1; then
  vram=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1)
  ok "NVIDIA GPU detected (${vram:-?} MiB VRAM) — Ollama will offload to it"
else
  warn "No GPU detected — everything still works on CPU, just slower per agent step"
fi

# ------------------------------------------------------ core: days 1-2 ----
section "Core toolchain (days 1-2: ingest + triage CLI)"

if have python3; then
  pyver=$(python3 -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')
  if python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)'; then
    ok "python3 $pyver (>= 3.11 required by pyproject)"
  else
    fail "python3 $pyver — pyproject requires >= 3.11 (uv can install one: uv python install 3.12)"
  fi
else
  fail "python3 not found"
fi

if have uv; then ok "uv $(uv --version 2>/dev/null | awk '{print $2}')"
else fail "uv not found — install: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

if have git; then ok "git $(git --version | awk '{print $3}')"
else fail "git not found"
fi

# ------------------------------------------------------------- ollama ----
section "Ollama (the model backend everything depends on)"

OLLAMA_URL="${OLLAMA_BASE_URL:-http://localhost:11434}"
if ! have ollama; then
  fail "ollama binary not found — install from https://ollama.com"
elif ! curl -fsS --max-time 3 "$OLLAMA_URL/api/tags" >/dev/null 2>&1; then
  fail "ollama installed but server not reachable at $OLLAMA_URL — start it: ollama serve"
else
  ok "ollama server reachable at $OLLAMA_URL"
  tags=$(curl -fsS --max-time 5 "$OLLAMA_URL/api/tags" 2>/dev/null)
  chat_model="${CHAT_MODEL:-qwen2.5:7b}"
  embed_model="${EMBED_MODEL:-nomic-embed-text}"
  if printf '%s' "$tags" | grep -q "\"${chat_model%%:*}"; then
    ok "chat model present: $chat_model"
  else
    fail "chat model '$chat_model' not pulled — run: ollama pull $chat_model"
  fi
  if printf '%s' "$tags" | grep -q "\"${embed_model%%:*}"; then
    ok "embed model present: $embed_model"
  else
    fail "embed model '$embed_model' not pulled — run: ollama pull $embed_model"
  fi
fi

# ------------------------------------------------- day 3: containers ----
section "Day 3 (optional): Docker service + Jaeger"

if have docker; then
  if docker info >/dev/null 2>&1; then
    ok "docker daemon running ($(docker --version | sed 's/Docker version //;s/,.*//'))"
    if docker compose version >/dev/null 2>&1; then ok "docker compose plugin present"
    else warn "docker compose plugin missing — compose.yaml needs it (or use docker-compose v1)"
    fi
  else
    warn "docker installed but daemon not running/accessible — start Docker (or add your user to the docker group)"
  fi
else
  warn "docker not found — skip compose/kind demos; the service still runs bare: uv run uvicorn day3_service.app.main:app"
fi

# --------------------------------------------- day 3/5: kubernetes ----
section "Days 3+5 (optional): kind cluster + kubectl"

if have kind; then ok "kind $(kind version 2>/dev/null | awk '{print $2}')"
else warn "kind not found — needed for the K8s deploy + incident demos (https://kind.sigs.k8s.io)"
fi
if have kubectl; then
  ok "kubectl $(kubectl version --client -o json 2>/dev/null | grep -o '"gitVersion": *"[^"]*"' | head -1 | cut -d'"' -f4)"
  if kubectl cluster-info >/dev/null 2>&1; then ok "a cluster is reachable with the current kubeconfig"
  else warn "kubectl present but no cluster reachable — create one: kind create cluster --config day4_devops/scripts/kind-config.yaml"
  fi
else
  warn "kubectl not found — needed for days 3/5"
fi

# --------------------------------------------------- day 4: devops ----
section "Day 4 (optional): pipeline + IaC + monitoring tooling"

if have helm;      then ok  "helm $(helm version --short 2>/dev/null)"
else warn "helm not found — needed only for kube-prometheus-stack"; fi
if have terraform; then ok  "terraform $(terraform version 2>/dev/null | head -1 | awk '{print $2}')"
else warn "terraform not found — needed only to validate day4_devops/infra/terraform"; fi
if have az;        then ok  "azure cli present (az bicep build for the Bicep mirror)"
else warn "az cli not found — needed only for 'az bicep build' and the pipeline's Azure side"; fi
if have pwsh;      then ok  "pwsh present (Publish-Scorecard.ps1 runs locally too)"
else warn "pwsh not found — the PowerShell scorecard step only matters on the pipeline agent"; fi

# -------------------------------------------------------- verdict ----
section "Verdict"
printf '  %s passed, %s warnings, %s failures\n' "$PASS" "$WARN" "$FAIL"
if [ "$FAIL" -gt 0 ]; then
  printf '  %s core requirements missing — fix the FAIL lines above first.\n' "$(red "$FAIL")"
  exit 1
fi
if [ "$WARN" -gt 0 ]; then
  printf '  Core is %s. Warnings only limit the optional day-3/4/5 demos.\n' "$(green READY)"
else
  printf '  Everything is %s — full pipeline, cluster and monitoring demos included.\n' "$(green READY)"
fi
exit 0
