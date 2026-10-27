#!/usr/bin/env bash
# Uso: k6/medicion/secuencia_piloto.sh <k3s|microk8s> <tasa_media> <tasa_alta> [repeticiones=3] ["idle media alta"] [rep_inicial=1]
# Corre los escenarios por repetición, sin supervisión; se detiene en el primer fallo. Con los tres escenarios, copia el último snapshot a data/.
set -euo pipefail

dist="${1:?uso: secuencia_piloto.sh <k3s|microk8s> <tasa_media> <tasa_alta> [repeticiones]}"
media="${2:?falta tasa_media}"; alta="${3:?falta tasa_alta}"; reps="${4:-3}"; escenarios="${5:-idle media alta}"; desde="${6:-1}"
raiz="$(cd "$(dirname "$0")/../.." && pwd)"
log="/tmp/secuencia_piloto_${dist}.log"
sesion="$(date +%F)_${dist}"
read -ra lista <<<"$escenarios"; total=$(((reps - desde + 1) * ${#lista[@]})); n=0
echo "distribución=$dist media=$media alta=$alta repeticiones=$desde..$reps escenarios=$escenarios" | tee -a "$log"
for r in $(seq "$desde" "$reps"); do
  for esc in "${lista[@]}"; do
    n=$((n + 1))
    args=(--distribucion "$dist" --escenario "$esc" --repeticion "$r" --tipo piloto --sesion "$sesion" --estabilizacion 120)
    [ "$esc" = media ] && args+=(--tasa "$media")
    [ "$esc" = alta ] && args+=(--tasa "$alta")
    [ "$n" -eq "$total" ] && [ "$escenarios" = "idle media alta" ] && args+=(--copiar-snapshot)
    echo "[$(date +%H:%M:%S)] $n/$total $esc r$r" | tee -a "$log"
    (cd "$raiz" && python3 -m k6.medicion.orquestador "${args[@]}") >>"$log" 2>&1 || { echo "FALLÓ $esc r$r (ver $log)" | tee -a "$log"; exit 1; }
  done
done
echo "[$(date +%H:%M:%S)] secuencia completa" | tee -a "$log"
