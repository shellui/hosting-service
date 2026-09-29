# Configuration

Operators configure hosting-service with environment variables (see [`.env.example`](../.env.example) in the repository root). Copy it to `.env` for local runs; pass the same keys to Docker, Coolify, or your orchestrator in production.

---

## Shared cache (Redis)

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `REDIS_URL` | unset | Django Redis cache backend for hosting rate limits (deploy, upload, destructive, access request) |

When unset, Django uses in-process **LocMem** (fine for local dev or a single Gunicorn worker). With **`GUNICORN_WORKERS` > 1**, set `REDIS_URL` so limits are shared across workers. `manage.py check --deploy` emits **`authapi.W001`** when production uses LocMem with multiple workers.

Examples:

```bash
# Docker Compose / Coolify internal Redis
REDIS_URL=redis://redis:6379/0
```

See [PUBLISH.md](../PUBLISH.md) for Coolify Redis setup.

---

## Gunicorn (Docker entrypoint)

| Variable | Default | Purpose |
| -------- | ------- | ------- |
| `GUNICORN_WORKERS` | `2` | Sync worker processes |
| `GUNICORN_THREADS` | `2` | Threads per worker |
| `GUNICORN_TIMEOUT` | `120` | Worker request timeout (large artifact uploads) |

---

## Related

- [Security hardening](security-hardening.md)
- [Claim trust](claim-trust.md)
- [PUBLISH.md](../PUBLISH.md)
