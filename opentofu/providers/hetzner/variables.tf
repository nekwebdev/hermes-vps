variable "cloud_provider" {
  description = "Provider selector"
  type        = string
  default     = "hetzner"

  validation {
    condition     = var.cloud_provider == "hetzner"
    error_message = "For this directory, provider must be hetzner."
  }
}

variable "hcloud_token" {
  description = "Hetzner API token. Optional if HCLOUD_TOKEN env var is set."
  type        = string
  default     = null
  nullable    = true
  sensitive   = true

  validation {
    condition     = var.hcloud_token == null || length(trimspace(var.hcloud_token)) > 0
    error_message = "If hcloud_token is set, it must be non-empty."
  }
}

variable "server_location" {
  description = "Hetzner location"
  type        = string
}

variable "server_type" {
  description = "Hetzner instance type"
  type        = string
}

variable "server_image" {
  description = "Image slug (must map to Debian 13)"
  type        = string
  default     = "debian-13"

  validation {
    condition     = lower(trimspace(var.server_image)) == "debian-13"
    error_message = "server_image must be debian-13 for this baseline."
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
  description = "Enable public IPv6"
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
