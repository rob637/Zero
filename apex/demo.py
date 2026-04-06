#!/usr/bin/env python
"""
Telic CLI - Interactive Demo

Usage:
    python apex/demo.py
    
Examples:
    > find all PDFs in ~/Documents
    > calculate amortization for $300k at 7% for 30 years
    > list files in ~/Downloads
"""

import asyncio
import json
import os
import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from apex.apex_engine import Apex


def format_result(result):
    """Format result for display."""
    if not result.success:
        return f"❌ Error: {result.error}"
    
    output = ["✅ Success\n"]
    
    # Show plan
    output.append("📋 Execution Plan:")
    for step in result.plan:
        status = "✓" if step.result and step.result.success else "✗"
        output.append(f"  {status} {step.description}")
    
    # Show final result
    output.append("\n📊 Result:")
    if result.final_result:
        if isinstance(result.final_result, dict):
            # Special formatting for amortization
            if "monthly_payment" in result.final_result:
                data = result.final_result
                output.append(f"  Monthly Payment: ${data['monthly_payment']:,.2f}")
                output.append(f"  Total Interest:  ${data['total_interest']:,.2f}")
                output.append(f"  Total Paid:      ${data['total_paid']:,.2f}")
                if "schedule" in data and len(data["schedule"]) > 0:
                    output.append(f"\n  First 6 months:")
                    output.append("  Month | Payment   | Principal | Interest  | Balance")
                    output.append("  " + "-" * 54)
                    for row in data["schedule"][:6]:
                        output.append(
                            f"  {row['month']:5} | ${row['payment']:8,.2f} | ${row['principal']:8,.2f} | "
                            f"${row['interest']:8,.2f} | ${row['balance']:,.2f}"
                        )
            else:
                output.append(f"  {json.dumps(result.final_result, indent=2)[:1000]}")
        elif isinstance(result.final_result, list):
            output.append(f"  Found {len(result.final_result)} items:")
            for item in result.final_result[:10]:
                if isinstance(item, dict):
                    name = item.get("name", item.get("path", str(item)))
                    output.append(f"    • {name}")
                else:
                    output.append(f"    • {item}")
            if len(result.final_result) > 10:
                output.append(f"    ... and {len(result.final_result) - 10} more")
        else:
            text = str(result.final_result)
            if len(text) > 500:
                text = text[:500] + "..."
            output.append(f"  {text}")
    
    return "\n".join(output)


