module "common_vps" {
  source = "../../modules/common-vps"

  cloud_provider       = var.cloud_provider
  hostname             = var.hostname
  admin_username       = var.admin_username
  admin_group          = var.admin_group
  admin_ssh_public_key = var.admin_ssh_public_key
  tags                 = var.tags
}

resource "linode_instance" "vps" {
  label           = var.hostname
  region          = var.server_location
  type            = var.server_type
  image           = var.server_image
  authorized_keys = [var.admin_ssh_public_key]
  root_pass       = random_password.bootstrap.result
  tags            = [for k, v in module.common_vps.common_tags : "${k}:${v}"]
  private_ip      = false
  backups_enabled = false

  metadata {
    user_data = base64encode(module.common_vps.user_data)
  }
}

resource "random_password" "bootstrap" {
  length  = 32
  special = true
}
