import sqlite3
from pathlib import Path
import chess.polyglot

DB_PATH = Path("data/chess_ai.db")


def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS games (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                result TEXT NOT NULL,
                moves_pgn TEXT NOT NULL
            )
        """)
        conn.execute("""
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


def position_hash(board):
    return str(chess.polyglot.zobrist_hash(board))


def get_move_stats(board, move_uci):
    pos = position_hash(board)
    with get_conn() as conn:
        row = conn.execute(
            """
            SELECT plays, wins, losses, draws, score
            FROM move_memory
            WHERE position_hash = ? AND move_uci = ?
            """,
            (pos, move_uci),
        ).fetchone()

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
    stats = get_move_stats(board, move_uci)

    if stats["plays"] == 0:
        return 0.0

    win_rate = (stats["wins"] + 0.5 * stats["draws"]) / stats["plays"]
    return stats["score"] + (win_rate * 40.0)


def record_game(result, moves_pgn):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO games (result, moves_pgn) VALUES (?, ?)",
            (result, moves_pgn),
        )


def learn_from_game(experiences, result, alpha=0.2):
    """
    experiences = [(position_hash, move_uci), ...] só da IA
    result: 'win', 'loss', 'draw'
    """
    reward_map = {
        "win": 1.0,
        "loss": -1.0,
        "draw": 0.1,
    }
    reward = reward_map[result]

    with get_conn() as conn:
        for pos_hash, move_uci in experiences:
            row = conn.execute(
                """
                SELECT plays, wins, losses, draws, score
                FROM move_memory
                WHERE position_hash = ? AND move_uci = ?
                """,
                (pos_hash, move_uci),
            ).fetchone()

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

            conn.execute(
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