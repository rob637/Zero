# Ziggy OAuth Broker

Central OAuth authentication service for Ziggy AI OS.

## What This Does

Users click "Connect Google" → this broker handles OAuth → tokens returned to local Ziggy.

**Users never need to register their own OAuth apps.**

## Quick Deploy

### Vercel (Recommended)

```bash
cd cloud
vercel deploy --prod
```

Set environment variables in Vercel dashboard:
- `GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET`
- `MICROSOFT_CLIENT_ID` / `MICROSOFT_CLIENT_SECRET`
- `SLACK_CLIENT_ID` / `SLACK_CLIENT_SECRET`
- `DISCORD_CLIENT_ID` / `DISCORD_CLIENT_SECRET`
- `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET`
- `BROKER_SECRET` (random string for signing)
- `BROKER_REDIRECT_URI` (e.g., `https://your-app.vercel.app/callback`)

### Railway

Push to Railway, set same env vars.

### Self-Hosted

```bash
pip install -r requirements.txt
uvicorn broker:app --host 0.0.0.0 --port 8080
```

## How It Works

1. User's local Ziggy redirects to: `https://broker/connect/google?callback=http://localhost:8000/oauth/callback`
2. Broker redirects to Google OAuth
3. User authorizes
4. Google redirects back to broker
5. Broker exchanges code for tokens
6. Broker redirects to user's localhost with tokens

**Privacy**: Tokens are passed directly to user's machine. The broker never stores them.

## Registering OAuth Apps

### Google
1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create project "Ziggy"
3. APIs & Services → OAuth consent screen → External
4. Create OAuth 2.0 Client ID (Web application)
5. Add redirect URI: `https://your-broker.vercel.app/callback`

### Microsoft
1. Go to [Azure Portal](https://portal.azure.com)
2. Azure AD → App registrations → New
3. Add redirect URI: `https://your-broker.vercel.app/callback`
4. Certificates & secrets → New client secret

### Slack
1. Go to [Slack API](https://api.slack.com/apps)
2. Create New App → From scratch
3. OAuth & Permissions → Add redirect URL

### Discord
1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. New Application
3. OAuth2 → Add redirect

### GitHub
1. Go to [GitHub Settings → Developer Settings](https://github.com/settings/developers)
2. OAuth Apps → New OAuth App
3. Add callback URL

## API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /` | Health check |
| `GET /providers` | List available providers |
| `GET /connect/{provider}?callback=...` | Start OAuth flow |
| `GET /callback` | OAuth callback (internal) |
| `POST /refresh/{provider}` | Refresh access token |

## Environment Variables

```env
# Google
GOOGLE_CLIENT_ID=xxx
GOOGLE_CLIENT_SECRET=xxx

# Microsoft
MICROSOFT_CLIENT_ID=xxx
MICROSOFT_CLIENT_SECRET=xxx

# Slack
SLACK_CLIENT_ID=xxx
SLACK_CLIENT_SECRET=xxx

# Discord  
DISCORD_CLIENT_ID=xxx
DISCORD_CLIENT_SECRET=xxx

# GitHub
GITHUB_CLIENT_ID=xxx
GITHUB_CLIENT_SECRET=xxx

# Spotify (optional)
SPOTIFY_CLIENT_ID=xxx
SPOTIFY_CLIENT_SECRET=xxx

# Notion (optional)
NOTION_CLIENT_ID=xxx
NOTION_CLIENT_SECRET=xxx

# Security
BROKER_SECRET=random-string-for-signing
BROKER_REDIRECT_URI=https://your-broker.vercel.app/callback

# Development
DEV_MODE=false
```
