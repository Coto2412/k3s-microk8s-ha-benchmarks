#!/usr/bin/env bash
# Uso: k6/operacion/fallo-controlado.sh <k3s|microk8s> <ip-nodo> <usuario> <llave>
# SIGKILL al proceso de orquestación del nodo (protocolo de la Etapa 2, sección 4.4); no apaga la VM ni la red.
set -euo pipefail

dist="${1:?uso: fallo-controlado.sh <k3s|microk8s> <ip-nodo> <usuario> <llave>}"
ip="${2:?falta ip-nodo}"; usuario="${3:?falta usuario}"; llave="${4:?falta llave}"
case "$dist" in
  k3s) unidad=k3s ;;
  microk8s) unidad=snap.microk8s.daemon-kubelite ;;
  *) echo "distribución inválida: $dist" >&2; exit 2 ;;
esac

echo "t_antes=$(date +%s.%N)"
ssh -i "$llave" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR \
  -o ConnectTimeout=5 -o BatchMode=yes "${usuario}@${ip}" "sudo systemctl kill --kill-whom=main -s SIGKILL ${unidad}"
echo "t_despues=$(date +%s.%N)"