async def demo_direct_operations():
    """Demo direct primitive operations (no LLM needed)."""
    print("\n" + "="*60)
    print(" TELIC DIRECT OPERATIONS DEMO")
    print(" (No LLM / API key required)")
    print("="*60)
    
    apex = Apex()
    
    # Demo 1: List files
    print("\n📁 Demo 1: List home directory")
    print("-" * 40)
    file_prim = apex.get_primitive("FILE")
    result = await file_prim.execute("list", {"directory": "~"})
    if result.success:
        print(f"Found {len(result.data)} items in ~")
        for item in result.data[:5]:
            prefix = "📁" if item["is_dir"] else "📄"
            print(f"  {prefix} {item['name']}")
        if len(result.data) > 5:
            print(f"  ... and {len(result.data) - 5} more")
    
    # Demo 2: Search for files
    print("\n🔍 Demo 2: Search for Python files")
    print("-" * 40)
    result = await file_prim.execute("search", {
        "directory": Path.home() / ".",
        "pattern": "*.py",
        "limit": 5,
        "recursive": False,
    })
    if result.success:
        print(f"Found {len(result.data)} .py files")
        for item in result.data:
            print(f"  📄 {item['name']} ({item['size']} bytes)")
    
    # Demo 3: Calculate amortization
    print("\n💰 Demo 3: Calculate Amortization")
    print("-" * 40)
    print("Loan: $250,000 at 6.5% for 30 years")
    compute = apex.get_primitive("COMPUTE")
    result = await compute.execute("formula", {
        "name": "amortization",
        "inputs": {"principal": 250000, "rate": 6.5, "term_months": 360}
    })
    if result.success:
        data = result.data
        print(f"\n  Monthly Payment: ${data['monthly_payment']:,.2f}")
        print(f"  Total Interest:  ${data['total_interest']:,.2f}")
        print(f"  Total Paid:      ${data['total_paid']:,.2f}")
        print("\n  First 3 months:")
        print("  Month | Payment   | Principal | Interest  | Balance")
        print("  " + "-" * 54)
        for row in data["schedule"][:3]:
            print(
                f"  {row['month']:5} | ${row['payment']:8,.2f} | ${row['principal']:8,.2f} | "
                f"${row['interest']:8,.2f} | ${row['balance']:,.2f}"
            )
    
    # Demo 4: Calculate compound interest
    print("\n📈 Demo 4: Compound Interest")
    print("-" * 40)
    print("$10,000 at 7% for 20 years")
    result = await compute.execute("formula", {
        "name": "compound_interest",
        "inputs": {"principal": 10000, "rate": 7, "years": 20}
    })
    if result.success:
        print(f"  Final Amount:    ${result.data['final_amount']:,.2f}")
        print(f"  Interest Earned: ${result.data['interest_earned']:,.2f}")
    
    # Demo 5: Create a document
    print("\n📝 Demo 5: Create Markdown Table")
    print("-" * 40)
    doc = apex.get_primitive("DOCUMENT")
    result = await doc.execute("create", {
        "format": "markdown",
        "data": [
            {"Name": "Alice", "Age": 30, "City": "NYC"},
            {"Name": "Bob", "Age": 25, "City": "LA"},
            {"Name": "Carol", "Age": 35, "City": "Chicago"},
        ],
    })
    if result.success:
        print(result.data["content"])
    
    print("\n" + "="*60)
    print(" AVAILABLE CAPABILITIES")
    print("="*60)
    for name, ops in apex.list_capabilities().items():
        print(f"\n{name}:")
        for op, desc in ops.items():
            print(f"  • {op}: {desc}")


