"""
Rule Validator — structural and parameter validation for user-defined
detection rules, following the same ValidationResult pattern as
services/validation/contracts.py.
"""
import logging
from typing import Any, Dict

from services.detection.rule_engine import PrimitiveRegistry
from services.validation.contracts import ValidationResult

logger = logging.getLogger(__name__)

_VALID_COMBINATORS = {"AND", "OR"}
_VALID_OPERATORS = {">", ">=", "<", "<=", "=="}
_VALID_AGGS = {"SUM", "COUNT", "AVG", "MAX", "MIN"}
_VALID_GROUP_BY = {"source_account", "dest_account"}
_VALID_DIRECTIONS = {"fan_out", "fan_in"}

# Hard ceilings on params that drive expensive graph traversals, beyond the
# per-primitive ceilings in PrimitiveRegistry.CEILINGS — a blanket backstop.
_GLOBAL_CEILINGS = {"window_days": 365, "max_cycles": 5000, "max_length": 20}


class RuleValidator:
    """Validates a rule's structure and primitive params before it's saved."""

    def validate(self, rule_json: Dict[str, Any]) -> ValidationResult:
        result = ValidationResult(passed=True)

        if not isinstance(rule_json, dict):
            result.add_violation("structure", "rule_json must be an object")
            return result

        combinator = str(rule_json.get("combinator", "AND")).upper()
        if combinator not in _VALID_COMBINATORS:
            result.add_violation("combinator", f"'{combinator}' must be one of {_VALID_COMBINATORS}")

        conditions = rule_json.get("conditions")
        if not isinstance(conditions, list) or len(conditions) == 0:
            result.add_violation("conditions", "a rule must have at least one condition")
            return result

        for i, cond in enumerate(conditions):
            self._validate_condition(cond, i, result)

        return result

    def _validate_condition(self, cond: Dict[str, Any], index: int, result: ValidationResult):
        if not isinstance(cond, dict):
            result.add_violation(f"conditions[{index}]", "each condition must be an object")
            return

        primitive = cond.get("primitive")
        if primitive not in PrimitiveRegistry.SCHEMAS:
            result.add_violation(
                f"conditions[{index}].primitive",
                f"'{primitive}' is not a known primitive — choose from {sorted(PrimitiveRegistry.SCHEMAS)}",
            )
            return

        schema = PrimitiveRegistry.SCHEMAS[primitive]
        params = cond.get("params", {})
        if not isinstance(params, dict):
            result.add_violation(f"conditions[{index}].params", "params must be an object")
            return

        for name, type_spec in schema.items():
            if name not in params:
                continue  # defaults fill missing params at evaluation time
            self._validate_param(primitive, name, params[name], type_spec, index, result)

        ceilings = {**_GLOBAL_CEILINGS, **PrimitiveRegistry.CEILINGS.get(primitive, {})}
        for name, ceiling in ceilings.items():
            if name in params:
                try:
                    if float(params[name]) > ceiling:
                        result.add_violation(
                            f"conditions[{index}].params.{name}",
                            f"{params[name]} exceeds the maximum allowed ({ceiling}) for performance/safety",
                        )
                except (TypeError, ValueError):
                    pass

        unknown = set(params) - set(schema)
        if unknown:
            result.add_violation(
                f"conditions[{index}].params", f"unknown params for '{primitive}': {sorted(unknown)}",
                severity="WARNING",
            )

    def _validate_param(self, primitive: str, name: str, value: Any, type_spec: str,
                        index: int, result: ValidationResult):
        path = f"conditions[{index}].params.{name}"

        if type_spec == "int":
            if not isinstance(value, (int, float)) or isinstance(value, bool) or int(value) != value:
                result.add_violation(path, f"'{name}' must be an integer, got {value!r}")
            elif value <= 0:
                result.add_violation(path, f"'{name}' must be positive, got {value}")

        elif type_spec == "float":
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                result.add_violation(path, f"'{name}' must be a number, got {value!r}")

        elif type_spec == "str":
            if not isinstance(value, str) or not value:
                result.add_violation(path, f"'{name}' must be a non-empty string")

        elif type_spec.startswith("enum:"):
            allowed = set(type_spec.split(":", 1)[1].split(","))
            if str(value) not in allowed:
                result.add_violation(path, f"'{value}' must be one of {sorted(allowed)}")
