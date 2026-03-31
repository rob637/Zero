"""
End-to-End Test: Loan Document → Amortization → Email

This test validates the complete flow:
1. Read a loan document
2. Extract loan terms (principal, rate, term)
3. Calculate amortization schedule
4. Create formatted output
5. Send to Fred

Run with: python -m pytest apex/test_e2e.py -v
Or directly: python apex/test_e2e.py
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path

# Allow running as standalone
import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from apex.apex_engine import (
    Apex,
    FilePrimitive,
    DocumentPrimitive,
    ComputePrimitive,
    EmailPrimitive,
    ContactsPrimitive,
    StepResult,
)


# ============================================================
#  TEST DATA
# ============================================================

SAMPLE_LOAN_DOC = """
LOAN AGREEMENT

Borrower: John Smith
Lender: First National Bank
Date: January 15, 2024

LOAN TERMS:

Principal Amount: $250,000.00
Annual Interest Rate: 6.5%
Loan Term: 30 years (360 months)
Monthly Payment Start Date: February 1, 2024

This agreement constitutes a binding contract between the borrower
and the lender for the mortgage loan specified above.

Signed,
John Smith (Borrower)
Jane Doe (Lender Representative)
"""


# ============================================================
#  UNIT TESTS FOR PRIMITIVES
# ============================================================

async def test_file_primitive():
    """Test FILE primitive operations."""
    print("\n=== Testing FILE Primitive ===")
    
    # Allow temp directory for testing
    prim = FilePrimitive(allowed_roots=[str(Path.home()), tempfile.gettempdir()])
    
    # Test list
    result = await prim.execute("list", {"directory": "~"})
    assert result.success, f"List failed: {result.error}"
    print(f"✓ list: Found {len(result.data)} items in ~")
    
    # Test search
    result = await prim.execute("search", {
        "directory": "~",
        "pattern": "*.py",
        "limit": 5,
    })
    assert result.success, f"Search failed: {result.error}"
    print(f"✓ search: Found {len(result.data)} .py files (limited to 5)")
    
    # Test write + read
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        test_path = f.name
    
    result = await prim.execute("write", {"path": test_path, "content": "Hello, Apex!"})
    assert result.success, f"Write failed: {result.error}"
    print(f"✓ write: Wrote to {test_path}")
    
    result = await prim.execute("read", {"path": test_path})
    assert result.success, f"Read failed: {result.error}"
    assert result.data == "Hello, Apex!", f"Content mismatch: {result.data}"
    print(f"✓ read: Content verified")
    
    # Test info
    result = await prim.execute("info", {"path": test_path})
    assert result.success, f"Info failed: {result.error}"
    assert result.data["size"] == 12
    print(f"✓ info: Size = {result.data['size']}, Modified = {result.data['modified']}")
    
    # Cleanup
    os.unlink(test_path)
    print("✓ All FILE tests passed")
    return True


async def test_document_primitive():
    """Test DOCUMENT primitive operations."""
    print("\n=== Testing DOCUMENT Primitive ===")
    
    prim = DocumentPrimitive()
    
    # Test parse (plain text)
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(SAMPLE_LOAN_DOC)
        test_path = f.name
    
    result = await prim.execute("parse", {"path": test_path})
    assert result.success, f"Parse failed: {result.error}"
    assert "Principal Amount" in result.data
    print(f"✓ parse: Extracted {len(result.data)} chars from text file")
    
    # Test create (CSV)
    result = await prim.execute("create", {
        "format": "csv",
        "data": [
            {"month": 1, "payment": 1580.17, "interest": 1354.17, "principal": 226.00},
            {"month": 2, "payment": 1580.17, "interest": 1352.94, "principal": 227.23},
        ],
    })
    assert result.success, f"Create CSV failed: {result.error}"
    assert "month,payment" in result.data["content"]
    print(f"✓ create(csv): Generated CSV with {len(result.data['content'])} chars")
    
    # Test create (markdown)
    result = await prim.execute("create", {
        "format": "markdown",
        "data": [
            {"month": 1, "payment": "$1,580.17", "balance": "$249,774.00"},
            {"month": 2, "payment": "$1,580.17", "balance": "$249,546.77"},
        ],
    })
    assert result.success, f"Create MD failed: {result.error}"
    assert "| month |" in result.data["content"]
    print(f"✓ create(markdown): Generated table")
    
    # Cleanup
    os.unlink(test_path)
    print("✓ All DOCUMENT tests passed")
    return True


async def test_compute_primitive():
    """Test COMPUTE primitive operations."""
    print("\n=== Testing COMPUTE Primitive ===")
    
    prim = ComputePrimitive()
    
    # Test amortization formula
    result = await prim.execute("formula", {
        "name": "amortization",
        "inputs": {
            "principal": 250000,
            "rate": 6.5,
            "term_months": 360,
        },
    })
    assert result.success, f"Amortization failed: {result.error}"
    assert 1580 <= result.data["monthly_payment"] <= 1581  # ~$1,580.17
    assert len(result.data["schedule"]) == 360
    print(f"✓ amortization: Monthly = ${result.data['monthly_payment']}, Total Interest = ${result.data['total_interest']}")
    
    # Verify schedule integrity
    schedule = result.data["schedule"]
    assert schedule[0]["month"] == 1
    assert schedule[-1]["month"] == 360
    assert schedule[-1]["balance"] < 1  # Should be ~0
    print(f"✓ schedule: 360 months, final balance = ${schedule[-1]['balance']}")
    
    # Test compound interest
    result = await prim.execute("formula", {
        "name": "compound_interest",
        "inputs": {"principal": 10000, "rate": 5, "years": 10},
    })
    assert result.success
    assert 16000 <= result.data["final_amount"] <= 17000  # ~$16,470
    print(f"✓ compound_interest: $10k at 5% for 10y = ${result.data['final_amount']}")
    
    # Test calculate
    result = await prim.execute("calculate", {
        "expression": "principal * (1 + rate)",
        "variables": {"principal": 1000, "rate": 0.05},
    })
    assert result.success
    assert result.data == 1050
    print(f"✓ calculate: 1000 * (1 + 0.05) = {result.data}")
    
    # Test aggregate
    result = await prim.execute("aggregate", {
        "data": [
            {"month": 1, "interest": 100},
            {"month": 2, "interest": 99},
            {"month": 3, "interest": 98},
        ],
        "function": "sum",
        "field": "interest",
    })
    assert result.success
    assert result.data == 297
    print(f"✓ aggregate(sum): Total interest = {result.data}")
    
    print("✓ All COMPUTE tests passed")
    return True


async def test_contacts_primitive():
    """Test CONTACTS primitive."""
    print("\n=== Testing CONTACTS Primitive ===")
    
    prim = ContactsPrimitive()
    
    # Add contacts
    prim.add_contact("Fred Johnson", "fred@example.com", "555-0100")
    prim.add_contact("Alice Smith", "alice@example.com")
    
    # Search
    result = await prim.execute("search", {"query": "fred"})
    assert result.success
    assert result.data["email"] == "fred@example.com"
    print(f"✓ search 'fred': Found {result.data['name']}")
    
    # List
    result = await prim.execute("list", {})
    assert result.success
    assert len(result.data) == 2
    print(f"✓ list: Found {len(result.data)} contacts")
    
    print("✓ All CONTACTS tests passed")
    return True


# ============================================================
#  INTEGRATION TEST
# ============================================================

async def test_loan_to_amortization_flow():
    """
    Test the complete flow WITHOUT LLM (direct primitive calls):
    1. Read loan document
    2. Extract terms (simulated - no LLM)
    3. Calculate amortization
    4. Create output document
    5. Prepare email
    """
    print("\n=== Testing Loan → Amortization Flow (No LLM) ===")
    
    # Create test loan document
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(SAMPLE_LOAN_DOC)
        loan_path = f.name
    print(f"Created test loan doc at {loan_path}")
    
    # Initialize primitives
    file_prim = FilePrimitive([tempfile.gettempdir()])
    doc_prim = DocumentPrimitive()
    compute_prim = ComputePrimitive()
    contacts_prim = ContactsPrimitive()
    email_prim = EmailPrimitive()
    
    # Add Fred as a contact
    contacts_prim.add_contact("Fred", "fred@example.com")
    
    # === Step 1: Read document ===
    result = await doc_prim.execute("parse", {"path": loan_path})
    assert result.success, f"Failed to parse: {result.error}"
    doc_content = result.data
    print(f"Step 1: Parsed document ({len(doc_content)} chars)")
    
    # === Step 2: Extract loan terms (simulated - would use LLM) ===
    # In production, this would be: doc_prim.execute("extract", {"content": doc_content, "schema": {...}})
    # For testing, we extract manually
    loan_terms = {
        "principal": 250000,
        "rate": 6.5,
        "term_months": 360,
    }
    print(f"Step 2: Extracted terms: {loan_terms}")
    
    # === Step 3: Calculate amortization ===
    result = await compute_prim.execute("formula", {
        "name": "amortization",
        "inputs": loan_terms,
    })
    assert result.success, f"Failed to calculate: {result.error}"
    amortization = result.data
    print(f"Step 3: Calculated amortization - Monthly payment: ${amortization['monthly_payment']}")
    
    # === Step 4: Create output document ===
    # First 12 months for summary
    summary_data = amortization["schedule"][:12]
    
    result = await doc_prim.execute("create", {
        "format": "markdown",
        "data": summary_data,
    })
    assert result.success
    schedule_md = result.data["content"]
    
    # Create full report
    report = f"""# Amortization Schedule

