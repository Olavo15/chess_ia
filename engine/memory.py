import os
import json
import sqlite3
from collections import Counter

import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
import chess.polyglot


def is_postgres():
    return bool(os.environ.get("DATABASE_URL"))


def get_conn():
    database_url = os.environ.get("DATABASE_URL")

    if database_url:
        sslmode = os.environ.get("DB_SSLMODE", "require")
        return psycopg2.connect(
            database_url,
            cursor_factory=RealDictCursor,
            sslmode=sslmode,
            connect_timeout=5,
        )

    conn = sqlite3.connect("chess.db")
    conn.row_factory = sqlite3.Row
    return conn


def sql_placeholder():
    return "%s" if is_postgres() else "?"


def dict_row(row):
    if row is None:
        return None
    return dict(row)


def init_db():
    with get_conn() as conn:
        cur = conn.cursor()

        if is_postgres():
            cur.execute("""
                CREATE TABLE IF NOT EXISTS games (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    result TEXT NOT NULL,
                    moves_pgn TEXT NOT NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS move_memory (
                    position_hash TEXT NOT NULL,
                    move_uci TEXT NOT NULL,
                    plays INTEGER NOT NULL DEFAULT 0,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    draws INTEGER NOT NULL DEFAULT 0,
                    score DOUBLE PRECISION NOT NULL DEFAULT 0,
                    PRIMARY KEY (position_hash, move_uci)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS learning_jobs (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP NULL,
                    finished_at TIMESTAMP NULL,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    payload JSONB NOT NULL,
                    error_message TEXT NULL,
                    success_message TEXT NULL
                )
            """)
        else:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS games (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    result TEXT NOT NULL,
                    moves_pgn TEXT NOT NULL
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS move_memory (
                    position_hash TEXT NOT NULL,
                    move_uci TEXT NOT NULL,
                    plays INTEGER NOT NULL DEFAULT 0,
                    wins INTEGER NOT NULL DEFAULT 0,
                    losses INTEGER NOT NULL DEFAULT 0,
                    draws INTEGER NOT NULL DEFAULT 0,
                    score REAL NOT NULL DEFAULT 0,
                    PRIMARY KEY (position_hash, move_uci)
                )
            """)

            cur.execute("""
                CREATE TABLE IF NOT EXISTS learning_jobs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP NULL,
                    finished_at TIMESTAMP NULL,
                    job_type TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'pending',
                    payload TEXT NOT NULL,
                    error_message TEXT NULL,
                    success_message TEXT NULL
                )
            """)

        conn.commit()


def position_hash(board):
    return str(chess.polyglot.zobrist_hash(board))


def record_game(result, moves_pgn):
    p = sql_placeholder()

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO games (result, moves_pgn) VALUES ({p}, {p})",
            (result, moves_pgn),
        )
        conn.commit()


def enqueue_learning_job(job_type, payload):
    p = sql_placeholder()

    payload_str = json.dumps(payload)

    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute(
            f"""
            INSERT INTO learning_jobs (job_type, payload, status)
            VALUES ({p}, {p}, {p})
            """,
            (job_type, payload_str, "pending"),
        )

        conn.commit()


def get_next_pending_job():
    with get_conn() as conn:
        cur = conn.cursor()

        if is_postgres():
            cur.execute("""
                SELECT id, job_type, status, payload
                FROM learning_jobs
                WHERE status = 'pending'
                ORDER BY id ASC
                LIMIT 1
            """)
        else:
            cur.execute("""
                SELECT id, job_type, status, payload
                FROM learning_jobs
                WHERE status = 'pending'
                ORDER BY id ASC
                LIMIT 1
            """)

        row = cur.fetchone()
        if row is None:
            return None

        row = dict(row)
        payload = row["payload"]

        if isinstance(payload, str):
            row["payload"] = json.loads(payload)

        return row


def mark_job_processing(job_id):
    p = sql_placeholder()

    with get_conn() as conn:
        cur = conn.cursor()

        if is_postgres():
            cur.execute(
                f"""
                UPDATE learning_jobs
                SET status = {p}, started_at = CURRENT_TIMESTAMP
                WHERE id = {p}
                """,
                ("processing", job_id),
            )
        else:
            cur.execute(
                f"""
                UPDATE learning_jobs
                SET status = {p}, started_at = CURRENT_TIMESTAMP
                WHERE id = {p}
                """,
                ("processing", job_id),
            )

        conn.commit()


def mark_job_done(job_id, success_message):
    p = sql_placeholder()

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE learning_jobs
            SET status = {p},
                finished_at = CURRENT_TIMESTAMP,
                success_message = {p},
                error_message = NULL
            WHERE id = {p}
            """,
            ("done", success_message, job_id),
        )
        conn.commit()


