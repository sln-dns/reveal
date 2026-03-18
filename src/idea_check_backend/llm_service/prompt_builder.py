from idea_check_backend.shared_types.scenario import SceneGenerationPayload


class ScenePromptBuilder:
    def build(self, payload: SceneGenerationPayload) -> str:
        allowed_question_count = min(3, payload.question_count_target)
        title_line = (
            f"Название сцены: {payload.scene_title}" if payload.scene_title else "Название сцены: n/a"
        )
        previous_answers = payload.previous_answers_summary or "Предыдущих ответов пока нет."
        branching_context = payload.branching_context or "Контекст ветвления пока не задан."
        principles = ", ".join(payload.experience_principles)
        ladder = ", ".join(payload.ladder_stages)
        allowed_families = ", ".join(payload.allowed_question_families)
        forbidden_families = ", ".join(payload.forbidden_question_families)
        allowed_formats = ", ".join(payload.allowed_answer_formats)
        generation_rules = "\n".join(f"- {rule}" for rule in payload.question_generation_rules)
        templates = "\n".join(f"- {template}" for template in payload.question_templates)

        return (
            "Ты создаёшь короткий пользовательский текст для сцены сценария знакомства на двух игроков.\n"
            "Отвечай только на русском языке.\n"
            "Не смешивай русский и английский без явной необходимости.\n"
            "Не используй англоязычные labels, headings или служебные подписи в пользовательском тексте.\n"
            "Тон должен быть живым, тёплым, лёгким и естественным, без сухого переводного звучания.\n"
            "Верни только валидный JSON с ключами: intro_text, questions, transition_text.\n"
            f"В массиве questions должно быть от 1 до {allowed_question_count} коротких вопросов.\n"
            "Все значения внутри JSON должны быть написаны по-русски.\n"
            "Не добавляй markdown, объяснения, комментарии и лишние ключи.\n\n"
            f"Scene ID: {payload.scene_id}\n"
            f"Scene type: {payload.scene_type}\n"
            f"{title_line}\n"
            f"Продуктовая цель: {payload.product_goal}\n"
            f"Выбранный мир: {payload.selected_world}\n"
            f"Выбранный тон: {payload.selected_tone}\n"
            f"Принципы опыта: {principles}\n"
            f"Задача сцены: {payload.scene_purpose}\n"
            f"Психологическая цель: {payload.psychological_goal}\n"
            f"Ступени сценарной лестницы: {ladder}\n"
            f"Разрешённые семейства вопросов: {allowed_families}\n"
            f"Запрещённые семейства вопросов: {forbidden_families}\n"
            f"Цель перехода: {payload.transition_goal}\n"
            f"Максимальная длина ответа: {payload.max_answer_length_chars} символов\n"
            f"Основной формат ответа: {payload.default_answer_format}\n"
            f"Разрешённые форматы ответа: {allowed_formats}\n"
            f"Предпочтительный стиль вопроса: {payload.preferred_question_style}\n"
            "Каждый вопрос по умолчанию должен быть быстрым и лёгким: человек должен отвечать "
            "почти интуитивно, без длинной рефлексии.\n"
            f"Предпочтительное число вариантов внутри вопроса: от {payload.preferred_option_count_min} "
            f"до {payload.preferred_option_count_max}.\n"
            "Отдавай сильное предпочтение формату простого выбора из вариантов.\n"
            "Каждый вопрос формулируй так, чтобы на него можно было быстро ответить выбором "
            "из коротких вариантов прямо в тексте вопроса.\n"
            f"В каждом вопросе оставляй возможность ответа '{payload.custom_answer_label}' "
            "или другого короткого свободного ответа.\n"
            "Не делай открытые вопросы форматом по умолчанию.\n"
            "Избегай длинных историй, тяжёлой рефлексии, самоанализа и формулировок, "
            "которые заставляют долго думать.\n"
            "Не превращай сцену в тест, опросник или интервью.\n"
            "Держи эмоциональную живость, игровую атмосферу и естественность.\n"
            "Хороший паттерн вопроса: 'Что тебе ближе: вариант А, вариант Б, вариант В или свой вариант?'\n"
            "Если нужен свободный ответ, он должен оставаться коротким и необязательным.\n"
            "Правила генерации вопросов:\n"
            f"{generation_rules}\n"
            f"Краткая сводка прошлых ответов: {previous_answers}\n"
            f"Контекст ветвления: {branching_context}\n"
            "Шаблоны-вдохновения для вопросов:\n"
            f"{templates}\n"
        )
