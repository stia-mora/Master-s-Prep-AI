"""Prompt manager path resolution tests."""

from __future__ import annotations

from master_prep_ai.services.prompt import get_prompt_manager


def test_prompt_manager_loads_prompts_from_master_prep_ai_tree() -> None:
    manager = get_prompt_manager()
    manager.clear_cache()

    prompts = manager.load_prompts(
        module_name="question",
        agent_name="idea_agent",
        language="en",
    )

    assert "generate_ideas" in prompts
