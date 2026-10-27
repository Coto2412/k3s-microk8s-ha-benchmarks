#!/usr/bin/env bash
# Uso: DISTRIBUCION=k3s REPETICION=1 TASA=100 k6/correr.sh <idle|media|alta>
# Núcleos 0 y 1 = núcleo físico 0 del host (hilos SMT hermanos), reservado fuera del mapeo de las VMs.
set -euo pipefail

esc="${1:?uso: correr.sh <idle|media|alta>}"
dist="${DISTRIBUCION:?falta DISTRIBUCION (k3s|microk8s)}"
rep="${REPETICION:?falta REPETICION}"
raiz="$(cd "$(dirname "$0")/.." && pwd)"
base="${dist}_${esc}_r$(printf '%02d' "$rep")"
salida="${raiz}/data/humo"
mkdir -p "$salida"

export DISTRIBUCION="$dist" ESCENARIO="$esc" REPETICION="$rep"
echo "t_inicio=$(date +%s.%N) base=${base}"
taskset -c "${K6_CPUS:-0,1}" k6 run \
  --out "json=${salida}/${base}.json.gz" \
  --summary-export "${salida}/${base}.resumen.json" \
  "${raiz}/k6/${esc}.js"
echo "t_fin=$(date +%s.%N)"
