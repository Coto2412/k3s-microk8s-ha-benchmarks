#!/usr/bin/env bash
# Uso: k6/medicion/secuencia_control.sh <k3s|microk8s> <tasa_media> [repeticiones=3]
# Corrida de control de --rtt y --cgroup-cp: escenario media en tres condiciones (base, rtt, cgroup) con orden rotado por repetición,
# todas en el mismo clúster y sesión. La repetición es el orden de ejecución; la condición queda en los metadatos (rtt, cgroup_cp).
set -euo pipefail

dist="${1:?uso: secuencia_control.sh <k3s|microk8s> <tasa_media> [repeticiones]}"
media="${2:?falta tasa_media}"; reps="${3:-3}"
raiz="$(cd "$(dirname "$0")/../.." && pwd)"
log="/tmp/secuencia_control_${dist}.log"
sesion="$(date +%F)_${dist}_control"
conds=(base rtt cgroup); n=0; total=$((reps * 3))
echo "distribución=$dist media=$media repeticiones=$reps sesión=$sesion" | tee -a "$log"
for r in $(seq 1 "$reps"); do
  for i in 0 1 2; do
    c="${conds[$(((i + r - 1) % 3))]}"; n=$((n + 1))
    args=(--distribucion "$dist" --escenario media --repeticion "$n" --tasa "$media" --tipo piloto --sesion "$sesion" --estabilizacion 120)
    [ "$c" = rtt ] && args+=(--rtt)
    [ "$c" = cgroup ] && args+=(--cgroup-cp)
    [ "$n" -eq "$total" ] && args+=(--copiar-snapshot)
    echo "[$(date +%H:%M:%S)] $n/$total media $c" | tee -a "$log"
    (cd "$raiz" && python3 -m k6.medicion.orquestador "${args[@]}") >>"$log" 2>&1 || { echo "FALLÓ $c n=$n (ver $log)" | tee -a "$log"; exit 1; }
  done
done
echo "[$(date +%H:%M:%S)] secuencia completa" | tee -a "$log"
