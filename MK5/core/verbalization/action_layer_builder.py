from __future__ import annotations

from dataclasses import dataclass

from core.entities.conclusion import CoreConclusion, DerivedActionLayer


@dataclass(slots=True)
class ActionLayerBuilder:
    def build(self, conclusion: CoreConclusion) -> DerivedActionLayer:
        relation_count = len(conclusion.key_relations)
        activated_count = len(conclusion.activated_concepts)
        conflict_count = len(conclusion.detected_conflicts)
        revision_count = len(conclusion.revision_decisions)
        intent = conclusion.inferred_intent
        metadata = conclusion.metadata if isinstance(conclusion.metadata, dict) else {}
        search_context = metadata.get('search_context', {}) if isinstance(metadata, dict) else {}
        search_attempted = bool(search_context.get('attempted'))
        search_required = bool(search_context.get('need_search'))
        search_result_count = int(search_context.get('result_count') or 0)
        missing_terms = list(search_context.get('missing_terms') or [])
        missing_aspects = list(search_context.get('missing_aspects') or [])
        grounded_terms = list(search_context.get('grounded_terms') or [])
        search_error = search_context.get('error')
        no_evidence_found = bool(search_context.get('no_evidence_found'))
        previous_tone_hint = ' '.join(str(metadata.get('previous_tone_hint') or '').split()).strip()
        topic_continuity = str(metadata.get('topic_continuity') or '')
        recent_memory_messages = list(metadata.get('recent_memory_messages') or [])
        recent_memory_count = int(metadata.get('recent_memory_count') or len(recent_memory_messages))

        response_mode = 'direct_answer_with_uncertainty'
        answer_goal = 'Answer only within the currently grounded range and do not fill gaps with unsupported guesses.'
        suggested_actions: list[str] = []
        do_not_claim = [
            'Do not present unverified details as confirmed facts.',
            'Do not quote debug or internal labels directly in the user-facing answer.',
            'Do not list hidden graph state unless the user explicitly asked for internal debugging.',
        ]
        tone_hint = previous_tone_hint or 'natural_concise_korean'

        if intent == 'structure_review' or conflict_count > 0 or revision_count > 0:
            response_mode = 'structured_explanation'
            answer_goal = 'Explain the structure carefully, and keep uncertain parts clearly bounded.'
            suggested_actions = [
                'State the main comparison axis first.',
                'Separate confirmed parts from uncertain parts.',
            ]
        elif intent == 'relation_synthesis_request' or relation_count >= 2 or activated_count >= 3:
            response_mode = 'structured_explanation'
            answer_goal = 'Summarize the directly relevant relations and reasons in a compact way.'
            suggested_actions = [
                'Lead with the main relation.',
                'Use one or two short sentences for the rationale when needed.',
            ]
        elif intent == 'memory_probe':
            response_mode = 'structured_explanation'
            if recent_memory_count > 0:
                answer_goal = 'State what is remembered from recent conversation history, and separate remembered details from anything still unknown.'
                suggested_actions = [
                    'Summarize the most recent user and assistant turns first.',
                    'Reuse remembered names, roles, and ongoing topics only when they appear in recent session memory.',
                    'Say clearly when a requested detail is not present in current session memory.',
                ]
            else:
                answer_goal = 'State memory limits plainly and do not pretend to remember missing details.'
                suggested_actions = [
                    'Say only what is currently remembered.',
                    'Say clearly when memory is insufficient.',
                ]
        elif intent == 'open_information_request':
            response_mode = 'direct_answer_with_uncertainty'
            answer_goal = 'If information is insufficient, state the boundary first and answer only within confirmed scope.'
            suggested_actions = [
                'Answer only within the available evidence.',
                'Prefer boundaries over speculation when details are missing.',
            ]

        if conclusion.detected_conflicts:
            do_not_claim.append('Do not say there are no active conflicts when conflicts were detected.')
        if not conclusion.activated_concepts:
            do_not_claim.append('Do not imply the system remembers specific content when no activated concepts support it.')
        if search_error:
            do_not_claim.append('Do not state facts that were not confirmed after a search failure.')
            suggested_actions.append('Say clearly that some details remain unknown because search confirmation failed.')
        if search_required and search_attempted and search_result_count == 0 and not search_error:
            response_mode = 'structured_explanation'
            answer_goal = 'State first that search was needed but no confirmable evidence was found, and do not replace missing evidence with guesses.'
            do_not_claim.append('Do not present structural differences or performance differences as confirmed when no supporting evidence was found.')
            suggested_actions.append('Say clearly that confirmable external evidence was not found.')
        if missing_terms:
            joined = ', '.join(missing_terms)
            do_not_claim.append(f'Do not present these entities as confirmed without evidence: {joined}')
            suggested_actions.append('Separate grounded entities from still-unconfirmed entities.')
        if missing_aspects:
            joined = ', '.join(missing_aspects)
            do_not_claim.append(f'Do not present these aspects as confirmed without evidence: {joined}')
            suggested_actions.append('Do not infer unconfirmed aspects; mark them as unresolved.')
        if grounded_terms and missing_terms:
            answer_goal = 'Summarize grounded entities first, then mark the unresolved entities without turning them into facts.'
        if no_evidence_found and not search_error:
            do_not_claim.append('Do not imply that missing evidence was actually confirmed.')
        if topic_continuity == 'continued_topic':
            suggested_actions.append('Treat this as a continuation of the same topic and keep continuity with the previous turn.')
        elif topic_continuity == 'related_topic':
            suggested_actions.append('Preserve the bridge from the previous topic, but make the shifted focus explicit.')

        return DerivedActionLayer(
            response_mode=response_mode,
            answer_goal=answer_goal,
            suggested_actions=suggested_actions,
            do_not_claim=do_not_claim,
            tone_hint=tone_hint,
            metadata={
                'activated_concept_count': activated_count,
                'key_relation_count': relation_count,
                'conflict_count': conflict_count,
                'intent_basis': 'graph_state_only',
                'search_attempted': search_attempted,
                'search_required': search_required,
                'search_result_count': search_result_count,
                'no_evidence_found': no_evidence_found,
                'grounded_term_count': len(grounded_terms),
                'missing_term_count': len(missing_terms),
                'missing_aspect_count': len(missing_aspects),
                'topic_continuity': topic_continuity,
                'previous_tone_hint': previous_tone_hint,
                'recent_memory_count': recent_memory_count,
            },
        )
