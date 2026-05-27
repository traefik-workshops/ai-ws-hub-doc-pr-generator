---
schema_version: 2
kind: middleware-http
name: TokenRateLimit
id: hub.middlewares.tokenratelimit
source: hub
traefik_version: v3.20.2
extracted_from:
  - hub/pkg/middleware/tokenratelimit/config.go
  - hub/pkg/middleware/tokenratelimit/middleware.go
summary: TokenRateLimit holds the token-based rate limit configuration for the AI gateway.
fields:
  - name: limit
    go_name: Limit
    type: integer
    go_type: int
  - name: period
    go_name: Period
    type: duration
  - name: strategy
    go_name: Strategy
    type: string
    go_type: '*StrategyConfig'
representations:
  yaml_path: spec
  crd:
    apiVersion: hub.traefik.io/v1alpha1
    kind: TokenRateLimit
---

# TokenRateLimit

TokenRateLimit holds the token-based rate limit configuration for the AI gateway.
