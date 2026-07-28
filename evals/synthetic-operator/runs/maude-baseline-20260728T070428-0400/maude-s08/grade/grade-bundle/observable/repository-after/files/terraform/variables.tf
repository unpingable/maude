variable "replicas" {
  type        = number
  description = "Desired worker replicas"

  validation {
    condition     = var.replicas >= 1 && var.replicas <= 50
    error_message = "replicas must be between 1 and 50"
  }
}
