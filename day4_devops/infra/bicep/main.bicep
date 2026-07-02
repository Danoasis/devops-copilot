// Same infrastructure as ../terraform, expressed in Bicep so the repo can speak
// to the comparison concretely (FUNDAMENTALS ch.9): Bicep = no state file (ARM
// is the desired-state engine), Azure-only, day-zero feature coverage.
// Validate offline:  az bicep build --file main.bicep
// Deploy:            az deployment group create -g rg-devopscopilot -f main.bicep

@description('Azure region for all resources.')
param location string = resourceGroup().location

@description('Project slug used in resource names.')
param project string = 'devopscopilot'

@description('AKS default node pool size.')
param nodeCount int = 2

param nodeVmSize string = 'Standard_B2s'

resource logAnalytics 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: 'log-${project}'
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: 30
  }
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-11-01-preview' = {
  name: 'acr${project}'
  location: location
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

resource aks 'Microsoft.ContainerService/managedClusters@2024-05-01' = {
  name: 'aks-${project}'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    dnsPrefix: project
    agentPoolProfiles: [
      {
        name: 'default'
        count: nodeCount
        vmSize: nodeVmSize
        mode: 'System'
      }
    ]
    addonProfiles: {
      omsagent: {
        enabled: true
        config: { logAnalyticsWorkspaceResourceID: logAnalytics.id }
      }
    }
  }
}

@description('AcrPull for the kubelet identity: pull images without secrets.')
resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, aks.id, 'AcrPull')
  scope: acr
  properties: {
    roleDefinitionId: subscriptionResourceId(
      'Microsoft.Authorization/roleDefinitions',
      '7f951dda-4ed3-4680-a7ca-43fe172d538d' // AcrPull
    )
    principalId: aks.properties.identityProfile.kubeletidentity.objectId
    principalType: 'ServicePrincipal'
  }
}

output acrLoginServer string = acr.properties.loginServer
output aksName string = aks.name
