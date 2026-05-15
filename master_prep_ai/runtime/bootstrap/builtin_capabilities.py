"""Built-in capability class paths."""

BUILTIN_CAPABILITY_CLASSES: dict[str, str] = {
    "chat": "master_prep_ai.capabilities.chat:ChatCapability",
    "deep_solve": "master_prep_ai.capabilities.deep_solve:DeepSolveCapability",
    "deep_question": "master_prep_ai.capabilities.deep_question:DeepQuestionCapability",
    "deep_research": "master_prep_ai.capabilities.deep_research:DeepResearchCapability",
    "math_animator": "master_prep_ai.capabilities.math_animator:MathAnimatorCapability",
    "visualize": "master_prep_ai.capabilities.visualize:VisualizeCapability",
}
