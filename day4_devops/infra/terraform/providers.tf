terraform {
  required_version = ">= 1.7"
  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
  }

  # Remote state with locking — REQUIRED for teams (FUNDAMENTALS ch.9: two
  # concurrent applies against local state is how infrastructure dies).
  # Commented for the local-only demo; uncomment + `terraform init -migrate-state`.
  # backend "azurerm" {
  #   resource_group_name  = "rg-tfstate"
  #   storage_account_name = "sttfstatedevopscopilot"
  #   container_name       = "tfstate"
  #   key                  = "devops-copilot.tfstate"
  # }
}

provider "azurerm" {
  features {}
}
