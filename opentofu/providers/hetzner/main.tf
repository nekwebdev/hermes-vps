module "common_vps" {
  source = "../../modules/common-vps"

  cloud_provider       = var.cloud_provider
  hostname             = var.hostname
  admin_username       = var.admin_username
  admin_group          = var.admin_group
  admin_ssh_public_key = var.admin_ssh_public_key
  tags                 = var.tags
}

resource "hcloud_ssh_key" "admin" {
  name       = "${var.hostname}-${var.admin_username}"
  public_key = var.admin_ssh_public_key
}

resource "hcloud_firewall" "vps" {
  name = "${var.hostname}-fw"

  rule {
    direction  = "in"
    protocol   = "tcp"
    port       = "22"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  dynamic "rule" {
    for_each = toset(var.allowed_tcp_ports)
    content {
      direction  = "in"
      protocol   = "tcp"
      port       = tostring(rule.value)
      source_ips = ["0.0.0.0/0", "::/0"]
    }
  }

  rule {
    direction  = "in"
    protocol   = "icmp"
    source_ips = ["0.0.0.0/0", "::/0"]
  }
}

resource "hcloud_server" "vps" {
  name        = var.hostname
  server_type = var.server_type
  location    = var.server_location
  image       = var.server_image
  user_data   = module.common_vps.user_data

  ssh_keys     = [hcloud_ssh_key.admin.id]
  firewall_ids = [hcloud_firewall.vps.id]

  public_net {
    ipv4_enabled = true
    ipv6_enabled = var.enable_ipv6
  }

  labels = module.common_vps.common_tags
}
