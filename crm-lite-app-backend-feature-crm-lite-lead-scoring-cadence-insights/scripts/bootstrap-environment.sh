#!/usr/bin/env bash
# Skeleton: provision base Azure resources for the CLM service. TODO: fill values.
set -euo pipefail

RG="${RG:-rg-clm}"
LOCATION="${LOCATION:-eastus}"

echo "TODO: az group create --name $RG --location $LOCATION"
echo "TODO: provision PostgreSQL flexible server (or Azure SQL) + database"
echo "TODO: provision Key Vault + store DATABASE_URL secret"
echo "TODO: provision Azure Container Registry (ACR)"
