# Traefik configuration reference index

> Configuration surface for Traefik and Traefik Hub, generated from the Go source code. OSS pages live under `reference/oss/`, Hub pages under `reference/hub/`. Each entry maps to a `reference/<source>/<path>.md` file.

Use this index to pick which concepts you need, then load their detailed pages.

## HTTP middlewares

Per-request transformations applied between routers and services.

- `http.middlewares.ratelimit` , RateLimit , RateLimit holds the rate limit configuration. This middleware ensures that services receive a fair amount of requests.
- `http.middlewares.stripprefix` , StripPrefix , StripPrefix removes the specified prefixes from the URL path.

## Hub middlewares

AI-gateway and Hub-specific middlewares.

- `hub.middlewares.tokenratelimit` , TokenRateLimit , TokenRateLimit holds the token-based rate limit configuration for the AI gateway.

## Hub CRDs

- `crd.api` , API , API defines an HTTP interface that is exposed to external clients.
