variable "cloud_provider" {
  description = "Provider selector"
  type        = string
  default     = "linode"

  validation {
    condition     = var.cloud_provider == "linode"
    error_message = "For this directory, provider must be linode."
  }
}

variable "linode_token" {
  description = "Linode API token. Optional if LINODE_TOKEN env var is set."
  type        = string
  default     = null
  nullable    = true
  sensitive   = true

  validation {
    condition     = var.linode_token == null || length(trimspace(var.linode_token)) > 0
    error_message = "If linode_token is set, it must be non-empty."
  }
}

variable "server_location" {
  description = "Linode region"
  type        = string
}

variable "server_type" {
  description = "Linode plan type"
  type        = string
}

variable "server_image" {
  description = "Image slug (must map to Debian 12)"
  type        = string
  default     = "linode/debian12"

  validation {
    condition = contains(
      ["linode/debian12", "private/linode/debian12"],
      lower(trimspace(var.server_image))
    ) || can(regex("debian12$", lower(trimspace(var.server_image))))
    error_message = "server_image must point to a Debian 12 Linode image."
  }
}

variable "hostname" {
  description = "Hostname"
  type        = string
}

variable "admin_username" {
  description = "Admin user"
  type        = string
}

variable "admin_group" {
  description = "SSH allow-group"
  type        = string
  default     = "sshadmins"

  validation {
    condition     = var.admin_group == "sshadmins"
    error_message = "admin_group is fixed to sshadmins to match hardened sshd AllowGroups."
  }
}

variable "admin_ssh_public_key" {
  description = "Admin public key"
  type        = string
  sensitive   = true
}

variable "enable_ipv6" {
  description = "Enable IPv6"
  type        = bool
  default     = true
}

variable "allowed_tcp_ports" {
  description = "Additional firewall ports"
  type        = list(number)
  default     = []

  validation {
    condition = alltrue([
      for port in var.allowed_tcp_ports :
      port >= 1 && port <= 65535 && port == floor(port)
    ]) && length(var.allowed_tcp_ports) == length(distinct(var.allowed_tcp_ports))
    error_message = "allowed_tcp_ports must contain unique integer values in range 1-65535."
  }
}

variable "tags" {
  description = "Resource tags"
  type        = map(string)
  default     = {}
}

variable "hermes_model" {
  description = "Hermes model identifier"
  type        = string
  default     = "anthropic/claude-sonnet-4"
}

variable "hermes_provider" {
  description = "Hermes provider identifier"
  type        = string
  default     = "openrouter"
}
