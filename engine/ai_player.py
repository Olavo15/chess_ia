import math
import random
import chess
import torch

from engine.neural_net import get_model, board_to_tensor
from engine.memory import get_position_memory, position_hash

NN_MODEL = get_model()

PIECE_VALUES = {
    chess.PAWN: 100,
    chess.KNIGHT: 320,
    chess.BISHOP: 330,
    chess.ROOK: 500,
    chess.QUEEN: 900,
    chess.KING: 0,
}

CHECKMATE_SCORE = 100000


def evaluate_position(board: chess.Board) -> float:
    if board.is_checkmate():
        return -CHECKMATE_SCORE if board.turn == chess.WHITE else CHECKMATE_SCORE

    if (
        board.is_stalemate()
        or board.is_insufficient_material()
        or board.is_seventyfive_moves()
        or board.is_fivefold_repetition()
    ):
        return 0.0

    tensor_state = board_to_tensor(board)
    with torch.no_grad():
        score = NN_MODEL(tensor_state).item()

    return score * 2000.0


def order_moves(board: chess.Board, moves):
    def move_score(move):
        score = 0

        if board.is_capture(move):
            victim = board.piece_at(move.to_square)
            attacker = board.piece_at(move.from_square)
            if victim and attacker:
                score += (
                    10 * PIECE_VALUES[victim.piece_type]
                    - PIECE_VALUES[attacker.piece_type]
                )
            else:
                score += 200

        if board.gives_check(move):
            score += 700

        if move.promotion:
            score += 1200

        return score

    return sorted(moves, key=move_score, reverse=True)


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


def choose_move(
    board: chess.Board,
    depth: int = 2,
    use_memory: bool = True,
    memory_weight: float = 12.0,
    exploration_rate: float = 0.03,
):
    legal_moves = list(board.legal_moves)
    if not legal_moves:
        return None, []

    legal_moves = order_moves(board, legal_moves)
    maximizing = board.turn == chess.WHITE

    best_score = -math.inf if maximizing else math.inf
    best_moves = []
    experiences = []

    try:
        memory_map = get_position_memory(board) if use_memory else {}
    except Exception as e:
        print("ERRO carregando memória da posição:", e)
        memory_map = {}

    for move in legal_moves:
        board.push(move)

        pos_hash = position_hash(board)
        calc_score = minimax(board, depth - 1, -math.inf, math.inf, not maximizing)

        raw_learned = memory_map.get(move.uci(), 0.0)
        
        sign = 1 if maximizing else -1

        learned_bonus = (raw_learned * 100.0) * memory_weight * sign

        tactical_bonus = 0

        if board.is_check():
            tactical_bonus += 120

        if board.is_checkmate():
            tactical_bonus += 50000

        if move.promotion:
            tactical_bonus += 1500

        tactical_bonus *= sign

        board.pop()

        total_score = calc_score + learned_bonus + tactical_bonus

        experiences.append((pos_hash, move.uci()))

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

    if not best_moves:
        best_moves = legal_moves

    if random.random() < exploration_rate:
        chosen_move = random.choice(legal_moves[: min(5, len(legal_moves))])
    else:
        chosen_move = random.choice(best_moves)

    return chosen_move, experiences
