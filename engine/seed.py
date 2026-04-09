import sys
import os

# Garante que o diretório raiz está no path
sys.path.append(os.getcwd())

from engine.memory import seed_openings_from_pgn, init_db


def main():
    pgn_path = "data/kasparov.pgn"
    if len(sys.argv) > 1:
        pgn_path = sys.argv[1]

    print(f"Iniciando semeadura de aberturas usando: {pgn_path}")
    init_db()

    # Processa apenas os primeiros 10 lances de cada partida
    games = seed_openings_from_pgn(pgn_path, max_moves=10)

    print(f"\nConcluído! {games} partidas foram injetadas na memória de aberturas.")
    print("Agora a IA terá preferência pelos lances vitoriosos contidos nesse PGN.")


if __name__ == "__main__":
    main()
