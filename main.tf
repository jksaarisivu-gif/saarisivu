terraform {
  required_version = ">= 1.5.0"
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 5.0"
    }
  }
}

provider "google" {
  project = var.project_id
  region  = var.region
}

variable "project_id" { type = string }
variable "region"     { type = string, default = "us-central1" }
variable "image_uri"  { type = string, default = "gcr.io/cloudrun/hello" }

resource "google_project_service" "required_apis" {
  for_each = toset([
    "aiplatform.googleapis.com",
    "secretmanager.googleapis.com",
    "dlp.googleapis.com",
    "run.googleapis.com",
  ])
  service            = each.key
  disable_on_destroy = false
}

resource "google_service_account" "concierge_sa" {
  account_id   = "luxury-purse-concierge-sa"
  display_name = "Luxury Purse ADK Concierge Service Account"
}

resource "google_secret_manager_secret" "gemini_secret" {
  secret_id = "gemini-api-key"
  replication { auto {} }
  depends_on = [google_project_service.required_apis]
}

resource "google_secret_manager_secret_iam_member" "secret_access" {
  secret_id = google_secret_manager_secret.gemini_secret.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.concierge_sa.email}"
}

resource "google_cloud_run_v2_service" "luxury_concierge_service" {
  name     = "luxury-purse-concierge"
  location = var.region
  template {
    service_account = google_service_account.concierge_sa.email
    containers {
      image = var.image_uri
      ports { container_port = 8080 }
      env {
        name  = "GOOGLE_GENAI_USE_VERTEXAI"
        value = "TRUE"
      }
      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }
    }
  }
  depends_on = [google_project_service.required_apis]
}
