#!/usr/bin/env bash
# Uso: k6/medicion/secuencia_fallo.sh <k3s|microk8s> <tasa_media> [repeticiones=5] [rep_inicial=1]
# Corridas media con fallo controlado (retención de 120 s): preparación, inyección, restauración y espera de Ready en cada una.
# Se detiene en el primer fallo; reanudar con rep_inicial. Copia el último snapshot a data/.
set -euo pipefail

dist="${1:?uso: secuencia_fallo.sh <k3s|microk8s> <tasa_media> [repeticiones] [rep_inicial]}"
media="${2:?falta tasa_media}"; reps="${3:-5}"; desde="${4:-1}"
raiz="$(cd "$(dirname "$0")/../.." && pwd)"
log="/tmp/secuencia_fallo_${dist}.log"
sesion="$(date +%F)_${dist}_fallo"
echo "distribución=$dist media=$media repeticiones=$desde..$reps sesión=$sesion" | tee -a "$log"
for r in $(seq "$desde" "$reps"); do
  args=(--distribucion "$dist" --escenario media --repeticion "$r" --tasa "$media" --fallo --fallo-retener 120 --tipo piloto --sesion "$sesion" --estabilizacion 120)
  [ "$r" -eq "$reps" ] && args+=(--copiar-snapshot)
  echo "[$(date +%H:%M:%S)] $r/$reps media-fallo" | tee -a "$log"
  (cd "$raiz" && python3 -m k6.medicion.orquestador "${args[@]}") >>"$log" 2>&1 || { echo "FALLÓ r$r (ver $log)" | tee -a "$log"; exit 1; }
done
echo "[$(date +%H:%M:%S)] secuencia completa" | tee -a "$log"
