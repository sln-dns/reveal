from idea_check_backend.shared_types.scenario import SceneGenerationPayload


class ScenePromptBuilder:
    def build(self, payload: SceneGenerationPayload) -> str:
        allowed_question_count = min(3, payload.question_count_target)
        title_line = f"Title: {payload.scene_title}" if payload.scene_title else "Title: n/a"
        previous_answers = payload.previous_answers_summary or "No previous answers yet."
        branching_context = payload.branching_context or "No branching context yet."
        principles = ", ".join(payload.experience_principles)
        ladder = ", ".join(payload.ladder_stages)
        allowed_families = ", ".join(payload.allowed_question_families)
        forbidden_families = ", ".join(payload.forbidden_question_families)
        templates = "\n".join(f"- {template}" for template in payload.question_templates)

        return (
            "You generate short scene content for a two-player dating scenario.\n"
            "Return valid JSON only with keys: intro_text, questions, transition_text.\n"
            f"Questions array must contain 1-{allowed_question_count} short questions.\n"
            "Keep the tone warm, playful, and concise.\n"
            "Do not add markdown, explanations, or extra keys.\n\n"
            f"Scene ID: {payload.scene_id}\n"
            f"Scene type: {payload.scene_type}\n"
            f"{title_line}\n"
            f"Product goal: {payload.product_goal}\n"
            f"Selected world: {payload.selected_world}\n"
            f"Selected tone: {payload.selected_tone}\n"
            f"Experience principles: {principles}\n"
            f"Scene purpose: {payload.scene_purpose}\n"
            f"Psychological goal: {payload.psychological_goal}\n"
            f"Ladder stages: {ladder}\n"
            f"Allowed question families: {allowed_families}\n"
            f"Forbidden question families: {forbidden_families}\n"
            f"Transition goal: {payload.transition_goal}\n"
            f"Max answer length: {payload.max_answer_length_chars} characters\n"
            f"Previous answers summary: {previous_answers}\n"
            f"Branching context: {branching_context}\n"
            "Question inspiration templates:\n"
            f"{templates}\n"
        )
