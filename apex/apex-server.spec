# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for Telic backend → apex-server.exe

Bundles the entire Python backend (FastAPI, connectors, intelligence,
primitives, etc.) into a single directory for Tauri sidecar.

Run from the apex/ directory:
    pyinstaller apex-server.spec
"""

import sys
from pathlib import Path

block_cipher = None

# Collect all Python source directories
_root = Path('.').resolve()
_data = [
    # Directories to include as data (non-importable or mixed)
    ('ui', 'ui'),
    ('sqlite', 'sqlite'),
]

# Hidden imports — modules discovered at runtime, not by static analysis
_hidden = [
    # FastAPI / Uvicorn internals
    'uvicorn.logging',
    'uvicorn.loops',
    'uvicorn.loops.auto',
    'uvicorn.protocols',
    'uvicorn.protocols.http',
    'uvicorn.protocols.http.auto',
    'uvicorn.protocols.websockets',
    'uvicorn.protocols.websockets.auto',
    'uvicorn.lifespan',
    'uvicorn.lifespan.on',

    # Our modules that get imported dynamically
    'server_state',
    'apex_engine',
    'react_agent',
    'intent_router',
    'sessions',
    'routines',
    'webhooks',
    'sync_engine',
    'index',
    'local_files',
    'semantic_search',

    # Route modules
    'routes',
    'routes.oauth',
    'routes.react',
    'routes.intelligence',
    'routes.routines',

    # Primitives
    'primitives',
    'primitives.base',
    'primitives.communication',
    'primitives.productivity',
    'primitives.data',
    'primitives.lifestyle',
    'primitives.services',
    'primitives.system',
    'primitives.web',

    # Connectors (all of them)
    'connectors',
    'connectors.base',
    'connectors.registry',
    'connectors.resolver',
    'connectors.unified',
    'connectors.credentials',
    'connectors.oauth_flow',
    'connectors.google_auth',
    'connectors.microsoft_auth',
    'connectors.calendar',
    'connectors.gmail',
    'connectors.drive',
    'connectors.contacts',
    'connectors.google_sheets',
    'connectors.google_slides',
    'connectors.google_photos',
    'connectors.slack',
    'connectors.github',
    'connectors.discord',
    'connectors.spotify',
    'connectors.todoist',
    'connectors.notion',
    'connectors.linear',
    'connectors.jira',
    'connectors.trello',
    'connectors.hubspot',
    'connectors.weather',
    'connectors.news',
    'connectors.web_search',
    'connectors.reddit',
    'connectors.twitter',
    'connectors.linkedin',
    'connectors.telegram',
    'connectors.twilio_sms',
    'connectors.stripe',
    'connectors.zoom',
    'connectors.teams',
    'connectors.outlook',
    'connectors.outlook_calendar',
    'connectors.onedrive',
    'connectors.onenote',
    'connectors.microsoft_contacts',
    'connectors.microsoft_excel',
    'connectors.microsoft_powerpoint',
    'connectors.microsoft_todo',
    'connectors.microsoft_graph',
    'connectors.dropbox',
    'connectors.airtable',
    'connectors.youtube',
    'connectors.smartthings',
    'connectors.desktop_notify',
    'connectors.devtools',
    'connectors.broker_client',

    # Intelligence modules
    'intelligence',
    'intelligence.semantic_memory',
    'intelligence.pattern_recognition',
    'intelligence.preference_learning',
    'intelligence.proactive_monitor',

    # src subpackages
    'src',
    'src.core',
    'src.core.llm',
    'src.privacy',
    'src.privacy.redaction',
    'src.privacy.audit_log',
    'src.control',
    'src.control.trust_levels',
    'src.control.approval_gateway',
    'src.control.undo_manager',
    'src.control.action_history',
    'src.storage',
    'src.brain',

    # Third-party that might be missed
    'httpx',
    'dotenv',
    'anthropic',
    'google.auth',
    'google.oauth2',
    'google.auth.transport.requests',
    'google_auth_oauthlib',
    'googleapiclient',
    'googleapiclient.discovery',
    'cryptography',
    'PIL',
]

a = Analysis(
    ['server.py'],
    pathex=[str(_root)],
    binaries=[],
    datas=_data,
    hiddenimports=_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter', 'matplotlib', 'scipy', 'pandas',
        'IPython', 'notebook', 'pytest',
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='apex-server',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # Keep console for logging
    icon='src-tauri/icons/icon.ico',
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='apex-server',
)
