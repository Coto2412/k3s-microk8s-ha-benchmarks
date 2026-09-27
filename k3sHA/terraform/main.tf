# Configuración de keepalived por nodo
# Configuración de la llave pública SSH
locals {
  keepalived_states     = ["MASTER", "BACKUP", "BACKUP"]
  keepalived_priorities = [100, 90, 80]
  ssh_public_key        = var.ssh_public_key != "" ? var.ssh_public_key : file("${path.module}/../keys/key.pub")
  vm_macs               = ["52:54:00:10:00:01", "52:54:00:10:00:02", "52:54:00:10:00:03"]
}

# Generación del inventario de Ansible directamente desde Terraform
resource "local_file" "ansible_inventory" {
  content = join("\n", [
    "# Grupo de servidores k3s con configuración de keepalived",
    "[k3s_servers]",
    join("\n", [
      for i in range(var.vm_count) :
      "# Nodo ${i + 1} - ${local.keepalived_states[i]} de keepalived con prioridad ${local.keepalived_priorities[i]}\n${var.vm_names[i]} ansible_host=${var.vm_ips[i]} keepalived_state=${local.keepalived_states[i]} keepalived_priority=${local.keepalived_priorities[i]} haproxy_bind_ip=0.0.0.0"
    ]),
    "",
    "# Grupo principal que incluye todos los servidores k3s",
    "[k3s_cluster:children]",
    "k3s_servers",
    "",
    "# Variables compartidas para el grupo k3s_cluster",
    "[k3s_cluster:vars]",
    "ansible_user=${var.cluster_user}",
    "cluster_user=${var.cluster_user}",
    "vip_address=${var.vip_address}",
    "ansible_ssh_private_key_file=../keys/key",
  ])
  filename = "${path.module}/../ansible/inventory.ini"
}

# Creación de la red virtual k3s-tesis en modo nat
resource "libvirt_network" "k3s_network" {
  name      = var.network_name
  mode      = "nat"
  domain    = "k3s-tesis.local"
  addresses = [var.network_cidr]

  # DHCP habilitado: IP estática por reserva de host (MAC->IP) vía
  # el atributo `addresses` de cada network_interface más abajo.
  dhcp {
    enabled = true
  }

  # Iniciar la red automáticamente al arrancar libvirt
  autostart = true
}

# Volumen base de la imagen Ubuntu 22.04
resource "libvirt_volume" "base_image" {
  name   = "ubuntu-2204-base.qcow2"
  source = var.base_image
  pool   = "default"
  format = "qcow2"
}

# Disco raíz para cada máquina virtual, clonado desde la imagen base
resource "libvirt_volume" "vm_disk" {
  count          = var.vm_count
  name           = "${var.vm_names[count.index]}-disk.qcow2"
  base_volume_id = libvirt_volume.base_image.id
  pool           = "default"
  format         = "qcow2"
  size           = var.vm_disk_size * 1073741824
}

# Disco cloud-init con configuración de usuario y red para cada VM
resource "libvirt_cloudinit_disk" "cloudinit" {
  count      = var.vm_count
  name       = "${var.vm_names[count.index]}-cloudinit.iso"
  pool       = "default"
    user_data  = templatefile("${path.module}/config/cloud-init.cfg", {
    hostname       = var.vm_names[count.index]
    cluster_user   = var.cluster_user
    ssh_public_key = local.ssh_public_key
  })
  network_config = templatefile("${path.module}/config/network-config.cfg", {
    ip_address  = var.vm_ips[count.index]
    mac_address = local.vm_macs[count.index]
  })
}

# Definición de cada máquina virtual k3s
resource "libvirt_domain" "k3s_node" {
  count   = var.vm_count
  name    = var.vm_names[count.index]
  memory  = var.vm_memory
  vcpu    = var.vm_cpu
  running = true

  # Disco raíz del sistema operativo
  disk {
    volume_id = libvirt_volume.vm_disk[count.index].id
  }

  # Disco cloud-init para configuración inicial
  cloudinit = libvirt_cloudinit_disk.cloudinit[count.index].id

  # Interfaz de red conectada a la red k3s-tesis.
  # `addresses` fija la reserva DHCP por MAC (IP estática determinística).
  network_interface {
    network_id     = libvirt_network.k3s_network.id
    hostname       = var.vm_names[count.index]
    addresses      = [var.vm_ips[count.index]]
    wait_for_lease = true
    mac            = local.vm_macs[count.index]
  }

  # Consola serial para acceso a la VM
  console {
    type        = "pty"
    target_port = "0"
    target_type = "serial"
  }

  # Configuración gráfica con SPICE
  graphics {
    type        = "spice"
    listen_type = "address"
    autoport    = true
  }

  # Uso del modelo de CPU del host para mejor rendimiento
  cpu {
    mode = "host-model"
  }
}

# Salida con las direcciones IP de cada nodo k3s
output "vm_ips" {
  value = {
    for i in range(var.vm_count) : var.vm_names[i] => var.vm_ips[i]
  }
  description = "Direcciones IP de los nodos k3s"
}

# Salida con la dirección IP virtual de keepalived
output "vip_address" {
  value       = var.vip_address
  description = "Dirección IP virtual para keepalived"
}
