output "provider" {
  description = "Selected provider"
  value       = var.cloud_provider
}

output "server_id" {
  description = "Server identifier"
  value       = hcloud_server.vps.id
}

output "public_ipv4" {
  description = "Public IPv4 address for SSH/bootstrap"
  value       = hcloud_server.vps.ipv4_address
}

output "public_ipv6" {
  description = "Public IPv6 address"
  value       = hcloud_server.vps.ipv6_address
}

output "admin_username" {
  description = "Admin username"
  value       = module.common_vps.admin_username
}

output "hostname" {
  description = "Server hostname"
  value       = var.hostname
}
