#!/usr/bin/env bash
set -euo pipefail
SVC=${1:?usage: deploy.sh SVC ENV}
ENV=${2:?usage: deploy.sh SVC ENV}
make deploy SVC=$SVC ENV=$ENV
make smoke SVC=$SVC ENV=$ENV
echo "$SVC deployed to $ENV"
