output "user_data" {
  description = "Rendered cloud-init user-data"
  value       = local.user_data
  sensitive   = true
}

output "common_tags" {
  description = "Shared tags"
  value       = local.common_tags
}

output "admin_username" {
  description = "Provisioned admin user"
  value       = var.admin_username
}
