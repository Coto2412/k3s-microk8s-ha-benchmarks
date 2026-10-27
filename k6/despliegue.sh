#!/usr/bin/env bash
# Uso: k6/despliegue.sh <k3s|microk8s> <construir|destruir> <ciclo>
# Cronometra por fases (sin carga de k6) y agrega una línea a data/despliegue/despliegue_<distribución>.jsonl (T-20.6).
set -euo pipefail

dist="${1:?uso: despliegue.sh <k3s|microk8s> <construir|destruir> <ciclo>}"
accion="${2:?falta acción}"; ciclo="${3:?falta ciclo}"
raiz="$(cd "$(dirname "$0")/.." && pwd)"
base="${raiz}/${dist}HA"
[ -d "$base" ] || { echo "distribución inválida: $dist" >&2; exit 2; }
registro="${raiz}/data/despliegue/despliegue_${dist}.jsonl"
modo=false; [ -e /run/tesis-medicion.estado ] && modo=true
fases=""
fase() {
  local t0 t1 r=0; t0=$(date +%s.%N); "$@" || r=$?; t1=$(date +%s.%N)
  fases="${fases}\"$1\":{\"inicio\":${t0},\"fin\":${t1},\"duracion_s\":$(echo "$t1 - $t0" | bc)},"
  return $r
}
log="${DESPLIEGUE_LOG:-/tmp}/despliegue_${dist}_${accion}_c${ciclo}.log"
tf_construir() { (cd "$base/terraform" && terraform init -input=false && terraform apply -auto-approve) >>"$log" 2>&1; }
tf_destruir() { (cd "$base/terraform" && ./limpia.sh) >>"$log" 2>&1; }
huellas() { (cd "$base" && ./limpia_fingerprint.sh) >>"$log" 2>&1; }
ansible() { (cd "$base/ansible" && ansible-playbook playbook.yml) >>"$log" 2>&1; }

t_ini=$(date +%s.%N); rc=0
case "$accion" in
  construir) fase tf_construir && fase huellas && fase ansible || rc=$? ;;
  destruir) fase tf_destruir || rc=$? ;;
  *) echo "acción inválida: $accion" >&2; exit 2 ;;
esac
t_fin=$(date +%s.%N)
mkdir -p "$(dirname "$registro")"
printf '{"distribucion":"%s","accion":"%s","ciclo":%s,"rc":%s,"modo_medicion":%s,"sin_carga":true,"inicio":%s,"fin":%s,"duracion_total_s":%s,"fases":{%s}}\n' \
  "$dist" "$accion" "$ciclo" "$rc" "$modo" "$t_ini" "$t_fin" "$(echo "$t_fin - $t_ini" | bc)" "${fases%,}" >> "$registro"
tail -1 "$registro"
exit "$rc"
