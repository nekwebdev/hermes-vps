variable "cloud_provider" {
  description = "Target provider selector used for validation and tagging"
  type        = string

  validation {
    condition     = contains(["hetzner", "linode"], var.cloud_provider)
    error_message = "cloud_provider must be either hetzner or linode"
  }
}

variable "hostname" {
  description = "Server hostname"
  type        = string

  validation {
    condition     = can(regex("^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$", var.hostname))
    error_message = "hostname must be RFC-1123 compatible (lowercase letters, numbers, hyphens; max 63 chars)."
  }
}

variable "admin_username" {
  description = "Primary non-root admin account"
  type        = string

  validation {
    condition     = can(regex("^[a-z_][a-z0-9_-]{0,30}$", var.admin_username))
    error_message = "admin_username must be a valid Linux username (lowercase, starts with letter/_)."
  }
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
  description = "Admin SSH public key"
  type        = string
  sensitive   = true

  validation {
    condition = can(regex(
      "^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp(256|384|521))\\s+[A-Za-z0-9+/]+={0,3}(\\s+.+)?$",
      trimspace(var.admin_ssh_public_key)
    ))
    error_message = "admin_ssh_public_key must be a valid single-line OpenSSH public key."
  }
}

variable "tags" {
  description = "Common tags"
  type        = map(string)
  default     = {}
}
