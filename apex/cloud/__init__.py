"""
Ziggy Cloud - Central OAuth Broker

This module provides centralized OAuth authentication so users
don't need to register their own apps with each provider.

Architecture:
    User's Ziggy (localhost) → Ziggy Cloud (broker) → Provider (Google/Microsoft/etc)
    
The broker:
1. Holds registered OAuth apps for each provider
2. Handles the OAuth dance
3. Returns tokens to the user's local Ziggy instance
4. Never stores user tokens (privacy-first)

Deployment:
    - Vercel (recommended)
    - Railway
    - Self-hosted

Usage:
    # In server.py, redirect to cloud broker
    redirect_url = f"https://auth.ziggy.ai/connect/{provider}?callback=http://localhost:8000/oauth/callback"
"""
