# Architecture Overview

Acme runs a service-oriented architecture on Kubernetes with a Postgres primary and read replicas.

## Core services
- checkout-svc — owns cart and order creation
- payments-svc — integrates with the gateway
- search-svc — OpenSearch-backed product search
- analytics-svc — streams events to the warehouse

## Datastores
- Postgres (primary + 2 replicas)
- Redis (sessions, rate limiting)
- OpenSearch (product search)
- S3 (object storage, ML artifacts)