async def interactive_mode():
    """Run interactive mode with LLM planning."""
    api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    model = "anthropic/claude-sonnet-4-20250514" if os.environ.get("ANTHROPIC_API_KEY") else "gpt-4o-mini"
    
    if not api_key:
        print("\n⚠️  No API key found. Running in demo mode.")
        print("   Set OPENAI_API_KEY or ANTHROPIC_API_KEY for full capabilities.\n")
        await demo_direct_operations()
        return
    
    print("""
╔═══════════════════════════════════════════════════════════════╗
║                     APEX — Interactive Demo                   ║
║          Ask anything. AI decomposes. You approve.            ║
╚═══════════════════════════════════════════════════════════════╝
""")
    print(f"  Model: {model}")
    print(f"  Safety: Human-in-the-loop (you approve before execution)")
    print()
    print("  Commands:")
    print("    help  — Show commands")
    print("    caps  — List all capabilities")
    print("    auto  — Toggle auto-approve mode (skip approval step)")
    print("    quit  — Exit")
    print()
    print("  Examples:")
    print('    "Find all PDF files in ~/Documents"')
    print('    "Calculate amortization for $300,000 at 7% for 30 years"')
    print('    "What Python files are in the current directory and how many?"')
    print('    "Read README.md and summarize it"')
    print()
    
    apex = Apex(api_key=api_key, model=model, enable_safety=False)
    apex.add_contact("Fred", "fred@example.com")
    apex.add_contact("Alice", "alice@company.com")
    apex.add_contact("Bob", "bob@startup.io")
    
    auto_approve = False
    
    while True:
        try:
            request = input("apex> ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nGoodbye!")
            break
        
        if not request:
            continue
        
        if request.lower() in ("quit", "exit", "q"):
            print("Goodbye!")
            break
        
        if request.lower() == "help":
            print("\n  Commands:")
            print("    help  — Show this help")
            print("    caps  — List all capabilities")
            print("    auto  — Toggle auto-approve mode")
            print("    quit  — Exit")
            print("\n  Or type any natural language request.\n")
            continue
        
        if request.lower() == "auto":
            auto_approve = not auto_approve
            mode = "ON (plans execute immediately)" if auto_approve else "OFF (you approve each plan)"
            print(f"  Auto-approve: {mode}\n")
            continue
        
        if request.lower() == "caps":
            for name, ops in apex.list_capabilities().items():
                print(f"\n  {name}:")
                for op, desc in ops.items():
                    print(f"    • {op}: {desc}")
            print()
            continue
        
        # ── Step 1: Plan ──────────────────────────────────────
        print("\n  ⏳ Planning...")
        try:
            result = await apex.do(request, require_approval=True)
        except Exception as e:
            print(f"  ❌ Planning failed: {e}\n")
            continue
        
        # ── Step 2: Show plan ─────────────────────────────────
        plan = result.plan
        print(f"\n  📋 Plan ({len(plan)} steps):")
        print("  " + "─" * 56)
        for step in plan:
            risk = _classify_risk_display(step.primitive, step.operation)
            risk_icon = {"low": "🟢", "medium": "🟡", "high": "🔴"}.get(risk, "⚪")
            print(f"  {risk_icon} [{step.id}] {step.primitive}.{step.operation}")
            print(f"       {step.description}")
            if step.params:
                params_short = json.dumps(step.params)
                if len(params_short) > 80:
                    params_short = params_short[:77] + "..."
                print(f"       params: {params_short}")
            if step.wires:
                print(f"       wires:  {json.dumps(step.wires)}")
        print("  " + "─" * 56)
        
        # ── Step 3: Approval ──────────────────────────────────
        if not auto_approve:
            try:
                choice = input("  Execute? [Y]es / [n]o / [a]uto-approve: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\n  Skipped.\n")
                continue
            
            if choice in ("a", "auto"):
                auto_approve = True
                print("  Auto-approve enabled for future requests.")
            elif choice in ("n", "no"):
                print("  ⏭️  Skipped.\n")
                continue
            elif choice not in ("", "y", "yes"):
                print("  ⏭️  Skipped.\n")
                continue
        
        # ── Step 4: Execute ───────────────────────────────────
        print("\n  ⚡ Executing...")
        try:
            result = await apex.do(request)
        except Exception as e:
            print(f"  ❌ Execution failed: {e}\n")
            continue
        
        # ── Step 5: Show results ──────────────────────────────
        print()
        for step in result.plan:
            if step.result and step.result.success:
                print(f"  ✓ [{step.id}] {step.description}")
            elif step.result:
                print(f"  ✗ [{step.id}] {step.description}")
                print(f"       Error: {step.result.error}")
            else:
                print(f"  ○ [{step.id}] {step.description} (not executed)")
        
        print()
        if result.success:
            print(format_result(result))
        else:
            print(f"  ❌ Failed: {result.error}")
        print()


def _classify_risk_display(primitive: str, operation: str) -> str:
    """Classify risk for display purposes."""
    high = {("EMAIL", "send"), ("FILE", "write"), ("SHELL", "run"), ("MESSAGE", "send")}
    medium = {("CALENDAR", "create"), ("CALENDAR", "delete"), ("TASK", "create"), 
              ("CONTACTS", "add"), ("NOTIFY", "alert")}
    key = (primitive.upper(), operation.lower())
    if key in high:
        return "high"
    elif key in medium:
        return "medium"
    return "low"


def main():
    """Main entry point."""
    if len(sys.argv) > 1 and sys.argv[1] == "--demo":
        asyncio.run(demo_direct_operations())
    else:
        asyncio.run(interactive_mode())


if __name__ == "__main__":
    main()
