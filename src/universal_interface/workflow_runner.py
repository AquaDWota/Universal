"""Execute workflows declared in config.yaml."""

from __future__ import annotations

import json
from universal_interface.action_engine import execute_actions_sequentially
from universal_interface.app_context import AppContext
from universal_interface.config import llm_inference_enabled
from universal_interface.llm import complete_text
from universal_interface.models import Action
from universal_interface.unified_search import universal_query


def _fmt_search(results) -> str:
    lines: list[str] = []
    for r in results:
        i = r.item
        ts = i.timestamp.isoformat() if i.timestamp else ""
        body = (i.content or "")[:400]
        suf = "…" if len(i.content or "") > 400 else ""
        lines.append(f"- [{i.source}/{i.type}] **{i.title}** — {body}{suf} ({ts})")
    return "\n".join(lines) if lines else "_No matching items._"


async def run_workflow(ctx: AppContext, name: str) -> str:
    wf = ctx.config.workflows.get(name)
    if wf is None:
        raise KeyError(f"Unknown workflow '{name}'. Add it under workflows: in config.yaml.")
    if not wf.enabled:
        raise RuntimeError(f"Workflow '{name}' is disabled.")

    segments: list[str] = []

    for step in wf.steps:
        if isinstance(step, str):
            res = await universal_query(
                ctx.registry,
                text=step,
                sources=["all"],
                types=["all"],
                limit=20,
            )
            segments.append(f"### Search: {step}\n{_fmt_search(res)}")
            continue

        if isinstance(step, dict):
            if step.get("search"):
                q = str(step["search"])
                res = await universal_query(
                    ctx.registry,
                    text=q,
                    sources=["all"],
                    types=["all"],
                    limit=int(step.get("limit") or 20),
                )
                segments.append(f"### Search: {q}\n{_fmt_search(res)}")
                continue

            conn = step.get("connector")
            act_id = step.get("action")
            if conn and act_id:
                action = Action(
                    connector=str(conn),
                    action_id=str(act_id),
                    params=dict(step.get("params") or {}),
                )
                executed = await execute_actions_sequentially(ctx.registry, [action])
                _, result = executed[0]
                payload = result.model_dump()
                segments.append(
                    f"### Action `{conn}.{act_id}`\n```json\n"
                    f"{json.dumps(payload, indent=2, default=str)[:6000]}\n```"
                )
                continue

        segments.append(f"### Skipped unsupported step\n```json\n{json.dumps(step, default=str)}\n```")

    body = "\n\n".join(segments) if segments else "_No workflow steps produced output._"

    prompt = wf.prompt
    if prompt and llm_inference_enabled(ctx.config.ai):
        sys = (
            "You are summarizing workflow output for the user. "
            "Be concise and actionable; cite connectors/sources when obvious."
        )
        try:
            return await complete_text(
                ctx.config.ai,
                system=sys,
                user=f"Workflow '{name}' collected:\n\n{body}\n\nInstruction:\n{prompt}",
            )
        except Exception:
            pass

    if prompt:
        body += f"\n\n_(LLM synthesis skipped — configure inference / API keys or disable prompt.)_"

    return body