def mark_job_failed(job_id, error_message):
    p = sql_placeholder()

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            UPDATE learning_jobs
            SET status = {p},
                finished_at = CURRENT_TIMESTAMP,
                error_message = {p}
            WHERE id = {p}
            """,
            ("failed", error_message[:2000], job_id),
        )
        conn.commit()


def get_job_counts():
    with get_conn() as conn:
        cur = conn.cursor()

        cur.execute(
            "SELECT COUNT(*) AS total FROM learning_jobs WHERE status = 'pending'"
        )
        pending = cur.fetchone()

        cur.execute(
            "SELECT COUNT(*) AS total FROM learning_jobs WHERE status = 'processing'"
        )
        processing = cur.fetchone()

        cur.execute("SELECT COUNT(*) AS total FROM learning_jobs WHERE status = 'done'")
        done = cur.fetchone()

        cur.execute(
            "SELECT COUNT(*) AS total FROM learning_jobs WHERE status = 'failed'"
        )
        failed = cur.fetchone()

        return {
            "pending": dict(pending)["total"],
            "processing": dict(processing)["total"],
            "done": dict(done)["total"],
            "failed": dict(failed)["total"],
        }


def get_position_memory(board):
    pos = position_hash(board)
    p = sql_placeholder()

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT move_uci, plays, wins, losses, draws, score
            FROM move_memory
            WHERE position_hash = {p}
            """,
            (pos,),
        )
        rows = cur.fetchall()

    memory = {}
    for raw_row in rows:
        row = dict(raw_row)
        plays = row["plays"]

        if plays == 0:
            bonus = 0.0
        else:
            win_rate = (row["wins"] + 0.5 * row["draws"]) / plays
            bonus = row["score"] + (win_rate * 40.0)

        memory[row["move_uci"]] = bonus

    return memory


def learn_from_game(experiences, result, alpha=0.35):
    reward_map = {
        "win": 1.5,
        "loss": -2.0,
        "draw": 0.0,
    }

    if result not in reward_map:
        raise ValueError("result deve ser 'win', 'loss' ou 'draw'")

    if not experiences:
        return 0

    reward = reward_map[result]
    grouped = Counter(experiences)
    keys = list(grouped.keys())

    with get_conn() as conn:
        cur = conn.cursor()

        if is_postgres():
            existing = {}

            if keys:
                placeholders = ",".join(["(%s, %s)"] * len(keys))
                params = []
                for pos_hash, move_uci in keys:
                    params.extend([pos_hash, move_uci])

                cur.execute(
                    f"""
                    SELECT position_hash, move_uci, plays, wins, losses, draws, score
                    FROM move_memory
                    WHERE (position_hash, move_uci) IN ({placeholders})
                    """,
                    params,
                )

                for row in cur.fetchall():
                    row = dict(row)
                    existing[(row["position_hash"], row["move_uci"])] = row

            rows_to_upsert = []

            total = len(keys)
            for idx, ((pos_hash, move_uci), repeat_count) in enumerate(
                grouped.items(), start=1
            ):
                row = existing.get((pos_hash, move_uci))

                if row is None:
                    plays = wins = losses = draws = 0
                    score = 0.0
                else:
                    plays = row["plays"]
                    wins = row["wins"]
                    losses = row["losses"]
                    draws = row["draws"]
                    score = row["score"]

                plays += repeat_count
                if result == "win":
                    wins += repeat_count
                elif result == "loss":
                    losses += repeat_count
                else:
                    draws += repeat_count

                weight = 1.0 + (idx / max(total, 1))
                adjusted_reward = reward * weight

                for _ in range(repeat_count):
                    score = score + alpha * (adjusted_reward - score)

                rows_to_upsert.append(
                    (pos_hash, move_uci, plays, wins, losses, draws, score)
                )

            if rows_to_upsert:
                execute_values(
                    cur,
                    """
                    INSERT INTO move_memory (
                        position_hash, move_uci, plays, wins, losses, draws, score
                    )
                    VALUES %s
                    ON CONFLICT (position_hash, move_uci)
                    DO UPDATE SET
                        plays = EXCLUDED.plays,
                        wins = EXCLUDED.wins,
                        losses = EXCLUDED.losses,
                        draws = EXCLUDED.draws,
                        score = EXCLUDED.score
                    """,
                    rows_to_upsert,
                )
        else:
            total = len(keys)
            for idx, ((pos_hash, move_uci), repeat_count) in enumerate(
                grouped.items(), start=1
            ):
                cur.execute(
                    """
                    SELECT plays, wins, losses, draws, score
                    FROM move_memory
                    WHERE position_hash = ? AND move_uci = ?
                    """,
                    (pos_hash, move_uci),
                )
                row = cur.fetchone()

                if row is None:
                    plays = wins = losses = draws = 0
                    score = 0.0
                else:
                    row = dict(row)
                    plays = row["plays"]
                    wins = row["wins"]
                    losses = row["losses"]
                    draws = row["draws"]
                    score = row["score"]

                plays += repeat_count
                if result == "win":
                    wins += repeat_count
                elif result == "loss":
                    losses += repeat_count
                else:
                    draws += repeat_count

                weight = 1.0 + (idx / max(total, 1))
                adjusted_reward = reward * weight

                for _ in range(repeat_count):
                    score = score + alpha * (adjusted_reward - score)

                cur.execute(
                    """
                    INSERT INTO move_memory (
                        position_hash, move_uci, plays, wins, losses, draws, score
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(position_hash, move_uci)
                    DO UPDATE SET
                        plays = excluded.plays,
                        wins = excluded.wins,
                        losses = excluded.losses,
                        draws = excluded.draws,
                        score = excluded.score
                    """,
                    (pos_hash, move_uci, plays, wins, losses, draws, score),
                )

        conn.commit()

    return len(grouped)
