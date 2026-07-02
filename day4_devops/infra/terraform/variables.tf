variable "location" {
  description = "Azure region."
  type        = string
  default     = "brazilsouth"
}

variable "project" {
  description = "Project slug used in resource names."
  type        = string
  default     = "devopscopilot"
}

variable "node_count" {
  description = "AKS default node pool size."
  type        = number
  default     = 2
}

variable "node_vm_size" {
  description = "AKS node VM size (B-series keeps the demo cheap)."
  type        = string
  default     = "Standard_B2s"
}
