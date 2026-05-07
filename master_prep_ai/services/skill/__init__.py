"""Skill service: load user-authored SKILL.md files and inject them into the chat system prompt."""

from master_prep_ai.services.skill.service import SkillService, get_skill_service

__all__ = ["SkillService", "get_skill_service"]
