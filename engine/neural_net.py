import torch
import torch.nn as nn
import torch.nn.functional as F
import numpy as np
import chess
import os


class ChessNet(nn.Module):
    def __init__(self):
        super(ChessNet, self).__init__()
        self.conv1 = nn.Conv2d(14, 64, kernel_size=3, padding=1)
        self.conv2 = nn.Conv2d(64, 128, kernel_size=3, padding=1)
        self.conv3 = nn.Conv2d(128, 128, kernel_size=3, padding=1)

        self.fc1 = nn.Linear(128 * 8 * 8, 256)
        self.fc2 = nn.Linear(256, 1)

    def forward(self, x):
        x = F.relu(self.conv1(x))
        x = F.relu(self.conv2(x))
        x = F.relu(self.conv3(x))

        x = x.view(-1, 128 * 8 * 8)

        x = F.relu(self.fc1(x))
        x = self.fc2(x)
        return x


def board_to_tensor(board: chess.Board):
    """
    Converte o estado atual do tabuleiro em um Tensor PyTorch de shape (1, 14, 8, 8)
    onde 1 é o tamanho do batch (1 tabuleiro por vez).
    """
    matrix = np.zeros((14, 8, 8), dtype=np.float32)

    pieces = {
        chess.PAWN: 0,
        chess.KNIGHT: 1,
        chess.BISHOP: 2,
        chess.ROOK: 3,
        chess.QUEEN: 4,
        chess.KING: 5,
    }

    for square in chess.SQUARES:
        piece = board.piece_at(square)
        if piece:
            channel = pieces[piece.piece_type]
            if piece.color == chess.BLACK:
                channel += 6
            row = chess.square_rank(square)
            col = chess.square_file(square)
            matrix[channel, row, col] = 1.0

    for move in board.legal_moves:
        row = chess.square_rank(move.to_square)
        col = chess.square_file(move.to_square)
        matrix[12, row, col] = 1.0
    turn_val = 1.0 if board.turn == chess.WHITE else -1.0
    matrix[13, :, :] = turn_val

    tensor = torch.from_numpy(matrix).unsqueeze(0)
    return tensor


def get_model(model_path="data/model_weights.pth"):
    model = ChessNet()
    if os.path.exists(model_path):
        try:
            model.load_state_dict(
                torch.load(model_path, map_location=torch.device("cpu"))
            )
            print(f"Pesos carregados de {model_path}")
        except Exception as e:
            print(f"Erro ao carregar pesos: {e}")
    else:
        print(
            "Modelo sem pesos carregados. Iniciando com pesos aleatórios (A IA jogará aleatoriamente)."
        )

    model.eval()
    return model
