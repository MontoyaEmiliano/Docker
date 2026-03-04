import os
from time import sleep
from flask import Flask, jsonify, request
import psycopg2
import redis

app = Flask(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_HOST = os.getenv("REDIS_HOST", "redis")

def get_redis():
    return redis.Redis(host=REDIS_HOST, port=6379, decode_responses=True)

def get_db_conn():
    return psycopg2.connect(DATABASE_URL)

def wait_for_db(max_retries=20):
    for _ in range(max_retries):
        try:
            conn = get_db_conn()
            conn.close()
            return
        except Exception:
            sleep(1)
    raise RuntimeError("Database no respondió, está muerta!")

def init_db():
    conn = get_db_conn()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id    SERIAL PRIMARY KEY,
            name  VARCHAR(100) NOT NULL,
            email VARCHAR(255) NOT NULL UNIQUE
        );
    """)
    conn.commit()
    cur.close()
    conn.close()

@app.before_request
def count_visit():
    try:
        r = get_redis()
        r.incr("visits")
    except Exception:
        pass

@app.get("/")
def home():
    return jsonify({
        "message": "¡Hola desde Docker Compose!",
        "services": {
            "/health":       "Verifica la salud de la aplicación",
            "/visits":       "Número total de visitas (Redis)",
            "GET /users":    "Lista todos los usuarios",
            "POST /users":   "Crea un nuevo usuario {name, email}"
        }
    })

@app.get("/health")
def health():
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT NOW();")
        now = cur.fetchone()[0]
        cur.close()
        conn.close()
        r = get_redis()
        pong = r.ping()
        return jsonify({
            "status": "ok",
            "db_time": str(now),
            "redis_ping": pong
        })
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.get("/visits")
def visits():
    try:
        r = get_redis()
        count = r.get("visits") or 0
        return jsonify({"visits": int(count)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.get("/users")
def get_users():
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("SELECT id, name, email FROM users ORDER BY id;")
        rows = cur.fetchall()
        cur.close()
        conn.close()
        users = [{"id": r[0], "name": r[1], "email": r[2]} for r in rows]
        return jsonify(users)
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.post("/users")
def create_user():
    data = request.get_json(silent=True) or {}
    name = data.get("name", "").strip()
    email = data.get("email", "").strip()
    if not name or not email:
        return jsonify({"status": "error", "message": "name y email son requeridos"}), 400
    try:
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (name, email) VALUES (%s, %s) RETURNING id;",
            (name, email)
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
        return jsonify({"id": new_id, "name": name, "email": email}), 201
    except psycopg2.errors.UniqueViolation:
        return jsonify({"status": "error", "message": "El email ya existe"}), 409
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    wait_for_db()
    init_db()
    app.run(host="0.0.0.0", port=8000)
