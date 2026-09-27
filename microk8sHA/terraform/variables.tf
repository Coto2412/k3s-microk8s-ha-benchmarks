# Cantidad de máquinas virtuales a crear
variable "vm_count" {
  description = "Cantidad de máquinas virtuales a crear"
  type        = number
  default     = 3
}

# Memoria RAM asignada a cada VM en MB
variable "vm_memory" {
  description = "Memoria RAM por máquina virtual en MB"
  type        = number
  default     = 4096
}

# Cantidad de vCPUs asignados a cada VM
variable "vm_cpu" {
  description = "Cantidad de vCPUs por máquina virtual"
  type        = number
  default     = 2
}

# Tamaño del disco raíz de cada VM en GB
variable "vm_disk_size" {
  description = "Tamaño del disco raíz en GB"
  type        = number
  default     = 50
}

# Nombre de la red libvirt
variable "network_name" {
  description = "Nombre de la red libvirt"
  type        = string
  default     = "microk8s-tesis"
}

# Rango CIDR de la red libvirt
variable "network_cidr" {
  description = "Rango CIDR de la red libvirt"
  type        = string
  default     = "192.168.100.0/24"
}

# Ruta de la imagen cloud de Ubuntu 24.04 LTS (sin valor por defecto — debe
# definirse en tfvars; no se hardcodea ruta local ni queda log de usuario/host)
variable "base_image" {
  description = "Ruta de la imagen cloud de Ubuntu 24.04 LTS (noble)"
  type        = string
}

# Llave pública SSH para acceso a las VMs
variable "ssh_public_key" {
  description = "Llave pública SSH para acceso a las máquinas virtuales"
  type        = string
  default     = ""
}

# Ruta de la llave privada SSH
variable "ssh_private_key" {
  description = "Ruta de la llave privada SSH"
  type        = string
  default     = "../keys/key"
}

# Usuario administrativo del clúster (se crea en las VMs y es el que usa Ansible)
variable "cluster_user" {
  description = "Usuario administrativo para las máquinas virtuales y conexión Ansible"
  type        = string
}

# Dirección IP virtual para keepalived
variable "vip_address" {
  description = "Dirección IP virtual para keepalived"
  type        = string
  default     = "192.168.100.100"
}

# Nombres de las máquinas virtuales
variable "vm_names" {
  description = "Nombres de las máquinas virtuales"
  type        = list(string)
  default     = ["microk8s-node1", "microk8s-node2", "microk8s-node3"]
}

# Direcciones IP estáticas para las máquinas virtuales
variable "vm_ips" {
  description = "Direcciones IP estáticas para las máquinas virtuales"
  type        = list(string)
  default     = ["192.168.100.11", "192.168.100.12", "192.168.100.13"]
}
