import os
import psycopg2
from psycopg2.extras import RealDictCursor
import chess.polyglot
from urllib.parse import urlparse


def get_conn():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("DATABASE_URL não configurada")

    parsed = urlparse(database_url)

    return psycopg2.connect(
        database_url,
        cursor_factory=RealDictCursor,
        sslmode="require",
        connect_timeout=5,
    )


def init_db():
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS games (
                    id SERIAL PRIMARY KEY,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    result TEXT NOT NULL,
                    moves_pgn TEXT NOT NULL
                )
            """
            )

            cur.execute(
                """
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
            """
            )
        conn.commit()


def position_hash(board):
    return str(chess.polyglot.zobrist_hash(board))


def get_move_stats(board, move_uci):
    pos = position_hash(board)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT plays, wins, losses, draws, score
                FROM move_memory
                WHERE position_hash = %s AND move_uci = %s
                """,
                (pos, move_uci),
            )
            row = cur.fetchone()

    if row is None:
        return {
            "plays": 0,
            "wins": 0,
            "losses": 0,
            "draws": 0,
            "score": 0.0,
        }

    return dict(row)


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
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO games (result, moves_pgn) VALUES (%s, %s)",
                (result, moves_pgn),
            )
        conn.commit()


def get_position_memory(board):
    pos = position_hash(board)

    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT move_uci, plays, wins, losses, draws, score
                FROM move_memory
                WHERE position_hash = %s
                """,
                (pos,),
            )
            rows = cur.fetchall()

    memory = {}
    for row in rows:
        plays = row["plays"]
        if plays == 0:
            bonus = 0.0
        else:
            win_rate = (row["wins"] + 0.5 * row["draws"]) / plays
            bonus = row["score"] + (win_rate * 40.0)

        memory[row["move_uci"]] = bonus

    return memory


def learn_from_game(experiences, result, alpha=0.2):
    reward_map = {
        "win": 1.0,
        "loss": -1.0,
        "draw": 0.1,
    }
    reward = reward_map[result]

    with get_conn() as conn:
        with conn.cursor() as cur:
            for pos_hash, move_uci in experiences:
                cur.execute(
                    """
                    SELECT plays, wins, losses, draws, score
                    FROM move_memory
                    WHERE position_hash = %s AND move_uci = %s
                    """,
                    (pos_hash, move_uci),
                )
                row = cur.fetchone()

                if row is None:
                    plays = wins = losses = draws = 0
                    score = 0.0
                else:
                    plays = row["plays"]
                    wins = row["wins"]
                    losses = row["losses"]
                    draws = row["draws"]
                    score = row["score"]

                plays += 1
                if result == "win":
                    wins += 1
                elif result == "loss":
                    losses += 1
                else:
                    draws += 1

                score = score + alpha * (reward - score)

                cur.execute(
                    """
                    INSERT INTO move_memory (
                        position_hash, move_uci, plays, wins, losses, draws, score
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (position_hash, move_uci)
                    DO UPDATE SET
                        plays = EXCLUDED.plays,
                        wins = EXCLUDED.wins,
                        losses = EXCLUDED.losses,
                        draws = EXCLUDED.draws,
                        score = EXCLUDED.score
                    """,
                    (pos_hash, move_uci, plays, wins, losses, draws, score),
                )

        conn.commit()
