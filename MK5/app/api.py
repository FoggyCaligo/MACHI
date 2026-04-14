from __future__ import annotations

from flask import Flask, jsonify, request, send_from_directory

from app.chat_pipeline import ChatPipeline, ChatPipelineRequest, DEFAULT_MODEL_NAME

REQUEST_TIMEOUT_MS = 300000


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
        return jsonify(
            {
                'default_model': DEFAULT_MODEL_NAME,
                'models': [],
                'ollama_available': False,
                'error': None,
            }
        )

    @app.post('/chat')
    def chat():
        message = (request.form.get('message') or '').strip()
        if not message:
            return jsonify({'detail': 'message is required'}), 400

        session_id = (request.form.get('session_id') or 'default').strip() or 'default'
        model_name = (request.form.get('model') or DEFAULT_MODEL_NAME).strip() or DEFAULT_MODEL_NAME
        turn_index = pipeline.next_turn_index(session_id)

        file = request.files.get('file')
        attached_files = []
        if file and file.filename:
            attached_files.append({'name': file.filename, 'size': getattr(file, 'content_length', None)})

        response = pipeline.process(
            request=ChatPipelineRequest(
                session_id=session_id,
                message=message,
                turn_index=turn_index,
                attached_files=attached_files,
                model_name=model_name,
            )
        )
        return jsonify(response)
