# Apex Development Setup

Quick guide to get Apex running locally.

## Prerequisites

- Python 3.11+
- An LLM API key (Anthropic or OpenAI)

## Setup

### 1. Clone and enter the project

```bash
cd Zero/apex
```

### 2. Create virtual environment

```bash
python -m venv .venv

# Windows
.venv\Scripts\activate

# Mac/Linux
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -e ".[dev]"
```

Or manually:
```bash
pip install litellm anthropic openai send2trash
```

### 4. Set your API key

```bash
# Windows PowerShell
$env:ANTHROPIC_API_KEY = "sk-ant-your-key-here"

# Windows CMD
set ANTHROPIC_API_KEY=sk-ant-your-key-here

# Mac/Linux
export ANTHROPIC_API_KEY=sk-ant-your-key-here
```

### 5. Run the CLI

```bash
python cli.py
```

## Usage

The CLI is for development/testing. Type natural language requests:

```
🤖 Apex> clean up my downloads

📋 Organize Downloads folder by moving files into category folders...

  [0] 📁 MOVE
      Source: C:\Users\You\Downloads\report.pdf
      Dest:   C:\Users\You\Downloads\Documents\report.pdf
      Reason: Organize document files
  
  [1] 🗑️ DELETE
      Source: C:\Users\You\Downloads\old_installer.exe
      Reason: Old installer, likely already installed

💡 Type 'approve' to execute, 'reject' to cancel

🤖 Apex> approve
✅ Completed: 2 succeeded
```

## Commands

| Command | Description |
|---------|-------------|
| `approve` or `a` | Execute all proposed actions |
| `approve 0 2` | Execute only actions 0 and 2 |
| `reject` or `r` | Cancel the current plan |
| `skills` | List registered skills |
| `memory` | Show remembered facts |
| `quit` or `q` | Exit |

## Project Structure

```
apex/
├── cli.py              # Development CLI
├── pyproject.toml      # Python package config
├── src/
│   ├── core/
│   │   ├── skill.py       # Skill base class & registry
│   │   ├── memory.py      # Persistent fact storage
│   │   ├── orchestrator.py # Task coordination
│   │   └── llm.py         # LLM integration
│   └── skills/
│       └── file_organizer.py  # First skill
├── docs/               # Documentation
└── spikes/            # Technical experiments
```

## Adding a New Skill

1. Create `src/skills/my_skill.py`:

```python
from ..core.skill import Skill, ActionPlan, register_skill

class MySkill(Skill):
    name = "my_skill"
    description = "Does something cool"
    trigger_phrases = ["do the thing", "my skill"]
    
    async def analyze(self, request: str, context: dict) -> ActionPlan:
        # Generate plan
        return ActionPlan(summary="...", reasoning="...")
    
    async def execute(self, plan: ActionPlan, approved: list[int]) -> dict:
        # Execute approved actions
        return {"success": [...], "failed": [...]}

# Register it
register_skill(MySkill())
```

2. Import in `src/skills/__init__.py`

That's it. The skill is now available.

## Next Steps

- [ ] Run `python cli.py` and test file organization
- [ ] Try different requests to see how the LLM responds
- [ ] Check `~/.apex/memory/facts.json` to see what Apex remembers
- [ ] Look at the Tauri docs for building the desktop UI

## Troubleshooting

**"No LLM API key found"**
- Set `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` environment variable

**"ModuleNotFoundError"**
- Make sure you're in the `apex` directory
- Run `pip install -e .` to install the package

**"Permission denied" on file operations**
- Apex can only modify files you have permission to modify
- Run as administrator if needed (not recommended)
