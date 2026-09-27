#!/bin/bash

set -e

INTERFAZ_SALIDA="wlp3s0"
RED_VM="192.168.100.0/24"

echo "🧹 Desactivando NAT temporal para ${RED_VM} por ${INTERFAZ_SALIDA}"

if sudo iptables -t nat -C POSTROUTING -s "${RED_VM}" -o "${INTERFAZ_SALIDA}" -j MASQUERADE 2>/dev/null; then
  sudo iptables -t nat -D POSTROUTING -s "${RED_VM}" -o "${INTERFAZ_SALIDA}" -j MASQUERADE
  echo "✅ Regla NAT eliminada"
else
  echo "ℹ️ La regla NAT no existe"
fi

echo "✅ NAT temporal desactivado"
