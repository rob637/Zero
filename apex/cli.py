"""
Apex CLI - Command line interface for testing

This is a simple CLI for development/testing.
The real UI will be the Tauri system tray app.
"""

import asyncio
import argparse
import os
import sys

# Add src to path for development
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from src.core import SkillRegistry, Orchestrator, MemoryEngine
from src.core.llm import create_client_from_env
from src.skills import FileOrganizerSkill


def print_plan(plan):
    """Pretty print an action plan."""
    print("\n" + "=" * 60)
    print(f"📋 {plan.summary}")
    print("=" * 60)
    print(f"\n💭 Reasoning: {plan.reasoning}\n")
    
    if plan.warnings:
        print("⚠️  Warnings:")
        for w in plan.warnings:
            print(f"   - {w}")
        print()
    
    if plan.actions:
        print(f"📝 Proposed Actions ({len(plan.actions)}):\n")
        for i, action in enumerate(plan.actions):
            icon = {
                "move": "📁",
                "delete": "🗑️",
                "create_folder": "📂",
                "rename": "✏️",
                "copy": "📋",
            }.get(action.action_type.value, "•")
            
            print(f"   [{i}] {icon} {action.action_type.value.upper()}")
            print(f"       Source: {action.source}")
            if action.destination:
                print(f"       Dest:   {action.destination}")
            print(f"       Reason: {action.reason}")
            print()
    else:
        print("   (No actions proposed)\n")
    
    print(f"📊 Stats: {plan.affected_files_count} files | {plan.space_freed_estimate} space")
    print("=" * 60)


async def interactive_mode():
    """Run Apex in interactive mode."""
    print("""
╔═══════════════════════════════════════════════════════════════╗
║                    APEX - Development CLI                     ║
║           Privacy-First Personal AI Operating Layer           ║
╚═══════════════════════════════════════════════════════════════╝
    """)
    
    # Check for API key
    if not create_client_from_env():
        print("⚠️  No LLM API key found!")
        print("   Set ANTHROPIC_API_KEY or OPENAI_API_KEY environment variable.")
        print()
    
    orchestrator = Orchestrator()
    
    print("Commands:")
    print("  - Type a request (e.g., 'clean up my downloads')")
    print("  - 'approve' or 'a' to approve all actions")
    print("  - 'approve 0 2 3' to approve specific actions")
    print("  - 'reject' or 'r' to reject the plan")
    print("  - 'skills' to list available skills")
    print("  - 'memory' to show remembered facts")
    print("  - 'quit' or 'q' to exit")
    print()
    
    current_task = None
    
    while True:
        try:
            user_input = input("\n🤖 Apex> ").strip()
            
            if not user_input:
                continue
            
            # Handle commands
            if user_input.lower() in ('quit', 'q', 'exit'):
                print("Goodbye! 👋")
                break
            
            if user_input.lower() == 'skills':
                skills = orchestrator.registry.list_skills()
                print("\n📚 Registered Skills:")
                for s in skills:
                    print(f"   - {s['name']} v{s['version']}: {s['description']}")
                continue
            
            if user_input.lower() == 'memory':
                from src.core.memory import memory
                facts = memory.recall_all()
                print(f"\n🧠 Memory ({len(facts)} facts):")
                for f in facts:
                    print(f"   [{f.category}] {f.content[:60]}...")
                continue
            
            if user_input.lower() in ('approve', 'a'):
                if current_task and current_task.plan:
                    print("\n⏳ Executing approved actions...")
                    result = await orchestrator.approve(current_task.id)
                    print(f"\n✅ Completed: {len(result.result.get('success', []))} succeeded")
                    if result.result.get('failed'):
                        print(f"❌ Failed: {len(result.result['failed'])}")
                    current_task = None
                else:
                    print("No plan to approve. Submit a request first.")
                continue
            
            if user_input.lower().startswith('approve '):
                if current_task and current_task.plan:
                    indices = [int(x) for x in user_input.split()[1:]]
                    print(f"\n⏳ Executing {len(indices)} approved actions...")
                    result = await orchestrator.approve(current_task.id, indices)
                    print(f"\n✅ Completed: {len(result.result.get('success', []))} succeeded")
                    current_task = None
                else:
                    print("No plan to approve.")
                continue
            
            if user_input.lower() in ('reject', 'r'):
                if current_task:
                    await orchestrator.reject(current_task.id)
                    print("❌ Plan rejected.")
                    current_task = None
                else:
                    print("No plan to reject.")
                continue
            
            # Submit as a request
            print("\n⏳ Analyzing request...")
            current_task = await orchestrator.submit(user_input)
            
            if current_task.plan:
                print_plan(current_task.plan)
                print("\n💡 Type 'approve' to execute, 'reject' to cancel, or make a new request.")
            else:
                print(f"❌ Error: {current_task.error}")
                current_task = None
                
        except KeyboardInterrupt:
            print("\n\nGoodbye! 👋")
            break
        except Exception as e:
            print(f"\n❌ Error: {e}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Apex CLI")
    parser.add_argument("--request", "-r", help="Single request to process")
    parser.add_argument("--auto-approve", action="store_true", help="Auto-approve (DANGEROUS)")
    args = parser.parse_args()
    
    if args.request:
        # Single request mode
        async def run_single():
            orchestrator = Orchestrator()
            task = await orchestrator.submit(args.request)
            if task.plan:
                print_plan(task.plan)
                if args.auto_approve:
                    print("\n⚠️  AUTO-APPROVING (--auto-approve flag)")
                    result = await orchestrator.approve(task.id)
                    print(f"Result: {result.result}")
        
        asyncio.run(run_single())
    else:
        # Interactive mode
        asyncio.run(interactive_mode())


if __name__ == "__main__":
    main()
