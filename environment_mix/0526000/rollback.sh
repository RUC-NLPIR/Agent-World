#!/usr/bin/env bash
set -euo pipefail
SVC=${1:?usage: rollback.sh SVC NAMESPACE}
NS=${2:-prod}
kubectl rollout undo deploy/$SVC -n $NS
echo "$SVC rolled back in $NS"
