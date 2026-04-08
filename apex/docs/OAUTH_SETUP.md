# OAuth Setup Guide

This guide walks you through setting up OAuth for each supported provider.

## Quick Start

1. Copy `.env.example` to `.env`
2. Add credentials for providers you want to use
3. Restart Ziggy

---

## Google (Gmail, Calendar, Drive, Contacts, Photos, Sheets, Slides)

**One OAuth = 7 services!**

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project (name it "Ziggy")
3. **APIs & Services → Library** → Enable:
   - Gmail API
   - Google Calendar API
   - Google Drive API
   - Google Contacts API
   - Google Photos Library API
   - Google Sheets API
   - Google Slides API
4. **APIs & Services → OAuth consent screen**
   - User Type: External
   - App name: "Ziggy"
   - Add scopes: `.../auth/gmail.modify`, `.../auth/calendar`, etc.
   - Add yourself as a test user
5. **APIs & Services → Credentials → Create Credentials → OAuth Client ID**
   - Application type: Desktop app
   - Download JSON file
6. Save the JSON file to: `~/.apex/google_credentials.json`

---

## Microsoft (Outlook, OneDrive, Calendar, Tasks, Contacts)

**One OAuth = 5 services!**

1. Go to [Azure Portal](https://portal.azure.com/)
2. **Azure Active Directory → App registrations → New registration**
   - Name: "Ziggy"
   - Supported account types: "Personal Microsoft accounts only" (for @outlook.com)
     OR "Accounts in any organizational directory and personal" (for work + personal)
   - Redirect URI: Web → `http://localhost:8000/oauth/callback`
3. Copy the **Application (client) ID** → `MICROSOFT_CLIENT_ID`
4. **Certificates & secrets → New client secret**
   - Copy the secret value → `MICROSOFT_CLIENT_SECRET`
5. **API permissions → Add a permission → Microsoft Graph → Delegated**:
   - `User.Read`
   - `Mail.Read`, `Mail.Send`, `Mail.ReadWrite`
   - `Calendars.Read`, `Calendars.ReadWrite`
   - `Files.Read`, `Files.ReadWrite`
   - `Tasks.Read`, `Tasks.ReadWrite`
   - `Contacts.Read`
   - `offline_access`

Add to `.env`:
```
MICROSOFT_CLIENT_ID=your-client-id
MICROSOFT_CLIENT_SECRET=your-client-secret
```

---

## Discord

1. Go to [Discord Developer Portal](https://discord.com/developers/applications)
2. **New Application** → Name it "Ziggy"
3. Copy **Application ID** → `DISCORD_CLIENT_ID`
4. **OAuth2 → General**
   - Add Redirect: `http://localhost:8000/oauth/callback`
5. Copy **Client Secret** → `DISCORD_CLIENT_SECRET`

Add to `.env`:
```
DISCORD_CLIENT_ID=your-client-id
DISCORD_CLIENT_SECRET=your-client-secret
```

---

## Slack

1. Go to [Slack API](https://api.slack.com/apps)
2. **Create New App → From scratch**
   - App Name: "Ziggy"
   - Pick a workspace
3. **OAuth & Permissions**
   - Add Redirect URL: `http://localhost:8000/oauth/callback`
   - Add Bot Token Scopes:
     - `channels:read`, `channels:history`
     - `chat:write`
     - `users:read`, `users:read.email`
     - `team:read`
4. **Basic Information**
   - Copy **Client ID** → `SLACK_CLIENT_ID`
   - Copy **Client Secret** → `SLACK_CLIENT_SECRET`

Add to `.env`:
```
SLACK_CLIENT_ID=your-client-id
SLACK_CLIENT_SECRET=your-client-secret
```

---

## GitHub

1. Go to [GitHub Settings → Developer settings → OAuth Apps](https://github.com/settings/developers)
2. **New OAuth App**
   - Application name: "Ziggy"
   - Homepage URL: `http://localhost:8000`
   - Authorization callback URL: `http://localhost:8000/oauth/callback`
3. Copy **Client ID** → `GITHUB_CLIENT_ID`
4. Generate a **Client secret** → `GITHUB_CLIENT_SECRET`

Add to `.env`:
```
GITHUB_CLIENT_ID=your-client-id
GITHUB_CLIENT_SECRET=your-client-secret
```

---

## Spotify

1. Go to [Spotify Developer Dashboard](https://developer.spotify.com/dashboard)
2. **Create app**
   - App name: "Ziggy"
   - Redirect URI: `http://localhost:8000/oauth/callback`
   - APIs: Web API
3. Copy **Client ID** → `SPOTIFY_CLIENT_ID`
4. Click **Show Client Secret** → `SPOTIFY_CLIENT_SECRET`

Add to `.env`:
```
SPOTIFY_CLIENT_ID=your-client-id
SPOTIFY_CLIENT_SECRET=your-client-secret
```

---

## API Key Providers (No OAuth Needed)

### Todoist
1. Go to [Todoist Settings → Integrations → Developer](https://todoist.com/app/settings/integrations/developer)
2. Copy your API token → `TODOIST_API_TOKEN`

### Twilio (SMS)
1. Go to [Twilio Console](https://console.twilio.com/)
2. Copy Account SID → `TWILIO_ACCOUNT_SID`
3. Copy Auth Token → `TWILIO_AUTH_TOKEN`
4. Get a phone number → `TWILIO_PHONE_NUMBER`

### Notion
1. Go to [Notion Integrations](https://www.notion.so/my-integrations)
2. Create new integration
3. Copy token → `NOTION_API_KEY`

### Linear
1. Go to [Linear Settings → API](https://linear.app/settings/api)
2. Create personal API key → `LINEAR_API_KEY`

---

## Testing Your Setup

After adding credentials, restart Ziggy:
```bash
./Telic.bat  # Windows
./run.sh     # Mac/Linux
```

The startup will show which providers are configured:
```
✅ LLM API key configured
✅ OAuth configured: discord, microsoft, slack
⚠️  OAuth not configured: github, spotify (add to .env)
```

Then visit `http://localhost:8000/setup` to connect your accounts.
