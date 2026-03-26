import math
import random
import chess

from engine.memory import memory_bonus, position_hash, get_position_memory

PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

CHECKMATE_SCORE = 100000


def evaluate_position(board: chess.Board) -> int:
    if board.is_checkmate():
        return -CHECKMATE_SCORE if board.turn == chess.WHITE else CHECKMATE_SCORE

    if board.is_stalemate() or board.is_insufficient_material():
        return 0

    score = 0

    for piece_type, value in PIECE_VALUES.items():
        score += len(board.pieces(piece_type, chess.WHITE)) * value
        score -= len(board.pieces(piece_type, chess.BLACK)) * value

    return score


def order_moves(board: chess.Board, moves):
    def score_move(move):
        score = 0

        if board.is_capture(move):
            victim = board.piece_at(move.to_square)
            attacker = board.piece_at(move.from_square)
            if victim and attacker:
                score += (
                    10 * PIECE_VALUES[victim.piece_type]
                    - PIECE_VALUES[attacker.piece_type]
                )

        if board.gives_check(move):
            score += 500

        if move.promotion:
            score += 800

        return score

    return sorted(moves, key=score_move, reverse=True)


def minimax(
    board: chess.Board, depth: int, alpha: float, beta: float, maximizing: bool
) -> float:
    if depth == 0 or board.is_game_over():
        return evaluate_position(board)

    moves = order_moves(board, list(board.legal_moves))

    if maximizing:
        best = -math.inf
        for move in moves:
            board.push(move)
            value = minimax(board, depth - 1, alpha, beta, False)
            board.pop()

            best = max(best, value)
            alpha = max(alpha, value)

            if beta <= alpha:
                break

        return best

    else:
        best = math.inf
        for move in moves:
            board.push(move)
            value = minimax(board, depth - 1, alpha, beta, True)
            board.pop()

            best = min(best, value)
            beta = min(beta, value)

            if beta <= alpha:
                break

        return best


def choose_move(board: chess.Board, depth: int = 2):
    legal_moves = list(board.legal_moves)
    if not legal_moves:
        return None, []

    legal_moves = order_moves(board, legal_moves)
    maximizing = board.turn == chess.WHITE

    best_score = -math.inf if maximizing else math.inf
    best_moves = []
    experiences = []

    memory_map = get_position_memory(board)

    for move in legal_moves:
        board.push(move)

        pos_hash = position_hash(board)
        calc_score = minimax(board, depth - 1, -math.inf, math.inf, not maximizing)

        learned = memory_map.get(move.uci(), 0.0)

        if maximizing:
            total_score = calc_score + (learned * 2)
        else:
            total_score = calc_score - (learned * 2)

        experiences.append((pos_hash, move.uci()))
        board.pop()

        if maximizing:
            if total_score > best_score:
                best_score = total_score
                best_moves = [move]
            elif total_score == best_score:
                best_moves.append(move)
        else:
            if total_score < best_score:
                best_score = total_score
                best_moves = [move]
            elif total_score == best_score:
                best_moves.append(move)

    chosen_move = random.choice(best_moves) if random.random() >= 0.1 else random.choice(legal_moves)
    return chosen_move, experiences
