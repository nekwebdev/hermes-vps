locals {
  common_tags = merge(var.tags, {
    managed_by = "opentofu"
    stack      = "hermes-vps"
    provider   = var.cloud_provider
  })

  bootstrap_script = templatefile("${path.module}/../../cloud-init/bootstrap-runner.sh.tftpl", {})

  user_data = templatefile("${path.module}/../../cloud-init/user-data.yaml.tftpl", {
    hostname             = var.hostname
    admin_username       = var.admin_username
    admin_group          = var.admin_group
    admin_ssh_public_key = var.admin_ssh_public_key
    bootstrap_script     = indent(6, local.bootstrap_script)
  })
}