**Principal:** ${loan_terms['principal']:,}
**Interest Rate:** {loan_terms['rate']}%
**Term:** {loan_terms['term_months']} months

**Monthly Payment:** ${amortization['monthly_payment']:,.2f}
**Total Interest:** ${amortization['total_interest']:,.2f}
**Total Amount Paid:** ${amortization['total_paid']:,.2f}

## First 12 Months

{schedule_md}
"""
    
    # Save to file
    output_path = tempfile.mktemp(suffix=".md")
    result = await file_prim.execute("write", {"path": output_path, "content": report})
    assert result.success, f"Failed to write: {result.error}"
    print(f"Step 4: Created report at {output_path}")
    
    # === Step 5: Find Fred and prepare email ===
    result = await contacts_prim.execute("search", {"query": "fred"})
    assert result.success and result.data
    fred_email = result.data["email"]
    
    result = await email_prim.execute("draft", {
        "to": fred_email,
        "subject": "Amortization Schedule for $250,000 Loan",
        "body": f"""Hi Fred,

Here's the amortization schedule you requested.

Monthly Payment: ${amortization['monthly_payment']:,.2f}
Total Interest over 30 years: ${amortization['total_interest']:,.2f}

The detailed schedule is attached.

Best regards""",
        "attachments": [output_path],
    })
    assert result.success
    print(f"Step 5: Drafted email to {fred_email}")
    
    # === Verify Results ===
    print("\n=== RESULTS ===")
    print(f"Loan Amount: ${loan_terms['principal']:,}")
    print(f"Interest Rate: {loan_terms['rate']}%")
    print(f"Term: {loan_terms['term_months']} months")
    print(f"Monthly Payment: ${amortization['monthly_payment']:,.2f}")
    print(f"Total Interest: ${amortization['total_interest']:,.2f}")
    print(f"Email to: {fred_email}")
    print(f"Draft created: {result.data['draft']}")
    
    # Cleanup
    os.unlink(loan_path)
    os.unlink(output_path)
    
    print("\n✓ Complete flow test PASSED!")
    return True


# ============================================================
#  APEX ENGINE INTEGRATION TEST
# ============================================================

async def test_apex_engine():
    """Test the Apex engine with direct primitive calls."""
    print("\n=== Testing Apex Engine ===")
    
    apex = Apex()  # Will work even without API key for direct calls
    
    # Add test contact
    apex.add_contact("Fred", "fred@example.com")
    
    # Test direct primitive access
    compute = apex.get_primitive("COMPUTE")
    result = await compute.execute("formula", {
        "name": "amortization",
        "inputs": {"principal": 100000, "rate": 5.0, "term_months": 180},
    })
    assert result.success
    print(f"✓ Direct primitive access: $100k at 5%/15yr = ${result.data['monthly_payment']}/mo")
    
    # List capabilities
    caps = apex.list_capabilities()
    print(f"✓ Capabilities: {', '.join(caps.keys())}")
    
    total_ops = sum(len(ops) for ops in caps.values())
    print(f"✓ Total operations: {total_ops}")
    
    print("✓ Apex Engine tests passed")
    return True


# ============================================================
#  RUN ALL TESTS
# ============================================================

async def run_all_tests():
    """Run all tests."""
    print("=" * 60)
    print(" APEX ENGINE - END-TO-END TEST SUITE")
    print("=" * 60)
    
    results = {}
    
    # Unit tests
    results["FILE"] = await test_file_primitive()
    results["DOCUMENT"] = await test_document_primitive()
    results["COMPUTE"] = await test_compute_primitive()
    results["CONTACTS"] = await test_contacts_primitive()
    
    # Integration tests
    results["LOAN_FLOW"] = await test_loan_to_amortization_flow()
    results["APEX_ENGINE"] = await test_apex_engine()
    
    # Summary
    print("\n" + "=" * 60)
    print(" TEST SUMMARY")
    print("=" * 60)
    
    passed = sum(1 for v in results.values() if v)
    total = len(results)
    
    for name, result in results.items():
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"  {name}: {status}")
    
    print(f"\n  Total: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n  🎉 ALL TESTS PASSED!")
        return True
    else:
        print("\n  ❌ SOME TESTS FAILED")
        return False


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
