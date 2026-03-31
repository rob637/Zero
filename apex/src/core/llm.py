"""
LLM Integration - Multi-provider AI access via LiteLLM

Supports:
- Anthropic (Claude)
- OpenAI (GPT-4)
- Google (Gemini)
- And many more via LiteLLM

User provides their own API key - we're selling the platform, not subsidizing API costs.
"""

import os
import json
from dataclasses import dataclass
from typing import Any


@dataclass
class LLMConfig:
    """Configuration for LLM provider."""
    provider: str  # anthropic, openai, google, etc.
    model: str  # claude-3-5-sonnet, gpt-4o, gemini-pro, etc.
    api_key: str
    temperature: float = 0.3
    max_tokens: int = 4000


class LLMClient:
    """
    Unified interface for multiple LLM providers via LiteLLM.
    
    Usage:
        client = LLMClient(LLMConfig(
            provider="anthropic",
            model="claude-3-5-sonnet-20241022",
            api_key="sk-ant-..."
        ))
        
        response = await client.complete(
            system="You are a helpful assistant.",
            user="What's 2+2?"
        )
    """
    
    def __init__(self, config: LLMConfig):
        """
        Initialize LLM client.
        
        Args:
            config: LLM configuration
        """
        self.config = config
        self._setup_environment()
    
    def _setup_environment(self) -> None:
        """Set up environment variables for the provider."""
        provider_env_map = {
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
            "google": "GOOGLE_API_KEY",
            "azure": "AZURE_API_KEY",
        }
        
        env_var = provider_env_map.get(self.config.provider)
        if env_var:
            os.environ[env_var] = self.config.api_key
    
    async def complete(
        self,
        system: str,
        user: str,
        json_mode: bool = False,
    ) -> str:
        """
        Get a completion from the LLM.
        
        Args:
            system: System prompt
            user: User message
            json_mode: If True, expect JSON output
            
        Returns:
            LLM response text
        """
        try:
            # Import here to allow graceful degradation if not installed
            import litellm
            
            # Map provider/model to LiteLLM format
            model = self._get_litellm_model()
            
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ]
            
            response = await litellm.acompletion(
                model=model,
                messages=messages,
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
            
            return response.choices[0].message.content
            
        except ImportError:
            # Fallback to direct API calls if LiteLLM not installed
            return await self._fallback_complete(system, user)
    
    def _get_litellm_model(self) -> str:
        """Map our config to LiteLLM model format."""
        if self.config.provider == "anthropic":
            return f"anthropic/{self.config.model}"
        elif self.config.provider == "openai":
            return self.config.model  # OpenAI is default
        elif self.config.provider == "google":
            return f"gemini/{self.config.model}"
        else:
            return f"{self.config.provider}/{self.config.model}"
    
    async def _fallback_complete(self, system: str, user: str) -> str:
        """Direct API calls without LiteLLM."""
        if self.config.provider == "anthropic":
            return await self._anthropic_complete(system, user)
        elif self.config.provider == "openai":
            return await self._openai_complete(system, user)
        else:
            raise ValueError(f"Unsupported provider for fallback: {self.config.provider}")
    
    async def _anthropic_complete(self, system: str, user: str) -> str:
        """Direct Anthropic API call."""
        try:
            from anthropic import AsyncAnthropic
            
            client = AsyncAnthropic(api_key=self.config.api_key)
            response = await client.messages.create(
                model=self.config.model,
                max_tokens=self.config.max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            return response.content[0].text
        except ImportError:
            raise ImportError("Install anthropic: pip install anthropic")
    
    async def _openai_complete(self, system: str, user: str) -> str:
        """Direct OpenAI API call."""
        try:
            from openai import AsyncOpenAI
            
            client = AsyncOpenAI(api_key=self.config.api_key)
            response = await client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=self.config.temperature,
                max_tokens=self.config.max_tokens,
            )
            return response.choices[0].message.content
        except ImportError:
            raise ImportError("Install openai: pip install openai")
    
    async def complete_json(
        self,
        system: str,
        user: str,
    ) -> dict:
        """
        Get a JSON completion from the LLM.
        
        Automatically handles JSON extraction from markdown code blocks.
        
        Returns:
            Parsed JSON dict
        """
        response = await self.complete(system, user, json_mode=True)
        
        # Extract JSON from markdown code blocks if present
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0]
        elif "```" in response:
            response = response.split("```")[1].split("```")[0]
        
        return json.loads(response.strip())


# Default prompts for file organization
FILE_PLANNING_SYSTEM_PROMPT = """You are Telic, an AI operating system that helps organize files on the user's computer.

CRITICAL SAFETY RULES (NEVER VIOLATE):
1. You NEVER execute actions directly. You ONLY generate plans for user approval.
2. You NEVER delete files permanently. "Delete" ALWAYS means "move to Recycle Bin".
3. You NEVER touch:
   - System files (Windows, System32, etc.)
   - Hidden files (starting with .)
   - Files outside the specified folder
   - Sensitive files (.env, .ssh, credentials, keys)
4. When in doubt, be CONSERVATIVE. It's better to do less than to cause damage.
5. ALWAYS warn about potentially risky actions.

OUTPUT FORMAT (strict JSON):
{
  "summary": "One-sentence description of what this plan does",
  "reasoning": "2-3 sentences explaining your logic",
  "warnings": ["List of any risks or things the user should know"],
  "actions": [
    {
      "type": "move",
      "source": "filename.ext",
      "destination": "FolderName/filename.ext", 
      "reason": "Brief explanation"
    },
    {
      "type": "delete",
      "source": "filename.ext",
      "destination": "Recycle Bin",
      "reason": "Brief explanation"
    },
    {
      "type": "create_folder",
      "source": "NewFolderName",
      "reason": "Brief explanation"
    }
  ],
  "affected_files_count": 0,
  "space_freed_estimate": "0 MB",
  "files_preserved": ["List of files intentionally left alone and why"]
}

If the request is dangerous or unclear:
- Add strong warnings
- Refuse dangerous parts
- Ask clarifying questions in the summary
- Be conservative - do less, not more"""


def create_client_from_env() -> LLMClient | None:
    """
    Create an LLM client from environment variables.
    
    Checks for:
    - ANTHROPIC_API_KEY
    - OPENAI_API_KEY
    - GOOGLE_API_KEY
    
    Returns the first one found, or None.
    """
    if api_key := os.environ.get("ANTHROPIC_API_KEY"):
        return LLMClient(LLMConfig(
            provider="anthropic",
            model="claude-sonnet-4-20250514",
            api_key=api_key,
        ))
    
    if api_key := os.environ.get("OPENAI_API_KEY"):
        return LLMClient(LLMConfig(
            provider="openai",
            model="gpt-4o",
            api_key=api_key,
        ))
    
    if api_key := os.environ.get("GOOGLE_API_KEY"):
        return LLMClient(LLMConfig(
            provider="google",
            model="gemini-pro",
            api_key=api_key,
        ))
    
    return None
