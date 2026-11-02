#!/usr/bin/env bash
# Uso: k6/medicion/estado_inicial.sh <carpeta-de-sesión>   (ej. data/pilotos/2026-11-03_k3s)
# Registra el estado del host antes de una secuencia, tras liberar el swap (mismo contenido que estado_inicial.txt de las pasadas del 28-oct).
set -euo pipefail
dest="${1:?uso: estado_inicial.sh <carpeta-de-sesión>}"
mkdir -p "$dest"
f="$dest/estado_inicial.txt"
[ ! -e "$f" ] || { echo "Ya existe $f; no se sobrescribe" >&2; exit 1; }
modo=inactivo; [ -e /run/tesis-medicion.estado ] && modo=activo
{
  echo "# Estado inicial tomado tras swapoff -a && swapon -a (modo medición: $modo; display-manager: $(systemctl is-active display-manager || true))"
  echo "## date"; date
  echo "## chronyc tracking"; chronyc tracking
  echo "## powerprofilesctl get"; powerprofilesctl get
  echo "## boost"; cat /sys/devices/system/cpu/cpufreq/boost
  echo "## free -m"; free -m
  echo "## df -h"; df -h / /run
  echo "## swapon --show"; swapon --show
  echo "## AC online"; cat /sys/class/power_supply/AC*/online
  echo "## red activa"; nmcli -t -f NAME,TYPE connection show --active
  echo "## /proc/vmstat pswpin pswpout (acumulados desde el arranque)"; grep -E '^pswp(in|out) ' /proc/vmstat
  echo "## procesos qemu (VmRSS en kB)"
  for p in $(pgrep -x qemu-system-x86); do
    echo "$(tr '\0' ' ' </proc/$p/cmdline | grep -o 'guest=[^,]*') $(grep VmRSS /proc/$p/status)"
  done
} >"$f"
echo "escrito $f"
