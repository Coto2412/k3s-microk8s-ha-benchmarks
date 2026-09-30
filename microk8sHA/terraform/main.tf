# Configuración de la llave pública SSH
locals {
  ssh_public_key = var.ssh_public_key != "" ? var.ssh_public_key : file("${path.module}/../keys/key.pub")
  vm_macs        = ["52:54:00:20:00:01", "52:54:00:20:00:02", "52:54:00:20:00:03"]

  # Pinning de CPU: cada VM a un núcleo físico completo (2 hilos SMT), sin
  # compartir núcleo con el host ni con otra VM. Núcleo 0 (hilos 0-1) queda
  # reservado para el host/observabilidad, fuera de este mapeo. Mismo
  # mapeo que k3sHA (nunca corren simultáneo, sin conflicto).
  vm_cpusets = [["2", "3"], ["4", "5"], ["6", "7"]]
}

# Generación del inventario de Ansible directamente desde Terraform
resource "local_file" "ansible_inventory" {
  content = join("\n", [
    "# Grupo de servidores microk8s",
    "[microk8s_servers]",
    join("\n", [
      for i in range(var.vm_count) :
      "${var.vm_names[i]} ansible_host=${var.vm_ips[i]}"
    ]),
    "",
    "# Grupo principal que incluye todos los servidores microk8s",
    "[microk8s_cluster:children]",
    "microk8s_servers",
    "",
    "# Variables compartidas para el grupo microk8s_cluster",
    "[microk8s_cluster:vars]",
    "ansible_user=${var.cluster_user}",
    "cluster_user=${var.cluster_user}",
    "vip_address=${var.vip_address}",
    "ansible_ssh_private_key_file=../keys/key",
  ])
  filename = "${path.module}/../ansible/inventory.ini"
}

# Creación de la red virtual microk8s-tesis en modo nat
resource "libvirt_network" "microk8s_network" {
  name      = var.network_name
  mode      = "nat"
  domain    = "microk8s-tesis.local"
  addresses = [var.network_cidr]

  # DHCP habilitado: IP estática por reserva de host (MAC->IP) vía
  # el atributo `addresses` de cada network_interface más abajo.
  dhcp {
    enabled = true
  }

  # DNS habilitado: el netplan de las VMs ya no fija nameservers estáticos
  # (viene todo por DHCP), así que dnsmasq debe resolver/reenviar consultas
  # o los nodos no tienen resolución de nombres para apt/descargas.
  dns {
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

# Definición de cada máquina virtual microk8s
resource "libvirt_domain" "microk8s_node" {
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

  # Pinning de CPU (el provider no expone cputune/vcpupin nativo, se inyecta
  # vía XSLT sobre el XML generado).
  xml {
    xslt = templatefile("${path.module}/config/vcpupin.xsl.tftpl", {
      cpu0 = local.vm_cpusets[count.index][0]
      cpu1 = local.vm_cpusets[count.index][1]
    })
  }

  # Interfaz de red conectada a la red microk8s-tesis.
  # `addresses` fija la reserva DHCP por MAC (IP estática determinística).
  network_interface {
    network_id     = libvirt_network.microk8s_network.id
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

# Salida con las direcciones IP de cada nodo microk8s
output "vm_ips" {
  value = {
    for i in range(var.vm_count) : var.vm_names[i] => var.vm_ips[i]
  }
  description = "Direcciones IP de los nodos microk8s"
}

# Salida con la dirección IP virtual del plano de control (kube-vip)
output "vip_address" {
  value       = var.vip_address
  description = "Dirección IP virtual del plano de control (kube-vip)"
}
