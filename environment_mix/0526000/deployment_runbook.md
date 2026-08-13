# Deployment Runbook

## Pre-flight
1. Confirm green CI on main
2. Post deploy plan in #deploys
3. Check the on-call schedule

## Deploy
```bash
make deploy SVC=payments ENV=prod
make smoke SVC=payments ENV=prod
```

## Rollback
```bash
kubectl rollout undo deploy/payments -n prod
```
If smoke tests fail, rollback immediately and file an incident.
