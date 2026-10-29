---
description: Deploy a Shellui app to a 7-day preview with the Shellui CLI, locally or from GitHub Actions.
---

# Deploy with the CLI

The Shellui CLI builds your app and uploads `dist/web/` to hosting-service as a preview site. Previews are meant for workshops and demos. Set `hosting.url` in `shellui.config.json` first.

## Preview

```bash
shellui login
shellui deploy --build
```

The first deploy creates a preview site and saves `hosting.slug` in `shellui.config.json`. Commit that file so later deploys, including CI, update the same site. A preview expires 7 days after its last deploy (`HOSTING_PREVIEW_TTL_DAYS`).

## CI with a deploy token

1. In admin, open Hosting, go to Deploy tokens and create one. Copy it now: it is shown once.
2. Save it as a repository secret named `SHELLUI_DEPLOY_TOKEN`.
3. Make sure `hosting.slug` is set in `shellui.config.json`, or every run creates a new preview.
4. Add a workflow:

```yaml
name: Preview
on:
  push:
    branches: [main]
jobs:
  preview:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - run: npm ci
      - run: npx shellui deploy --build
        env:
          SHELLUI_DEPLOY_TOKEN: ${{ secrets.SHELLUI_DEPLOY_TOKEN }}
```

When `SHELLUI_DEPLOY_TOKEN` is set, the CLI skips `shellui login` and sends the token to hosting-service. It never prints the token.

A deploy token belongs to your company. It can create a preview and redeploy any preview slug of your company, nothing else: it cannot list apps, read history, deploy apps created in admin, manage tokens or delete anything. Revoke it in admin when you no longer need it.

## Errors

| Error | What to do |
| --- | --- |
| `deploy_token_invalid` | The secret is wrong or was cut. Copy a new token |
| `deploy_token_revoked` | Create a new token in admin |
| `deploy_token_expired` | Create a new token in admin |
| `deploy_token_preview_only` | `hosting.slug` names an app created in admin. Use a preview slug |
| `preview_forbidden` | `hosting.slug` belongs to another company |
