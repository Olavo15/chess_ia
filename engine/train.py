import torch
import torch.nn as nn
import torch.optim as optim
import chess
import chess.pgn
import random
import os
import sys
from engine.neural_net import ChessNet, board_to_tensor, get_model

LEARNING_RATE = 0.0005
BATCH_SIZE = 64
EPOCHS = 20
MODEL_PATH = "data/model_weights.pth"
PGN_DATASET = "data/kasparov.pgn"


def stream_pgn_batches(pgn_path, batch_size=BATCH_SIZE, samples_per_game=15):
    """
    Função Geradora (Yield)! Ela lê o log PGN gigantesco partida por partida
    e nunca o carrrega inteiro pra memória RAM.
    """
    if not os.path.exists(pgn_path):
        print(f"Erro: Arquivo PGN {pgn_path} não encontrado.")
        return

    with open(pgn_path, "r", encoding="utf-8", errors="replace") as pgn_file:
        x_batch = []
        y_batch = []

        while True:
            game = chess.pgn.read_game(pgn_file)
            if game is None:
                break

            result = game.headers.get("Result")
            if result == "1-0":
                target_score = 1.0
            elif result == "0-1":
                target_score = -1.0
            elif result == "1/2-1/2":
                target_score = 0.0
            else:
                continue

            board = game.board()
            positions = []

            for move in game.mainline_moves():
                board.push(move)
                if board.fullmove_number > 5:
                    positions.append(board.copy())

            if not positions:
                continue

            sample_size = min(samples_per_game, len(positions))
            sampled_positions = random.sample(positions, sample_size)

            for b in sampled_positions:
                x_batch.append(board_to_tensor(b))
                y_batch.append(torch.tensor([[target_score]], dtype=torch.float32))

                if len(x_batch) >= batch_size:
                    yield torch.cat(x_batch, dim=0), torch.cat(y_batch, dim=0)
                    x_batch = []
                    y_batch = []

        if len(x_batch) > 0:
            yield torch.cat(x_batch, dim=0), torch.cat(y_batch, dim=0)


def train():
    print(f"Buscando dataset em {PGN_DATASET} ...")
    if not os.path.exists(PGN_DATASET):
        print(
            "Dataset PGN não encontrado. Cancele e rode o script pra baixar o dataset primeiro."
        )
        sys.exit(1)

    print("Inicializando o modelo Neural PyTorch...")
    model = get_model(MODEL_PATH)
    model.train()

    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=LEARNING_RATE)

    device = next(model.parameters()).device

    for epoch in range(EPOCHS):
        total_loss = 0.0
        batches_processed = 0

        print(f"\nIniciando Epoch {epoch+1}/{EPOCHS}...")

        for x_data, y_target in stream_pgn_batches(PGN_DATASET, BATCH_SIZE):
            x_data = x_data.to(device)
            y_target = y_target.to(device)

            optimizer.zero_grad()

            prediction = model(x_data)

            loss = criterion(prediction, y_target)
            loss.backward()
            optimizer.step()

            total_loss += loss.item()
            batches_processed += 1

            if batches_processed % 10 == 0:
                print(
                    f"  [Epoch {epoch+1}] Lote {batches_processed} treinado. Loss média: {total_loss/batches_processed:.4f}"
                )

        if not os.path.exists("data"):
            os.makedirs("data")
        torch.save(model.state_dict(), MODEL_PATH)
        print(f"-> Fim do Epoch {epoch+1}. Modelo salvo em {MODEL_PATH}")


if __name__ == "__main__":
    train()
