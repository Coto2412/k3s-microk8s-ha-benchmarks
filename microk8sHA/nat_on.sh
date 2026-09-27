#!/bin/bash

set -e

INTERFAZ_SALIDA="wlp3s0"
RED_VM="192.168.100.0/24"

echo "✅ Activando NAT temporal para ${RED_VM} por ${INTERFAZ_SALIDA}"

sudo sysctl -w net.ipv4.ip_forward=1

if ! sudo iptables -t nat -C POSTROUTING -s "${RED_VM}" -o "${INTERFAZ_SALIDA}" -j MASQUERADE 2>/dev/null; then
  sudo iptables -t nat -A POSTROUTING -s "${RED_VM}" -o "${INTERFAZ_SALIDA}" -j MASQUERADE
  echo "✅ Regla NAT agregada"
else
  echo "ℹ️ La regla NAT ya existe"
fi

echo "✅ NAT temporal activado"
