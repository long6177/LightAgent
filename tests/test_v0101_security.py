import pytest

from LightAgent import (
    BaseCapabilityProvider,
    CapabilitySpec,
    LightAgent,
    SafeExpressionError,
    evaluate_safe_expression,
)


def make_agent(**kwargs):
    return LightAgent(model="security-test-model", api_key="test-key", **kwargs)


def test_safe_expression_evaluates_data_only_operations():
    assert evaluate_safe_expression("45 * 9827") == 442215
    assert evaluate_safe_expression("[1, 2, 3]") == [1, 2, 3]
    assert evaluate_safe_expression("3 < 4 and 8 != 9") is True


@pytest.mark.parametrize("expression", [
    "__import__('os')",
    "open('secret.txt')",
    "(1).__class__",
    "[1][0]",
    "{[1]: 2}",
    "{x for x in range(3)}",
    "lambda: 1",
])
def test_safe_expression_rejects_execution_and_runtime_access(expression):
    with pytest.raises(SafeExpressionError):
        evaluate_safe_expression(expression)


def test_safe_expression_rejects_resource_exhaustion_inputs():
    expression = "[0] * 65"
    with pytest.raises(SafeExpressionError):
        evaluate_safe_expression(expression)


def test_arbitrary_python_tools_are_not_registered_by_default():
    agent = make_agent()
    names = set(agent.tool_registry.function_mappings)

    assert "safe_expression" in names
    assert "execute_python_code" not in names
    assert "execute_python_file" not in names
    assert "execute_python_code_stream" not in names


def test_explicit_arbitrary_python_opt_in_still_requires_sandbox():
    agent = make_agent(enable_unsafe_python=True)
    agent.runtime.open_session()

    assert "execute_python_code" in agent.tool_registry.function_mappings
    _, error = agent._prepare_tool_call("execute_python_code", {"code": "1 + 1"})

    assert error is not None
    assert "LA-SANDBOX" in error
    assert "SandboxProvider" in error


def test_explicit_sandbox_provider_opens_the_policy_gate():
    class TestSandboxProvider(BaseCapabilityProvider):
        name = "sandbox"

        def __init__(self):
            super().__init__([CapabilitySpec("sandbox.execute", execute=True)])

    agent = make_agent(
        enable_unsafe_python=True,
        capability_registry=None,
    )
    agent.runtime.open_session()
    agent.capability_registry.register(TestSandboxProvider())

    _, error = agent._prepare_tool_call("execute_python_code", {"code": "1 + 1"})

    assert error is None
