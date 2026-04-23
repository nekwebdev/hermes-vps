terraform {
  required_version = "~> 1.8.7"

  required_providers {
    linode = {
      source  = "linode/linode"
      version = "~> 3.11.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.8.1"
    }
  }
}
