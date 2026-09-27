# Configuración de Terraform y proveedores
terraform {
  required_version = ">= 1.0"

  required_providers {
    libvirt = {
      source  = "dmacvicar/libvirt"
      version = "= 0.7.6"
    }
    local = {
      source  = "hashicorp/local"
      version = "~> 2.0"
    }
  }
}
