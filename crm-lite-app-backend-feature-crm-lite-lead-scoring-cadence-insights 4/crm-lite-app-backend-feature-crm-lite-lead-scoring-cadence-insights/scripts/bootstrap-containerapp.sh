#!/usr/bin/env bash
# Skeleton: deploy the container to Azure Container Apps. TODO: fill values.
set -euo pipefail

RG="${RG:-rg-clm}"
APP="${APP:-clm-service}"

echo "TODO: az containerapp env create ..."
echo "TODO: az containerapp create --name $APP --resource-group $RG \\"
echo "        --image <acr>.azurecr.io/$APP:latest --target-port 8000 --ingress external"
echo "TODO: set secrets/env (DATABASE_URL from Key Vault, gateway header names)"
