---
description: Deploy a Shellui app to preview or production with the Shellui CLI, locally or from GitHub Actions.
---

# Deploy with the CLI

The Shellui CLI builds your app and uploads `dist/web/` to hosting-service. Set `hosting.url` in `shellui.config.json` first.

## Preview

```bash
shellui login
shellui deploy --build
```

The first deploy creates a preview site and saves `hosting.slug` in `shellui.config.json`. A preview expires 7 days after its last deploy (`HOSTING_PREVIEW_TTL_DAYS`).

## Production

1. In admin, open Hosting > Apps and create the app. Note its name.
2. Add it to your config:

```json
{
  "hosting": {
    "url": "https://hosting.shellui.com",
    "app": "my-app"
  }
}
```

3. Deploy:

```bash
shellui deploy --prod --build
```

`shellui deploy history` lists deployments. `shellui promote <deployment>` makes an earlier one live again.

## CI with a deploy token

1. In admin, open the app, go to Deploy tokens and create one. Copy it now: it is shown once.
2. Save it as a repository secret named `SHELLUI_DEPLOY_TOKEN`.
3. Add a workflow:

```yaml
name: Deploy
on:
  push:
    branches: [main]
jobs:
  deploy:
    runs-on: ubuntu-latest
    permissions:
      contents: read
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22
      - run: npm ci
      - run: npx shellui deploy --prod --build
        env:
          SHELLUI_DEPLOY_TOKEN: ${{ secrets.SHELLUI_DEPLOY_TOKEN }}
```

When `SHELLUI_DEPLOY_TOKEN` is set, the CLI skips `shellui login` and sends the token to hosting-service. It never prints the token.

A deploy token only deploys its own app. It cannot list apps, read history, manage tokens or delete anything. Revoke it in admin when you no longer need it.

## Errors

| Error | What to do |
| --- | --- |
| `deploy_token_invalid` | The secret is wrong or was cut. Copy a new token |
| `deploy_token_revoked` | Create a new token in admin |
| `deploy_token_expired` | Create a new token in admin |
| `deploy_token_wrong_app` | `hosting.app` names another app than the token |
| `not_production_app` | `hosting.app` is a preview site. Create the app in admin |
