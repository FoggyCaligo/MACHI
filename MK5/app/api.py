from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from app.chat_pipeline import ChatPipeline, ChatPipelineRequest, UserFacingChatError
from app.model_discovery import DEFAULT_MODEL_NAME, discover_model_catalog
from config import REQUEST_TIMEOUT_MS

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def register_routes(app: Flask) -> None:
    pipeline = ChatPipeline()

    @app.get('/')
    def index():
        return send_from_directory(app.static_folder, 'chat.html')

    @app.get('/ui-config')
    def ui_config():
        return jsonify({'request_timeout_ms': REQUEST_TIMEOUT_MS})

    @app.get('/projects')
    def projects():
        return jsonify({'projects': []})

    @app.get('/models')
    def models():
        catalog = discover_model_catalog(DEFAULT_MODEL_NAME)
        return jsonify(
            {
                'default_model': catalog.default_model,
                'models': catalog.models,
                'ollama_available': catalog.ollama_available,
                'error': catalog.error,
            }
        )

    @app.post('/chat')
    def chat():
        print('[api] /chat start')
        message = (request.form.get('message') or '').strip()
        if not message:
            return jsonify({'detail': 'message is required'}), 400

        session_id = (request.form.get('session_id') or 'default').strip() or 'default'
        selected_model = (request.form.get('model') or '').strip() or DEFAULT_MODEL_NAME
        file = request.files.get('file')
        attached_files: list[dict[str, object]] = []
        if file and file.filename:
            attached_files.append(
                {
                    'name': file.filename,
                    'content_type': getattr(file, 'content_type', None),
                    'size': getattr(file, 'content_length', None),
                }
            )

        try:
            result = pipeline.process(
                ChatPipelineRequest(
                    session_id=session_id,
                    message=message,
                    turn_index=0,
                    attached_files=attached_files,
                    model_name=selected_model,
                )
            )
            print('[api] /chat fin ok')
            return jsonify(result)
        except UserFacingChatError as exc:
            print(f'[api] /chat fin user_error detail={exc}')
            return jsonify({'detail': str(exc)}), 400
        except RuntimeError as exc:
            print(f'[api] /chat fin runtime_error detail={exc}')
            return jsonify({'detail': str(exc)}), 500

    @app.post('/internal/revision-review')
    def internal_revision_review():
        body = request.get_json(silent=True) if request.is_json else {}
        raw_limit = (request.form.get('limit') or (body or {}).get('limit') or '100')
        raw_trigger = (request.form.get('trigger') or (body or {}).get('trigger') or 'system_internal')
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            return jsonify({'detail': 'limit must be integer'}), 400
        result = pipeline.run_internal_revision_review(
            limit=max(1, limit),
            trigger=' '.join(str(raw_trigger or '').split())[:80] or 'system_internal',
        )
        return jsonify(result)
