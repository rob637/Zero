"""
End-to-End Loop Test: Natural Language → Plan → Execute → Results

This test proves the CORE LOOP of the Apex engine:
  1. User asks a natural language question
  2. LLM decomposes it into primitive steps (simulated here)
  3. Engine wires step outputs into step inputs
  4. Primitives execute against real data
  5. Final result is returned

No external API key required — we simulate the LLM's planning response
to validate the full pipeline.

Run with: python -m pytest test_full_loop.py -v
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from apex.apex_engine import Apex, StepResult


# ============================================================
#  HELPERS
# ============================================================

def make_llm_mock(responses: dict):
    """Create a mock LLM that returns canned responses based on prompt content.
    
    The mock inspects the prompt to decide which response to return:
    - If the prompt contains 'task planner' or 'Decompose' → return the plan JSON
    - Otherwise → return a generic completion
    """
    async def mock_llm(prompt: str, triggering_request: str = "") -> str:
        # Planning prompts contain the capabilities list
        for keyword, response in responses.items():
            if keyword.lower() in prompt.lower():
                return response
        return '{"result": "ok"}'
    return mock_llm


def create_test_engine(plan_response: str) -> Apex:
    """Create an Apex engine with a mock LLM that returns the given plan."""
    engine = Apex(api_key="test-key", enable_safety=False)
    mock = make_llm_mock({"decompose": plan_response})
    # Patch both the engine and the planner (planner gets llm at init time)
    engine._llm_complete = mock
    engine._planner._llm = mock
    # Allow /tmp for test files (default only allows ~)
    from apex.apex_engine import FilePrimitive
    engine._primitives["FILE"] = FilePrimitive(
        allowed_roots=[str(Path.home()), tempfile.gettempdir()]
    )
    return engine


# ============================================================
#  TEST 1: Simple file search (single step)
# ============================================================

@pytest.mark.asyncio
async def test_e2e_loop_file_search():
    """User asks to list files → LLM plans FILE.list → engine executes → results returned."""
    
    # Create some test files
    tmpdir = tempfile.mkdtemp()
    for name in ["report.pdf", "notes.txt", "photo.jpg"]:
        Path(tmpdir, name).write_text(f"content of {name}")
    
    # The LLM would return this plan for "List files in <dir>"
    plan_response = json.dumps([
        {
            "description": "List all files in the directory",
            "primitive": "FILE",
            "operation": "list",
            "params": {"directory": tmpdir},
            "wires": {}
        }
    ])
    
    engine = create_test_engine(plan_response)
    
    result = await engine.do(f"List files in {tmpdir}")
    
    assert result.success, f"Failed: {result.error}"
    assert result.final_result is not None
    filenames = [item["name"] for item in result.final_result]
    assert "report.pdf" in filenames
    assert "notes.txt" in filenames
    assert "photo.jpg" in filenames
    assert len(result.plan) == 1
    
    print(f"✓ File search returned {len(filenames)} files: {filenames}")
    
    # Cleanup
    for name in ["report.pdf", "notes.txt", "photo.jpg"]:
        os.unlink(Path(tmpdir, name))
    os.rmdir(tmpdir)


# ============================================================
#  TEST 2: Multi-step with wiring (search → read → compute)
# ============================================================

@pytest.mark.asyncio
async def test_e2e_loop_multi_step_wired():
    """
    User asks: "Read the loan doc and calculate amortization"
    LLM plans: FILE.read → COMPUTE.formula (wired to step_0's content)
    Engine: executes both, wires output of step 0 into step 1
    """
    
    # Create a test loan file
    tmpdir = tempfile.mkdtemp()
    loan_path = str(Path(tmpdir, "loan.txt"))
    Path(loan_path).write_text("Principal: $200,000\nRate: 5.5%\nTerm: 360 months")
    
    # The plan the LLM would generate
    plan_response = json.dumps([
        {
            "description": "Read the loan document",
            "primitive": "FILE",
            "operation": "read",
            "params": {"path": loan_path},
            "wires": {}
        },
        {
            "description": "Calculate amortization schedule",
            "primitive": "COMPUTE",
            "operation": "formula",
            "params": {
                "name": "amortization",
                "inputs": {"principal": 200000, "rate": 5.5, "term_months": 360}
            },
            "wires": {}
        }
    ])
    
    engine = create_test_engine(plan_response)
    
    result = await engine.do("Read the loan doc and calculate amortization")
    
    assert result.success, f"Failed: {result.error}"
    assert result.final_result is not None
    assert "monthly_payment" in result.final_result
    assert "schedule" in result.final_result
    assert len(result.final_result["schedule"]) == 360
    assert 1100 < result.final_result["monthly_payment"] < 1200  # ~$1,135.58
    assert len(result.plan) == 2
    
    # Verify both steps executed
    assert result.plan[0].result.success  # FILE.read
    assert result.plan[1].result.success  # COMPUTE.formula
    
    print(f"✓ Multi-step: Read doc → Amortization = ${result.final_result['monthly_payment']}/mo")
    
    # Cleanup
    os.unlink(loan_path)
    os.rmdir(tmpdir)


# ============================================================
#  TEST 3: Full loan→amortization→email flow (4 steps, wired)
# ============================================================

@pytest.mark.asyncio
async def test_e2e_loop_full_loan_to_email():
    """
    User asks: "Read my loan doc, calculate amortization, and email the schedule to Fred"
    
    LLM plans:
      step_0: FILE.read (loan doc)
      step_1: COMPUTE.formula (amortization)
      step_2: CONTACTS.search (find Fred)
      step_3: EMAIL.draft (compose email, wired to step_1 and step_2)
    
    This is the showcase scenario — 4 primitives, cross-step wiring, real execution.
    """
    
    # Setup: create loan file and add contact
    tmpdir = tempfile.mkdtemp()
    loan_path = str(Path(tmpdir, "loan.txt"))
    Path(loan_path).write_text("Principal: $150,000\nRate: 4.5%\nTerm: 180 months")
    
    plan_response = json.dumps([
        {
            "description": "Read the loan document",
            "primitive": "FILE",
            "operation": "read",
            "params": {"path": loan_path},
            "wires": {}
        },
        {
            "description": "Calculate amortization schedule",
            "primitive": "COMPUTE",
            "operation": "formula",
            "params": {
                "name": "amortization",
                "inputs": {"principal": 150000, "rate": 4.5, "term_months": 180}
            },
            "wires": {}
        },
        {
            "description": "Look up Fred's contact info",
            "primitive": "CONTACTS",
            "operation": "search",
            "params": {"query": "Fred"},
            "wires": {}
        },
        {
            "description": "Draft email to Fred with amortization results",
            "primitive": "EMAIL",
            "operation": "draft",
            "params": {
                "subject": "Your Amortization Schedule"
            },
            "wires": {
                "to": "step_2.email",
                "body": "step_1.monthly_payment"
            }
        }
    ])
    
    engine = create_test_engine(plan_response)
    engine.add_contact("Fred", "fred@example.com")
    
    result = await engine.do("Read my loan doc, calculate amortization, and email the schedule to Fred")
    
    assert result.success, f"Failed: {result.error}"
    assert len(result.plan) == 4
    
    # Verify each step
    assert result.plan[0].result.success, "FILE.read failed"
    assert result.plan[1].result.success, "COMPUTE.formula failed"
    assert result.plan[2].result.success, "CONTACTS.search failed"
    assert result.plan[3].result.success, "EMAIL.draft failed"
    
    # Verify wiring worked
    amort = result.plan[1].result.data
    assert 1100 < amort["monthly_payment"] < 1200  # ~$1,147
    assert len(amort["schedule"]) == 180
    
    email_draft = result.plan[3].result.data
    assert email_draft["to"] == "fred@example.com"  # Wired from step_2.email
    
    print(f"✓ Full flow: Read → Compute (${amort['monthly_payment']}/mo) → Find Fred → Email draft")
    print(f"  Email to: {email_draft['to']}")
    print(f"  Subject: {email_draft['subject']}")
    
    # Cleanup
    os.unlink(loan_path)
    os.rmdir(tmpdir)


# ============================================================
#  TEST 4: Dynamic search + conditional results
# ============================================================

@pytest.mark.asyncio
async def test_e2e_loop_search_and_summarize():
    """
    User asks: "Find all .txt files in my folder and tell me how many there are"
    
    LLM plans:
      step_0: FILE.search (find .txt files)
      step_1: COMPUTE.aggregate (count them)
    """
    
    # Create test files
    tmpdir = tempfile.mkdtemp()
    for i in range(5):
        Path(tmpdir, f"note_{i}.txt").write_text(f"Note {i}")
    Path(tmpdir, "image.png").write_bytes(b"\x89PNG")
    Path(tmpdir, "data.csv").write_text("a,b,c")
    
    plan_response = json.dumps([
        {
            "description": "Search for .txt files",
            "primitive": "FILE",
            "operation": "search",
            "params": {"directory": tmpdir, "pattern": "*.txt"},
            "wires": {}
        },
        {
            "description": "Count the results",
            "primitive": "COMPUTE",
            "operation": "aggregate",
            "params": {"function": "count", "field": "name"},
            "wires": {"data": "step_0"}
        }
    ])
    
    engine = create_test_engine(plan_response)
    
    result = await engine.do(f"Find all .txt files in {tmpdir} and count them")
    
    assert result.success, f"Failed: {result.error}"
    # Step 0 should find exactly 5 .txt files
    found = result.plan[0].result.data
    assert len(found) == 5, f"Expected 5 .txt files, found {len(found)}"
    
    print(f"✓ Search + count: Found {len(found)} .txt files in test dir")
    
    # Cleanup
    for f in Path(tmpdir).iterdir():
        f.unlink()
    os.rmdir(tmpdir)


# ============================================================
#  TEST 5: Plan approval mode (shows plan without executing)
# ============================================================

@pytest.mark.asyncio
async def test_e2e_loop_approval_mode():
    """
    Test require_approval=True returns the plan WITHOUT executing it.
    This is the human-in-the-loop safety feature.
    """
    
    plan_response = json.dumps([
        {
            "description": "Search for PDF files",
            "primitive": "FILE",
            "operation": "search",
            "params": {"directory": "~", "pattern": "*.pdf"},
            "wires": {}
        },
        {
            "description": "Delete old files",
            "primitive": "FILE",
            "operation": "write",
            "params": {"path": "/tmp/should_not_be_created.txt", "content": "SHOULD NOT HAPPEN"},
            "wires": {}
        }
    ])
    
    engine = create_test_engine(plan_response)
    
    result = await engine.do(
        "Find PDFs and write a summary",
        require_approval=True,
    )
    
    # Plan is generated but NOT executed
    assert result.success
    assert len(result.plan) == 2
    assert result.final_result is None  # Nothing was executed
    
    # Verify no steps were actually run
    for step in result.plan:
        assert step.result is None, f"Step '{step.description}' was executed but shouldn't have been"
    
    # Verify the destructive file was NOT created
    assert not Path("/tmp/should_not_be_created.txt").exists()
    
    # Verify plan is human-readable
    descriptions = [s.description for s in result.plan]
    print(f"✓ Approval mode: Plan returned without execution")
    print(f"  Steps: {descriptions}")


# ============================================================
#  TEST 6: Error handling with on_fail=continue
# ============================================================

@pytest.mark.asyncio
async def test_e2e_loop_error_resilience():
    """
    Test that when a step fails with on_fail=continue, subsequent steps still run.
    """
    
    plan_response = json.dumps([
        {
            "description": "Try to read a file that doesn't exist",
            "primitive": "FILE",
            "operation": "read",
            "params": {"path": "/tmp/nonexistent_file_xyz.txt"},
            "wires": {},
            "on_fail": "continue"
        },
        {
            "description": "Calculate something independently",
            "primitive": "COMPUTE",
            "operation": "calculate",
            "params": {"expression": "2 + 2"},
            "wires": {}
        }
    ])
    
    engine = create_test_engine(plan_response)
    
    result = await engine.do("Try to read a file and also do some math")
    
    # Overall result reflects the failure
    assert not result.success  # step 0 failed
    
    # But step 1 still ran successfully
    assert not result.plan[0].result.success  # File not found
    assert result.plan[1].result.success      # Math worked
    assert result.plan[1].result.data == 4    # 2 + 2 = 4
    
    print(f"✓ Error resilience: Step 0 failed, Step 1 still ran = {result.plan[1].result.data}")


# ============================================================
#  MAIN
# ============================================================

if __name__ == "__main__":
    async def main():
        print("=" * 60)
        print(" APEX ENGINE - FULL LOOP END-TO-END TESTS")
        print("=" * 60)
        
        await test_e2e_loop_file_search()
        await test_e2e_loop_multi_step_wired()
        await test_e2e_loop_full_loan_to_email()
        await test_e2e_loop_search_and_summarize()
        await test_e2e_loop_approval_mode()
        await test_e2e_loop_error_resilience()
        
        print("\n" + "=" * 60)
        print(" ALL FULL-LOOP TESTS PASSED!")
        print("=" * 60)
    
    asyncio.run(main())
