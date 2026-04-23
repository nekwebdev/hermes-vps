output "provider" {
  description = "Selected provider"
  value       = var.cloud_provider
}

output "server_id" {
  description = "Server identifier"
  value       = linode_instance.vps.id
}

output "public_ipv4" {
  description = "Public IPv4 address for SSH/bootstrap"
  value       = one(linode_instance.vps.ipv4)
}

output "public_ipv6" {
  description = "Public IPv6 address"
  value       = try(linode_instance.vps.ipv6, "")
}

output "admin_username" {
  description = "Admin username"
  value       = module.common_vps.admin_username
}

output "hostname" {
  description = "Server hostname"
  value       = var.hostname
}
