import os
from flask import Flask, jsonify
from server.routes.knowledge_routes import knowledge_bp
from server.routes.pr_routes import pr_bp


def create_app() -> Flask:
    app = Flask(__name__)

    @app.get("/health")
    def health() -> tuple:
        return jsonify({"ok": True}), 200

    app.register_blueprint(knowledge_bp)
    app.register_blueprint(pr_bp)
    return app


if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", "5057"))
    app.run(host="0.0.0.0", port=port, debug=True)


