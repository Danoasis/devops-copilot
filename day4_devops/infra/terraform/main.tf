# The cloud twin of the local setup: kind -> AKS, `kind load` -> ACR pull via
# managed identity, Jaeger/Prometheus -> Log Analytics + Azure Monitor.
# Validated with `terraform init -backend=false && terraform validate && terraform plan`
# — a real reviewable plan, zero spend until apply.

resource "azurerm_resource_group" "main" {
  name     = "rg-${var.project}"
  location = var.location
}

resource "azurerm_log_analytics_workspace" "main" {
  name                = "log-${var.project}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  sku                 = "PerGB2018"
  retention_in_days   = 30
}

resource "azurerm_container_registry" "main" {
  name                = "acr${var.project}"
  resource_group_name = azurerm_resource_group.main.name
  location            = azurerm_resource_group.main.location
  sku                 = "Basic"
  admin_enabled       = false # identities, not passwords
}

resource "azurerm_kubernetes_cluster" "main" {
  name                = "aks-${var.project}"
  location            = azurerm_resource_group.main.location
  resource_group_name = azurerm_resource_group.main.name
  dns_prefix          = var.project

  default_node_pool {
    name       = "default"
    node_count = var.node_count
    vm_size    = var.node_vm_size
  }

  identity {
    type = "SystemAssigned"
  }

  oms_agent {
    log_analytics_workspace_id = azurerm_log_analytics_workspace.main.id
  }
}

# Let AKS pull from ACR with its managed identity — no imagePullSecrets,
# nothing to rotate (the same lesson as KB-008's workload identity federation).
resource "azurerm_role_assignment" "aks_acr_pull" {
  scope                            = azurerm_container_registry.main.id
  role_definition_name             = "AcrPull"
  principal_id                     = azurerm_kubernetes_cluster.main.kubelet_identity[0].object_id
  skip_service_principal_aad_check = true
}
