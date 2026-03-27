import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor, execute_values
import chess.polyglot
from collections import Counter


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

        conn.commit()


def position_hash(board):
    return str(chess.polyglot.zobrist_hash(board))


def get_move_stats(board, move_uci):
    pos = position_hash(board)
    p = sql_placeholder()

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"""
            SELECT plays, wins, losses, draws, score
            FROM move_memory
            WHERE position_hash = {p} AND move_uci = {p}
            """,
            (pos, move_uci),
        )
        row = dict_row(cur.fetchone())

    if row is None:
        return {
            "plays": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "score": 0.0,
        }

    return row


def memory_bonus(board, move_uci):
    try:
        stats = get_move_stats(board, move_uci)
    except Exception as e:
        print("ERRO memory_bonus:", e)
        return 0.0

    if stats["plays"] == 0:
        return 0.0

    win_rate = (stats["wins"] + 0.5 * stats["draws"]) / stats["plays"]
    return stats["score"] + (win_rate * 40.0)


def record_game(result, moves_pgn):
    p = sql_placeholder()

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            f"INSERT INTO games (result, moves_pgn) VALUES ({p}, {p})",
            (result, moves_pgn),
        )
        conn.commit()


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

    reward = reward_map[result]
    total = len(experiences)

    with get_conn() as conn:
        cur = conn.cursor()

        for i, (pos_hash, move_uci) in enumerate(experiences):
            weight = 1.0 + (i / max(total, 1))
            adjusted_reward = reward * weight

            cur.execute(
                """
                SELECT plays, wins, losses, draws, score
                FROM move_memory
                WHERE position_hash = %s AND move_uci = %s
                """,
                (pos_hash, move_uci),
            )
            row = cur.fetchone()

            if row:
                plays = row["plays"] + 1
                wins = row["wins"] + (1 if result == "win" else 0)
                losses = row["losses"] + (1 if result == "loss" else 0)
                draws = row["draws"] + (1 if result == "draw" else 0)
                score = row["score"] + alpha * (adjusted_reward - row["score"])

                cur.execute(
                    """
                    UPDATE move_memory
                    SET plays = %s, wins = %s, losses = %s, draws = %s, score = %s
                    WHERE position_hash = %s AND move_uci = %s
                    """,
                    (plays, wins, losses, draws, score, pos_hash, move_uci),
                )
            else:
                cur.execute(
                    """
                    INSERT INTO move_memory
                    (position_hash, move_uci, plays, wins, losses, draws, score)
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        pos_hash,
                        move_uci,
                        1,
                        1 if result == "win" else 0,
                        1 if result == "loss" else 0,
                        1 if result == "draw" else 0,
                        adjusted_reward,
                    ),
                )

        conn.commit()
