from __future__ import annotations

from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

from app.chat_pipeline import ChatPipeline, ChatPipelineRequest
from storage.sqlite.unit_of_work import SqliteUnitOfWork

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / 'data' / 'memory.db'
SCHEMA_PATH = PROJECT_ROOT / 'storage' / 'schema.sql'
REQUEST_TIMEOUT_MS = 300000


def _uow_factory():
    return SqliteUnitOfWork(DB_PATH, schema_path=SCHEMA_PATH, initialize_schema=True)


def register_routes(app: Flask) -> None:
    pipeline = ChatPipeline(db_path=DB_PATH, schema_path=SCHEMA_PATH)

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
        return jsonify(
            {
                'default_model': 'mk5-graph-core',
                'models': [],
                'ollama_available': False,
                'error': None,
            }
        )

    @app.get('/debug/session/<session_id>')
    def debug_session(session_id: str):
        with _uow_factory() as uow:
            messages = list(uow.chat_messages.list_by_session(session_id, limit=50))
            events = list(uow.graph_events.list_recent(limit=50))
        return jsonify(
            {
                'session_id': session_id,
                'message_count': len(messages),
                'messages': [
                    {
                        'id': m.id,
                        'turn_index': m.turn_index,
                        'role': m.role,
                        'content': m.content,
                    }
                    for m in messages
                ],
                'recent_events': [
                    {
                        'id': e.id,
                        'event_type': e.event_type,
                        'message_id': e.message_id,
                        'trigger_node_id': e.trigger_node_id,
                        'trigger_edge_id': e.trigger_edge_id,
                        'note': e.note,
                    }
                    for e in events
                ],
            }
        )

    @app.post('/chat')
    def chat():
        message = (request.form.get('message') or '').strip()
        if not message:
            return jsonify({'detail': 'message is required'}), 400

        session_id = (request.form.get('session_id') or 'default').strip() or 'default'
        turn_index = pipeline.next_turn_index(session_id)
        file = request.files.get('file')
        attached_files = []
        if file and file.filename:
            attached_files.append({'name': file.filename, 'size': getattr(file, 'content_length', None)})

        response = pipeline.process(
            ChatPipelineRequest(
                session_id=session_id,
                message=message,
                turn_index=turn_index,
                attached_files=attached_files,
                model_name='mk5-graph-core',
            )
        )
        return jsonify(response)
