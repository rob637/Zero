"""Primitive contract auditing utilities for quality gates."""

from __future__ import annotations

from typing import Any, Dict, List


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def audit_primitives(primitives: Dict[str, Any]) -> Dict[str, Any]:
    primitive_rows: List[Dict[str, Any]] = []

    total_primitives = 0
    total_operations = 0
    operations_with_schema = 0
    operations_with_description = 0
    complete_param_defs = 0
    total_param_defs = 0

    for prim_name, primitive in sorted(primitives.items()):
        total_primitives += 1

        operations = primitive.get_operations() or {}
        schema = primitive.get_param_schema() or {}
        available = primitive.get_available_operations() or operations
        connected_providers = []
        if hasattr(primitive, "get_connected_providers"):
            connected_providers = primitive.get_connected_providers() or []

        primitive_gaps: List[str] = []
        if not operations:
            primitive_gaps.append("no_operations_declared")

        for op_name, op_desc in operations.items():
            total_operations += 1

            if isinstance(op_desc, str) and op_desc.strip():
                operations_with_description += 1

            op_schema = schema.get(op_name)
            if isinstance(op_schema, dict):
                # Empty dict is a valid explicit contract for no-parameter operations.
                operations_with_schema += 1
                for _param_name, param_def in op_schema.items():
                    total_param_defs += 1
                    if isinstance(param_def, dict):
                        p_type = str(param_def.get("type", "")).strip()
                        p_desc = str(param_def.get("description", "")).strip()
                        has_required = "required" in param_def
                        if p_type and p_desc and has_required:
                            complete_param_defs += 1
            elif op_name in available:
                # Many primitives expose zero-arg operations without explicit schema entries.
                operations_with_schema += 1
            else:
                primitive_gaps.append(f"missing_schema:{op_name}")

            if op_name not in available:
                primitive_gaps.append(f"not_available:{op_name}")

        primitive_rows.append(
            {
                "primitive": prim_name,
                "operations": len(operations),
                "available_operations": len(available),
                "connected_providers": connected_providers,
                "gaps": sorted(set(primitive_gaps)),
            }
        )

    op_schema_coverage = _clamp01(
        (operations_with_schema / total_operations) if total_operations else 0.0
    )
    op_description_coverage = _clamp01(
        (operations_with_description / total_operations) if total_operations else 0.0
    )
    param_definition_quality = _clamp01(
        (complete_param_defs / total_param_defs) if total_param_defs else 1.0
    )

    # Weighted toward reliable machine-usable contracts.
    quality_0_1 = _clamp01(
        op_schema_coverage * 0.55
        + param_definition_quality * 0.30
        + op_description_coverage * 0.15
    )

    global_gaps: List[str] = []
    if op_schema_coverage < 0.98:
        global_gaps.append("schema_coverage_below_target")
    if param_definition_quality < 0.98:
        global_gaps.append("param_definition_quality_below_target")
    if op_description_coverage < 0.99:
        global_gaps.append("operation_description_coverage_below_target")

    return {
        "summary": {
            "total_primitives": total_primitives,
            "total_operations": total_operations,
            "operations_with_schema": operations_with_schema,
            "operations_with_description": operations_with_description,
            "total_param_defs": total_param_defs,
            "complete_param_defs": complete_param_defs,
            "schema_coverage": round(op_schema_coverage, 4),
            "description_coverage": round(op_description_coverage, 4),
            "param_definition_quality": round(param_definition_quality, 4),
            "score_0_1": round(quality_0_1, 4),
            "score_10": round(quality_0_1 * 10.0, 2),
            "gaps": global_gaps,
        },
        "primitives": primitive_rows,
    }
