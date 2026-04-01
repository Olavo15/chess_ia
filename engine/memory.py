import json
import os
import sqlite3
from collections import Counter

import chess.polyglot
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values


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


def normalize_experiences(experiences):
    normalized = []

    for item in experiences or []:
        if isinstance(item, (list, tuple)) and len(item) == 2:
            normalized.append((str(item[0]), str(item[1])))

    return normalized


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
        pending = dict(cur.fetchone())["total"]

        cur.execute(
            "SELECT COUNT(*) AS total FROM learning_jobs WHERE status = 'processing'"
        )
        processing = dict(cur.fetchone())["total"]

        cur.execute("SELECT COUNT(*) AS total FROM learning_jobs WHERE status = 'done'")
        done = dict(cur.fetchone())["total"]

        cur.execute(
            "SELECT COUNT(*) AS total FROM learning_jobs WHERE status = 'failed'"
        )
        failed = dict(cur.fetchone())["total"]

    return {
        "pending": pending,
        "processing": processing,
        "done": done,
        "failed": failed,
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


def learn_from_game(experiences, result, alpha=0.65, chunk_size=200):
    reward_map = {
        "win": 8.0,
        "loss": -10.0,
        "draw": 1.5,
    }

    if result not in reward_map:
        raise ValueError("result deve ser 'win', 'loss' ou 'draw'")

    normalized_experiences = normalize_experiences(experiences)
    if not normalized_experiences:
        return 0

    reward = reward_map[result]
    grouped = Counter(normalized_experiences)
    all_items = list(grouped.items())

    total_unique = len(all_items)
    total_processed = 0

    with get_conn() as conn:
        cur = conn.cursor()

        for start in range(0, total_unique, chunk_size):
            chunk_items = all_items[start : start + chunk_size]
            chunk_keys = [item[0] for item in chunk_items]

            if is_postgres():
                existing = {}

                if chunk_keys:
                    placeholders = ",".join(["(%s, %s)"] * len(chunk_keys))
                    params = []
                    for pos_hash, move_uci in chunk_keys:
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

                for offset, ((pos_hash, move_uci), repeat_count) in enumerate(
                    chunk_items, start=1
                ):
                    global_idx = start + offset

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

                    weight = 1.0 + ((global_idx / max(total_unique, 1)) * 3.5)
                    adjusted_reward = reward * weight

                    if result == "loss":
                        adjusted_reward -= 4.0
                    if result == "win":
                        adjusted_reward += 2.0

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
                for offset, ((pos_hash, move_uci), repeat_count) in enumerate(
                    chunk_items, start=1
                ):
                    global_idx = start + offset

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

                    weight = 1.0 + ((global_idx / max(total_unique, 1)) * 3.5)
                    adjusted_reward = reward * weight

                    if result == "loss":
                        adjusted_reward -= 4.0
                    if result == "win":
                        adjusted_reward += 2.0

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

            total_processed += len(chunk_items)

        conn.commit()

    return total_processed
