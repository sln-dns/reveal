# Runtime Event Logging

`PairFlowApiService` and `PairScenarioRuntimeService` now emit structured runtime events through `RuntimeEventLogger` in [src/idea_check_backend/observability/runtime_events.py](/var/folders/42/jpgf43_12bzf43rnsrfg2r800000gn/T/vibe-kanban/worktrees/1155-runtime-event-lo/Idea_check/src/idea_check_backend/observability/runtime_events.py).

## Event format

Every runtime event is logged as structured JSON with these top-level fields:

- `event_type`: constant `runtime_event`
- `event_name`: stable domain event name
- `timestamp`: ISO-8601 UTC timestamp
- `session_id`: always present when the event belongs to a pair session
- `scenario_run_id`: present after runtime start
- `scene_id`: present for scene-level events
- `participant_id`: present for participant-specific events
- `participant_slot`: present when the slot is known
- `metadata`: event-specific structured payload

## Event names

- `session_created`: pair session container created
- `participant_joined`: participant attached to a session
- `scenario_run_started`: runtime run created and initialized
- `scene_activated`: scene becomes active
- `question_delivered`: participant-facing question created/delivered
- `answer_submitted`: participant answer persisted for the active scene
- `waiting_for_second_answer`: one answer exists, reveal is blocked on the partner
- `answers_revealed`: both answers are available and reveal became possible
- `scene_completed`: active scene finished and was marked completed
- `branch_selected`: runtime picked the next scene or ended the scenario
- `run_completed`: scenario run completed
- `runtime_error`: runtime flow raised an exception during `start_run` or `submit_answer`

## Metadata conventions

Metadata is intentionally event-specific, but the current flow already logs:

- counts such as `participant_count`, `answers_submitted_count`, `expected_answers_count`
- timing such as `time_since_scene_activation_seconds` and `time_to_second_answer_seconds`
- transition details such as `state_before`, `state_after`, `run_state_before`, `run_state_after`
- progression details such as `selected_next_scene_id` and `branch_reason`
- failure details such as `error_type`, `error_message`, and `operation`

## Intended usage

- Technical debugging: identify where a run stopped, whether reveal happened, and which transition failed.
- Product analytics: understand which scenes are activated, where users stall, and how often progression reaches later scenes.
- Incident triage: inspect `runtime_error` together with the last emitted scene or answer events.
