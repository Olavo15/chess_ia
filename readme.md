# ♟️ Chess IA

Uma aplicação web de xadrez com inteligência artificial desenvolvida em **Python (Flask)**, com interface interativa no navegador e suporte a jogadas legais, histórico e análise de jogo.

---

## 🚀 Funcionalidades

- ✅ Tabuleiro interativo
- ✅ Validação de jogadas com regras oficiais do xadrez
- ✅ IA jogando contra o usuário
- ✅ Detecção de:
  - Check
  - Checkmate
  - Empate
- ✅ Histórico de jogadas
- ✅ Destaque de movimentos possíveis
- ✅ Promoção de peões
- ✅ API com Flask
- 🚧 IA em evolução com aprendizado

---

## 🧠 Tecnologias utilizadas

### Backend

- Python
- Flask
- python-chess

### Frontend

- HTML
- CSS
- JavaScript
- chessboard.js
- chess.js

### IA

- Algoritmo de busca / heurística
- Estrutura preparada para aprendizado e self-play

---

## 📁 Estrutura do projeto

```bash
chess_ia/
│
├── web/
│   └── app.py
│
├── engine/
│   ├── ai_player.py
|   ├── board.py
|   ├── q_learning.py
│   ├── memory.py
│
├── templates/
│   └── index.html
│
├── static/
│   ├── js/
│   ├── css/
│   └── img/
│
├── data/
│   └── chess_ai.db
│
├── requirements.txt
└── README.md
```

## 🗺️ Roadmap

### 🤖 IA

- [x] Melhorar heurística
- [ ] Minimax + Alpha-Beta
- [ ] Self-play automático
- [x] Aprendizado persistente

### 🎮 Gameplay

- [ ] Ranking / Elo
- [ ] Histórico completo de partidas
- [x] Exportação de PGN

### 🎨 Interface

- [ ] UI estilo Chess.com
- [ ] Animações de movimento
- [ ] Destaque de jogadas

### 📊 Análise

- [ ] Análise de partidas
- [x] Avaliação de posição

# ⭐ Contribuições

### Contribuições são bem-vindas.

### Fluxo sugerido:

```bash
fork
git clone
git checkout -b minha-feature
git commit -m "feat: minha melhoria"
git push origin minha-feature
```

### Depois, abra um Pull Request.

# 💡 Observação

### Este projeto está em evolução contínua, principalmente na parte de inteligência artificial. A ideia é transformar o projeto em uma engine capaz de aprender com as próprias partidas.
