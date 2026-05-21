import sys
import os
from io import StringIO
from datetime import datetime
import chess
import chess.pgn

sys.path.append(os.getcwd())

from engine.memory import init_db, record_game, learn_from_game
from engine.ai_player import choose_move


def build_pgn_from_history(history, result="*", self_play=False):
    """
    Constrói a string PGN de uma partida baseada no histórico de movimentos.
    """
    game = chess.pgn.Game()
    game.headers["Event"] = "Partida Automatica Keep-Alive"
    game.headers["Site"] = (
        "Local" if not os.environ.get("DATABASE_URL") else "Production (Supabase)"
    )
    game.headers["Date"] = datetime.now().strftime("%Y.%m.%d")
    game.headers["Round"] = "1"

    if self_play:
        game.headers["White"] = "AI White Keep-Alive"
        game.headers["Black"] = "AI Black Keep-Alive"
    else:
        game.headers["White"] = "Player"
        game.headers["Black"] = "Chess IA"

    game.headers["Result"] = result

    node = game
    temp_board = chess.Board()

    for item in history:
        move = chess.Move.from_uci(item["uci"])
        if move in temp_board.legal_moves:
            node = node.add_variation(move)
            temp_board.push(move)

    exporter = StringIO()
    print(game, file=exporter, end="\n")
    return exporter.getvalue()


def run_auto_game():
    print("=== [KEEP-ALIVE] Iniciando partida de xadrez automatica ===")

    init_db()

    board = chess.Board()
    history = []
    ai_experiences = {
        "white": [],
        "black": [],
    }

    move_count = 0
    max_moves = 80

    while not board.is_game_over() and move_count < max_moves:
        side = "white" if board.turn == chess.WHITE else "black"

        ai_move, exp = choose_move(
            board,
            depth=1,
            use_memory=False,
            exploration_rate=0.20,
        )

        if ai_move is None:
            print(
                "[KEEP-ALIVE] Alerta: Nenhum lance disponível encontrado pelo jogador de IA."
            )
            break

        san = board.san(ai_move)
        board.push(ai_move)

        # Registra o histórico
        history.append(
            {
                "uci": ai_move.uci(),
                "san": san,
                "from": chess.square_name(ai_move.from_square),
                "to": chess.square_name(ai_move.to_square),
                "promotion": (
                    chess.piece_symbol(ai_move.promotion) if ai_move.promotion else None
                ),
            }
        )

        if exp:
            ai_experiences[side].extend(exp)

        move_count += 1

    result = board.result() if board.is_game_over() else "*"
    print(
        f"[KEEP-ALIVE] Partida encerrada. Resultado: {result} em {move_count} lances."
    )

    pgn_text = build_pgn_from_history(history, result=result, self_play=True)

    print("[KEEP-ALIVE] Gravando partida na tabela 'games'...")
    record_game(result, pgn_text)

    print("[KEEP-ALIVE] Treinando modelo a partir das experiencias da partida...")
    learned_count = 0
    if result == "1-0":
        if ai_experiences["white"]:
            learned_count += learn_from_game(ai_experiences["white"], "win")
        if ai_experiences["black"]:
            learned_count += learn_from_game(ai_experiences["black"], "loss")
    elif result == "0-1":
        if ai_experiences["white"]:
            learned_count += learn_from_game(ai_experiences["white"], "loss")
        if ai_experiences["black"]:
            learned_count += learn_from_game(ai_experiences["black"], "win")
    else:
        if ai_experiences["white"]:
            learned_count += learn_from_game(ai_experiences["white"], "draw")
        if ai_experiences["black"]:
            learned_count += learn_from_game(ai_experiences["black"], "draw")

    print(
        f"[KEEP-ALIVE] Concluido! {learned_count} posicoes atualizadas na tabela 'move_memory'."
    )
    print("=== [KEEP-ALIVE] Banco de dados mantido ativo com sucesso! ===")


if __name__ == "__main__":
    run_auto_game()
