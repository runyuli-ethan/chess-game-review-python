# Chess Game Review — Simplified Python

This is the fixed-setting version of the Python chess reviewer. The only user input is a PGN.

## One-time setup

Create a Python environment and install the project's single Python dependency:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Install native Stockfish on macOS if it is not already installed:

```bash
brew install stockfish
```

The program automatically searches this folder's optional `bin` directory, common installation locations, and the system PATH. There are no engine-path or strength settings to enter.

It also recognizes the normal folder created by the official macOS Stockfish download. On this Mac it automatically finds the existing Stockfish 18 program in `Downloads`.

## Run it in any code editor

1. Open this project folder in your code editor.
2. Make sure the editor uses this project's `.venv` Python environment.
3. Open `main.py` and use the editor's normal **Run** command.
4. Paste the complete PGN.
5. Enter `END` on a new line.

The editor must run `main.py` in a console that accepts keyboard input. No terminal options, filenames, or settings are entered into the program; the PGN is its only user input.

## Simple framework

```text
main.py
  asks for the PGN and prints the result
       ↓
chess_review.py
  reads the game, runs Stockfish, grades moves, and builds the report
       ↓
Stockfish
  supplies the chess calculations
```

## What was removed from Version 1

- Terminal commands and their parser
- PGN filename and piped-input choices
- Quick, Balanced, Deep, and custom-node choices
- JSON output
- User-supplied engine paths and environment settings
- Package launcher files and installable command setup
- Separate files used only to divide the same review process
- Parsed move fields that the review never used

The fixed Balanced analysis, adaptive rechecks, nine labels, percentages, best lines, and Elo estimates were kept.

## Fixed analysis quality

- Every non-finished position: 30,000 Stockfish nodes with the best two choices.
- Important or uncertain positions: rechecked at 150,000 nodes.
- All nine labels, player percentages, best lines, and both Elo estimates are retained.

The Elo result is a low-confidence estimate from one game, not a real rating measurement.
