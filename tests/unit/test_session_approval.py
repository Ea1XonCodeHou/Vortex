"""会话级工具审批缓存测试。"""

from vortex.domain.permissions import ApprovalDecision, ApprovalOutcome, ToolApprovalRequest
from vortex.domain.tools import ToolCall, ToolRisk
from vortex.permissions.session import SessionApprovalManager


def _request(
    tool_name: str = "read_file",
    *,
    run_id: str = "run-1",
    allowed_decisions: tuple[ApprovalDecision, ...] = (
        ApprovalDecision.ALLOW_ONCE,
        ApprovalDecision.ALLOW_SESSION,
        ApprovalDecision.DENY,
    ),
) -> ToolApprovalRequest:
    return ToolApprovalRequest(
        run_id=run_id,
        iteration=1,
        call=ToolCall(id="call-1", name=tool_name, arguments={"path": "README.md"}),
        risk=ToolRisk.READ,
        allowed_decisions=allowed_decisions,
    )


async def test_allow_session_is_cached_by_tool_name() -> None:
    manager = SessionApprovalManager()
    prompts: list[ToolApprovalRequest] = []

    async def prompt(request: ToolApprovalRequest) -> ApprovalDecision:
        prompts.append(request)
        return ApprovalDecision.ALLOW_SESSION

    manager.set_prompt(prompt)

    first = await manager.authorize(_request())
    second = await manager.authorize(_request())

    assert first.decision is ApprovalDecision.ALLOW_SESSION
    assert first.cached is False
    assert second.decision is ApprovalDecision.ALLOW_SESSION
    assert second.cached is True
    assert len(prompts) == 1


async def test_allow_once_and_deny_are_not_cached() -> None:
    manager = SessionApprovalManager()
    decisions = iter((ApprovalDecision.ALLOW_ONCE, ApprovalDecision.DENY))
    prompt_count = 0

    async def prompt(request: ToolApprovalRequest) -> ApprovalDecision:
        nonlocal prompt_count
        del request
        prompt_count += 1
        return next(decisions)

    manager.set_prompt(prompt)

    assert (await manager.authorize(_request())).decision is ApprovalDecision.ALLOW_ONCE
    assert (await manager.authorize(_request())).decision is ApprovalDecision.DENY
    assert prompt_count == 2


async def test_missing_client_prompt_fails_closed() -> None:
    outcome = await SessionApprovalManager().authorize(_request())

    assert outcome.decision is ApprovalDecision.DENY
    assert outcome.cached is False


async def test_allow_turn_is_cached_only_for_same_run_and_tool() -> None:
    manager = SessionApprovalManager()
    prompt_count = 0

    async def prompt(request: ToolApprovalRequest) -> ApprovalDecision:
        nonlocal prompt_count
        del request
        prompt_count += 1
        return ApprovalDecision.ALLOW_TURN

    manager.set_prompt(prompt)
    decisions = (ApprovalDecision.ALLOW_TURN, ApprovalDecision.DENY)

    first = await manager.authorize(_request("apply_patch", allowed_decisions=decisions))
    second = await manager.authorize(_request("apply_patch", allowed_decisions=decisions))
    third = await manager.authorize(
        _request("apply_patch", run_id="run-2", allowed_decisions=decisions)
    )

    assert first.cached is False
    assert second == ApprovalOutcome(ApprovalDecision.ALLOW_TURN, cached=True)
    assert third.cached is False
    assert prompt_count == 2


async def test_prompt_decision_outside_allowed_set_fails_closed() -> None:
    manager = SessionApprovalManager()

    async def prompt(request: ToolApprovalRequest) -> ApprovalDecision:
        del request
        return ApprovalDecision.ALLOW_SESSION

    manager.set_prompt(prompt)
    outcome = await manager.authorize(
        _request(
            "apply_patch",
            allowed_decisions=(ApprovalDecision.ALLOW_TURN, ApprovalDecision.DENY),
        )
    )

    assert outcome.decision is ApprovalDecision.DENY
