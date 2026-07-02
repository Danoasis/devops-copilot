output "acr_login_server" {
  value = azurerm_container_registry.main.login_server
}

output "aks_cluster_name" {
  value = azurerm_kubernetes_cluster.main.name
}

output "kubeconfig_command" {
  value = "az aks get-credentials -g ${azurerm_resource_group.main.name} -n ${azurerm_kubernetes_cluster.main.name}"
}
