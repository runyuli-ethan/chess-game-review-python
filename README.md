# Chess Game Review

Chess Game Review is a Python program that analyzes a completed chess game with
Stockfish. Paste a game in PGN format and the program reviews every move, shows
which player has the stronger position, suggests better lines, and estimates
how strongly each player performed in that game.

## Features

- Reviews every move with Stockfish.
- Uses nine move labels: Best, Excellent, Good, Inaccuracy, Mistake, Blunder,
  Missed win, Missed mate, and Forced.
- Shows each player's position share after every move.
- Shows Stockfish's White-win, draw, and Black-win forecast.
- Prints a suggested best line after a non-best move when one is available.
- Rechecks important or uncertain positions with a deeper search.
- Gives each player a rough single-game Elo estimate and a wide plausible range.

## Requirements

- Python 3.10 or newer
- Stockfish
- The Python package listed in `requirements.txt`

Stockfish is a separate chess engine and is not included in this repository.

## One-time setup

Create a Python environment and install the required Python package:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

On macOS, Stockfish can be installed with Homebrew:

```bash
brew install stockfish
```

You can also download Stockfish from its official website. If it is not
installed in a normal system location, place the executable in the project's
`bin` folder and name it `stockfish` or `stockfish.exe`.

The program searches automatically for Stockfish in:

- The project's `bin` folder
- Common macOS, Linux, and Windows installation locations
- The system PATH
- The usual folder created by the official macOS Stockfish download

## Run the program

1. Open this project folder in your code editor.
2. Select the Python interpreter inside the project's `.venv` folder.
3. Open `main.py` and use the editor's normal **Run** command.
4. Paste the complete PGN.
5. Enter `END` on a new line.

The editor must run `main.py` in a console that accepts keyboard input. The PGN
is the only information the program asks the user to enter.

You can also start it from a terminal:

```bash
.venv/bin/python main.py
```

## How it works

```text
main.py
  collects the PGN and displays progress
       ↓
chess_review.py
  reads the game and rebuilds every board position
       ↓
Stockfish
  examines the strongest choices in each position
       ↓
chess_review.py
  compares the played moves, assigns labels, estimates performance,
  and builds the report
       ↓
main.py
  prints the completed review
```

Every unfinished position receives a 30,000-node Stockfish search. Important or
uncertain positions are checked again with 150,000 nodes. A node is one position
Stockfish reaches while considering possible future moves.

## Understanding the percentages

W/D/L means Stockfish's White-win, draw, and Black-win forecast.

The two player percentages are position shares. Each player receives half of
the draw chance, so the two shares always total 100%. For example:

```text
White win: 40% | Draw: 40% | Black win: 20%
White share: 60% | Black share: 40%
```

## Project files

```text
main.py                    User input, progress, and printed output
chess_review.py            PGN reading, Stockfish analysis, labels, and report
requirements.txt           Required Python package
tests/test_chess_review.py Automatic checks for the main review calculations
bin/README.md              Instructions for the optional local Stockfish file
```

## Run the tests

The tests use small prepared positions and do not start Stockfish:

```bash
.venv/bin/python -m unittest discover -s tests -v
```

## Important limitation

The Elo result describes performance in one game only. It is not an official or
reliable measurement of a player's true rating. A real rating requires results
from many games against rated opponents.
