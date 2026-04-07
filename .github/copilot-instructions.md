# STOP. READ THIS FIRST.

## Core Principle: TRUST THE AI

The LLM is the intelligence. The engine is plumbing.

## DO NOT:
- Add code to work around AI mistakes
- Add complex rules to prompts when AI ignores simple rules
- Hard-code scenario mappings
- Create post-processors to "fix" AI output
- Add more examples when one doesn't work

## DO:
- Keep prompts simple and generic
- If AI picks wrong primitive → improve primitive description
- If AI ignores date → simplify the prompt, not add MORE rules
- Trust the AI to be intelligent

## When You Catch Yourself Adding a Workaround:
1. STOP
2. Ask: "Am I coding around the AI instead of trusting it?"
3. If yes, find a simpler approach

## The Planner Prompt Should Be:
- TODAY: {date}
- List of primitives
- 1-3 simple rules
- Maybe one example
- NOTHING ELSE
