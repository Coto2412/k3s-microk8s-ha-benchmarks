#!/bin/bash

set -e 

echo "🧹 Limpiando known_hosts para las IPs del clúster..."
# Extraemos las IPs dinámicamente del inventory generado por Terraform
# Usamos mapfile para guardar cada línea como un elemento del array
mapfile -t IPS < <(awk -F'=' '/ansible_host=/ {print $2}' ansible/inventory.ini | awk '{print $1}' | sort -u)

for ip in "${IPS[@]}"; do
  ssh-keygen -f "/home/coto/.ssh/known_hosts" -R "$ip" > /dev/null 2>&1
done

echo "🔑 Iniciando ssh-agent..."
eval "$(ssh-agent -s)"

echo "🔐 Cargando clave SSH..."
ssh-add keys/key

echo "🌐 Probando conectividad..."

# La variable IPS ya fue definida arriba, solo iteramos
for ip in "${IPS[@]}"; do
  echo "➡ Probando $ip ..."
  ping -c 2 $ip > /dev/null || { echo "❌ No hay conectividad con $ip"; exit 1; }

  echo "➡ Probando SSH en $ip ..."
  ssh -o StrictHostKeyChecking=no -o ConnectTimeout=5 -i keys/key jdelpino@$ip "echo OK" || {
    echo "❌ SSH falló en $ip"
    exit 1
  }
done

echo "✅ Conectividad OK"

echo "📡 Probando Ansible..."
ansible -i ansible/inventory.ini all -m ping
