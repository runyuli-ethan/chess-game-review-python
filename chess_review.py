"""All chess-review work used by main.py.

The work moves through this file in the following order:
1. Read the PGN and rebuild every board position.
2. Find and start Stockfish, the separate chess-calculation program.
3. Ask Stockfish to examine every position.
4. Turn its answers into percentages and move labels.
5. Recheck difficult decisions with more work.
6. Estimate each player's performance and build the printed report.

Names beginning with an underscore, such as _parse_pgn(), are internal helper
functions. The only function main.py needs to call is review_pgn() at the end.
"""

# Type hints are notes such as value: int or -> str. This import lets Python
# store those notes without needing to fully read every named type immediately.
from __future__ import annotations

# io lets python-chess read the user's text as though it were a small text file.
import io

# math supplies the formulas used for percentages, move quality, and Elo.
import math

# os checks whether a Stockfish file is allowed to run on this computer.
import os

# shutil.which() searches the computer's normal command locations for Stockfish.
import shutil

# @dataclass creates the normal setup code for classes that mainly hold data.
from dataclasses import dataclass

# Path safely builds and checks file locations on macOS, Windows, and Linux.
from pathlib import Path

# Callable is a type hint meaning "a function that can be called later."
from typing import Callable

# python-chess supplies the chess rules, board objects, PGN reader, and the
# connection used to speak with Stockfish.
import chess
import chess.engine
import chess.pgn


# -----------------------------------------------------------------------------
# FIXED REVIEW SETTINGS
# -----------------------------------------------------------------------------

# A node is one point Stockfish reaches while searching possible future moves.
# Every unfinished position gets 30,000 nodes. Selected uncertain positions are
# later checked again with 150,000 nodes. These fixed values match the original
# project's Balanced mode and are not user options.
BASE_NODES = 30_000
DEEP_NODES = 150_000

# __file__ is this file's location. parent gives the project folder containing
# it, which is needed when looking for an optional bin/stockfish file.
PROJECT_FOLDER = Path(__file__).resolve().parent

# quality_loss measures how much worse the played move was than Stockfish's
# choice. These limits turn that number into the five normal quality labels.
# Larger special mistakes are handled separately as Missed win/mate or Blunder.
LOSS_LIMITS = {
    "best": 0.5,
    "excellent": 2.0,
    "good": 5.0,
    "inaccuracy": 10.0,
    "mistake": 20.0,
}

# This table connects the calculated game-accuracy score on the left to a rough
# single-game Elo value on the right. Values between rows are filled in later.
ELO_CURVE = [
    (20, 100),
    (35, 250),
    (50, 450),
    (60, 650),
    (70, 900),
    (80, 1200),
    (88, 1550),
    (94, 2000),
    (97, 2350),
    (99, 2700),
    (100, 3000),
]


# -----------------------------------------------------------------------------
# SMALL DATA CONTAINERS
# -----------------------------------------------------------------------------

class ReviewError(ValueError):
    """An expected review problem that main.py can show in a short message."""


# @dataclass creates __init__ automatically so these classes can be filled with
# values directly. It turns calling hundreds of variables into a single, uniform package of 
# all variables that relate to each other.
# 
# frozen=True prevents recorded results from being changed by
# accident after they are created.
@dataclass(frozen=True)
class Move:
    """Only the facts about one played move that the review actually needs."""

    # Both White's and Black's first turns use move number 1.
    move_number: int

    # "w" means White and "b" means Black.
    color: str

    # SAN is the readable move form, such as Nf3, O-O, or Qc3#.
    san: str

    # UCI is the exact start/end-square form used by engines, such as g1f3.
    uci: str

    # A move is forced when this number is 1.
    legal_move_count: int

    # FEN is one line of text that describes the whole board before this move.
    # It is kept so the best engine line can later be changed into readable SAN.
    before_fen: str
    gives_checkmate: bool


@dataclass
class Game:
    """The parsed game: its PGN information, moves, and every board position."""

    # PGN headers contain items such as White, Black, ratings, and Result.
    headers: dict[str, str]
    moves: list[Move]

    # There is one board before the first move and one after every move.
    boards: list[chess.Board]
    result: str


@dataclass(frozen=True)
class Line:
    """One possible continuation returned by Stockfish."""

    # score_kind is "cp" for centipawns, "mate" for a forced checkmate, or
    # None if Stockfish did not provide a score. One pawn is about 100 cp.
    score_kind: str | None
    score_value: int

    # Stockfish normally gives win/draw/loss values that total 1,000. None means
    # that particular Stockfish version did not supply those values.
    win: int | None
    draw: int | None
    loss: int | None

    # The expected future moves, stored in exact UCI form.
    moves: list[str]


@dataclass(frozen=True)
class PositionAnalysis:
    """Stockfish's ranked choices for one board position."""

    # lines[0] is the best choice and lines[1] is the second-best choice.
    lines: list[Line]


@dataclass(frozen=True)
class Chances:
    """The percentages shown or used for one position."""

    # These three direct chances add to about 100%.
    white_win: float
    draw: float
    black_win: float

    # Position share gives each player half of the draw chance. White share and
    # Black share therefore add to 100% and create the headline percentages.
    white_share: float
    black_share: float


@dataclass(frozen=True)
class MoveReview:
    """Everything calculated about one move after comparing it with Stockfish."""

    move: Move
    classification: str
    best_uci: str | None
    played_is_best: bool

    # score_loss is lost position-share points. centipawn_loss is lost engine
    # value. quality_loss combines both so one label can be chosen reliably.
    score_loss: float
    centipawn_loss: float
    quality_loss: float

    # raw_score_loss may be negative when two separate engine searches contain
    # small differences. It helps decide whether a deeper recheck is needed.
    raw_score_loss: float

    # A large gap means the best choice was much better than the second choice.
    second_best_gap: float | None
    after_chances: Chances
    best_line: Line | None


@dataclass(frozen=True)
class Performance:
    """One player's low-confidence performance estimate for this game only."""

    estimate: int | None
    low: int | None
    high: int | None
    accuracy: float | None

    # The number of non-forced decisions used by the estimate.
    moves: int


@dataclass(frozen=True)
class ReviewResult:
    """The final information needed to create the printed report."""

    game: Game
    reviews: list[MoveReview]
    white_performance: Performance
    black_performance: Performance


def _is_draw(board: chess.Board) -> bool:
    """Return True when this board should be treated as a finished draw.

    The checks cover stalemate, too little material to mate, the automatic
    75-move/five-repeat rules, and the claimable 50-move/three-repeat rules.
    Keeping each board's move history makes the repeat checks accurate.
    """
    return (
        board.is_stalemate()
        or board.is_insufficient_material()
        or board.is_seventyfive_moves()
        or board.is_fivefold_repetition()
        or board.is_fifty_moves()
        or board.is_repetition(3)
    )


def _parse_pgn(pgn: str) -> Game:
    """Turn the user's PGN text into the Game object used by the review.

    python-chess reads the text, applies every move using real chess rules, and
    lets this function save a board before and after each turn. Those saved
    boards are what Stockfish examines later.
    """

    # Remove unused space around the paste and reject an empty result.
    source = pgn.strip()
    if not source:
        raise ReviewError("No PGN was provided.")

    # StringIO makes ordinary text act like a text file because read_game()
    # expects something it can read line by line.
    try:
        parsed = chess.pgn.read_game(io.StringIO(source))
    except (ValueError, IndexError, TypeError) as error:
        raise ReviewError(f"The PGN could not be read: {error}") from error

    # read_game() can return no game or a game containing a recorded parse error.
    if parsed is None:
        raise ReviewError("The PGN could not be read.")
    if parsed.errors:
        raise ReviewError(f"The PGN could not be read: {parsed.errors[0]}")

    # mainline_moves() ignores side variations and keeps the moves actually
    # played in the game. list() saves them so they can be looped over.
    mainline = list(parsed.mainline_moves())
    if not mainline:
        raise ReviewError("The PGN contains no moves.")

    # Start from the PGN's opening board. Usually this is the normal starting
    # position, but PGN can also provide a custom starting position.
    board = parsed.board()

    # stack=True keeps earlier moves inside the copy. That history is required
    # to detect threefold repetition correctly.
    boards = [board.copy(stack=True)]
    moves: list[Move] = []

    # Apply each move in order while saving the facts needed for grading.
    for index, chess_move in enumerate(mainline):
        before_fen = board.fen()
        color = "w" if board.turn == chess.WHITE else "b"

        # This changes a chess move into normal, readable chess notation and saves that text in san.
        san = board.san(chess_move)
        legal_move_count = board.legal_moves.count()

        # push() changes board to the position after this move.
        board.push(chess_move)
        moves.append(
            Move(
                # // performs whole-number division: indexes 0 and 1 become
                # move 1, indexes 2 and 3 become move 2, and so on.
                move_number=index // 2 + 1,
                color=color,
                san=san,
                uci=chess_move.uci(),
                legal_move_count=legal_move_count,
                before_fen=before_fen,
                gives_checkmate=board.is_checkmate(),
            )
        )

        # Save the new board while keeping the full move history.
        boards.append(board.copy(stack=True))

    # Convert all PGN header names and values to normal strings, then return the
    # complete parsed game. "*" means the PGN did not state a finished result.
    headers = {str(key): str(value) for key, value in parsed.headers.items()}
    return Game(headers, moves, boards, headers.get("Result", "*"))


def _is_executable(path: Path) -> bool:
    """Check that a path is a real file and the computer is allowed to run it."""
    return path.is_file() and os.access(path, os.X_OK)


def _find_stockfish() -> str:
    """Find the Stockfish program automatically and return its full path.

    A path is the written location of a file. This function builds a list of
    likely locations, checks them in order, and returns the first runnable one.
    """

    # First look in this project's bin folder. glob("stockfish*") means every
    # file whose name begins with stockfish, including versioned filenames.
    bin_folder = PROJECT_FOLDER / "bin"
    candidates = [bin_folder / "stockfish", bin_folder / "stockfish.exe"]
    if bin_folder.is_dir():
        candidates.extend(sorted(bin_folder.glob("stockfish*")))

    # Next check common native installation locations. These come before PATH so
    # an unrelated script named stockfish cannot hide the real engine program.
    candidates.extend(
        [
            Path("/opt/homebrew/bin/stockfish"),
            Path("/usr/local/bin/stockfish"),
            Path("/usr/bin/stockfish"),
            Path(r"C:\Program Files\Stockfish\stockfish.exe"),
        ]
    )

    # The official macOS download normally creates a folder shaped like:
    # Downloads/stockfish18/stockfish/stockfish-macos-m1-apple-silicon
    downloads = Path.home() / "Downloads"
    if downloads.is_dir():
        candidates.extend(sorted(downloads.glob("stockfish*/stockfish/stockfish-macos*")))

    # PATH is the operating system's normal list of command locations.
    on_path = shutil.which("stockfish")
    if on_path:
        candidates.append(Path(on_path))

    # checked avoids testing the same path twice. resolve() changes the winning
    # path into its complete absolute location before returning it.
    checked: set[Path] = set()
    for candidate in candidates:
        if candidate not in checked and _is_executable(candidate):
            return str(candidate.resolve())
        checked.add(candidate)

    raise ReviewError(
        "Stockfish was not found. Install it once with 'brew install stockfish', "
        "or place the official executable at bin/stockfish, then run main.py again."
    )


def _line_from_engine(info: dict, turn: chess.Color) -> Line:
    """Change one large Stockfish answer into the small Line object we need.

    Stockfish returns a dictionary containing many details. This project keeps
    only its score, win/draw/loss values, and expected future moves.
    """

    # Stockfish scores can be written from either player's view. pov(turn)
    # changes the score to the view of the player whose turn it currently is.
    raw_score = info.get("score")
    score_kind = None
    score_value = 0
    if raw_score is not None:
        score = raw_score.pov(turn) if isinstance(raw_score, chess.engine.PovScore) else raw_score
        if score.is_mate():
            # A positive mate number means this player can force checkmate; a
            # negative number means this player is expected to be checkmated.
            score_kind = "mate"
            score_value = int(score.mate() or 0)
        else:
            # A centipawn is 1/100 of a pawn's rough value. Positive is better
            # for the player whose turn it is; negative is worse.
            score_kind = "cp"
            score_value = int(score.score() or 0)

    # WDL means win/draw/loss. Stockfish normally returns three values totaling
    # 1,000, which are converted into percentages later.
    raw_wdl = info.get("wdl")
    win = draw = loss = None
    if raw_wdl is not None:
        wdl = raw_wdl.pov(turn) if isinstance(raw_wdl, chess.engine.PovWdl) else raw_wdl
        win, draw, loss = int(wdl.wins), int(wdl.draws), int(wdl.losses)

    # pv means principal variation: Stockfish's expected sequence of best moves.
    # Store those moves in UCI form so they stay exact until report time.
    return Line(
        score_kind=score_kind,
        score_value=score_value,
        win=win,
        draw=draw,
        loss=loss,
        moves=[move.uci() for move in info.get("pv", [])],
    )


def _analyze_position(
    engine: chess.engine.SimpleEngine,
    board: chess.Board,
    nodes: int,
) -> PositionAnalysis:
    """Ask Stockfish for the two strongest choices in one board position."""

    # Finished positions have no legal next move, so asking Stockfish to search
    # them would waste work and can cause engine errors.
    if board.is_checkmate() or _is_draw(board):
        return PositionAnalysis([])

    # Limit the search by node count instead of seconds. multipv=2 asks for two
    # ranked choices rather than only the best choice. The second choice helps
    # the program recognize uniquely necessary and forced moves.
    try:
        raw = engine.analyse(
            board,
            chess.engine.Limit(nodes=nodes),
            multipv=2,
            info=chess.engine.INFO_ALL,
        )
    except (chess.engine.EngineError, chess.engine.EngineTerminatedError, TimeoutError) as error:
        raise ReviewError(f"Stockfish analysis failed: {error}") from error

    # python-chess normally returns a list for MultiPV, but wrapping a single
    # answer keeps the remaining code safe with engines that return one item.
    information = raw if isinstance(raw, list) else [raw]

    # multipv=1 is the best choice and multipv=2 is second-best. Sort the answers
    # before converting each large engine dictionary into a small Line.
    information.sort(key=lambda item: int(item.get("multipv", 1)))
    lines = [_line_from_engine(info, board.turn) for info in information]
    if not lines:
        raise ReviewError("Stockfish returned no answer for a position.")
    return PositionAnalysis(lines)


def _fallback_share(line: Line | None, white_to_move: bool) -> float:
    """Estimate White's share when Stockfish did not provide WDL values.

    Modern Stockfish normally supplies WDL, so this is a safety fallback. The
    curved formula changes a centipawn score into a number between 0% and 100%
    without ever going below or above that range.
    """
    if line is None or line.score_kind is None:
        return 50.0

    # A known forced mate gives the player to move 100%, 0%, or 50% when the
    # mate score has no direction. Otherwise use the centipawn formula.
    if line.score_kind == "mate":
        side_share = 100.0 if line.score_value > 0 else 0.0 if line.score_value < 0 else 50.0
    else:
        side_share = 100.0 / (1.0 + math.exp(-line.score_value / 220))

    # The engine score described the player to move. Reverse it when Black was
    # the player to move because this function must always return White's share.
    return side_share if white_to_move else 100.0 - side_share


def _position_chances(board: chess.Board, analysis: PositionAnalysis) -> Chances:
    """Convert one position into exact or engine-estimated percentages."""

    # Checkmate is known with certainty. board.turn is the losing player because
    # that player must move but has no legal way out of check.
    if board.is_checkmate():
        white_won = board.turn == chess.BLACK
        return Chances(
            100.0 if white_won else 0.0,
            0.0,
            0.0 if white_won else 100.0,
            100.0 if white_won else 0.0,
            0.0 if white_won else 100.0,
        )

    # A finished draw gives each player a 50% position share even though neither
    # player has a direct win chance.
    if _is_draw(board):
        return Chances(0.0, 100.0, 0.0, 50.0, 50.0)

    # lines[0] is Stockfish's best line and contains the main WDL forecast.
    line = analysis.lines[0] if analysis.lines else None
    if line and line.win is not None and line.draw is not None and line.loss is not None:
        # Stockfish's values total 1,000, so dividing by 10 creates percentages.
        side_win = line.win / 10.0
        draw = line.draw / 10.0
        side_loss = line.loss / 10.0

        # WDL is from the player-to-move's view. Put it into a consistent
        # White-win and Black-win order for the rest of the program.
        white_win, black_win = (
            (side_win, side_loss) if board.turn == chess.WHITE else (side_loss, side_win)
        )
        return Chances(
            white_win,
            draw,
            black_win,
            # Each player receives half the draw chance in the two headline
            # percentages. The resulting two shares always total 100%.
            white_win + draw / 2.0,
            black_win + draw / 2.0,
        )

    # Use the centipawn fallback only if the engine omitted WDL information.
    white_share = _fallback_share(line, board.turn == chess.WHITE)
    return Chances(white_share, 0.0, 100.0 - white_share, white_share, 100.0 - white_share)


def _line_share(line: Line | None) -> float | None:
    """Return the position share for the player whose turn this line describes."""

    if line is None:
        return None

    # Win chance plus half the draw chance gives the player's share. Stockfish
    # values are divided by 10 because they normally total 1,000.
    if line.win is not None and line.draw is not None:
        return (line.win + line.draw / 2.0) / 10.0
    if line.score_kind == "mate":
        return 100.0 if line.score_value > 0 else 0.0
    if line.score_kind == "cp":
        return 100.0 / (1.0 + math.exp(-line.score_value / 220))
    return None


def _score_in_centipawns(line: Line | None) -> int:
    """Return one numeric score so normal and forced-mate lines can be compared.

    Centipawn lines already contain a normal number. Mate lines are changed into
    very large positive or negative values because checkmate matters more than
    any material gain. A closer mate receives the larger value.
    """
    if line is None or line.score_kind is None:
        return 0
    if line.score_kind == "cp":
        return line.score_value
    # sign becomes 1 for a winning mate, -1 for a losing mate, or 0 when unknown.
    sign = 1 if line.score_value > 0 else -1 if line.score_value < 0 else 0
    return sign * (100_000 - min(99, abs(line.score_value)) * 1_000)


def _review_move(
    move: Move,
    before: PositionAnalysis,
    after: PositionAnalysis,
    before_chances: Chances,
    after_chances: Chances,
) -> MoveReview:
    """Compare one played move with Stockfish and assign one of nine labels.

    The position before the move tells us what the player could have achieved.
    The position after it tells us what the played move actually achieved.
    """

    # Pull out Stockfish's first and second choices. The first UCI move in the
    # best line is the move Stockfish wanted the player to make.
    best_line = before.lines[0] if before.lines else None
    second_line = before.lines[1] if len(before.lines) > 1 else None
    best_uci = best_line.moves[0] if best_line and best_line.moves else None
    played_is_best = best_uci == move.uci

    # Measure the drop in the moving player's position share. max(0, value)
    # prevents small search differences from recording a negative loss.
    best_share = before_chances.white_share if move.color == "w" else before_chances.black_share
    played_share = after_chances.white_share if move.color == "w" else after_chances.black_share
    raw_loss = best_share - played_share
    score_loss = max(0.0, raw_loss)

    # Stockfish's answer after a move is from the opponent's view, so the minus
    # sign changes it back to the original player's view. A delivered checkmate
    # receives the largest possible winning value.
    best_cp = _score_in_centipawns(best_line)
    after_line = after.lines[0] if after.lines else None
    played_cp = 100_000 if move.gives_checkmate else -_score_in_centipawns(after_line)
    cp_loss = max(0.0, best_cp - played_cp)

    # Centipawn differences become less useful once a position is already near
    # 100%-0%. saturation measures how far the best share is from an even 50%.
    # The adjustment reduces exaggerated losses in already-decided positions.
    saturation = min(1.0, abs(best_share - 50.0) / 50.0)
    adjusted_cp_loss = cp_loss * (1.0 - 0.65 * saturation)

    # Use whichever warning is larger: lost share or adjusted engine value.
    quality_loss = max(score_loss, adjusted_cp_loss / 20.0)

    # These checks identify forced choices and missed mating attacks before the
    # normal Best-to-Blunder scale is applied.
    best_line_share = _line_share(best_line)
    second_share = _line_share(second_line)
    only_move = move.legal_move_count == 1

    # A best move is considered uniquely necessary when it is at least 18 share
    # points better than Stockfish's second choice.
    unique_move = bool(
        played_is_best
        and best_line_share is not None
        and second_share is not None
        and best_line_share - second_share >= 18.0
    )
    best_has_mate = bool(
        best_line
        and best_line.score_kind == "mate"
        and best_line.score_value > 0
    )
    kept_mate = move.gives_checkmate or bool(
        after_line
        and after_line.score_kind == "mate"
        and after_line.score_value < 0
    )

    # Order matters: special chess situations are checked first, followed by the
    # normal quality-loss limits from best to worst.
    if only_move or unique_move:
        label = "Forced"
    elif best_has_mate and not kept_mate:
        label = "Missed mate"
    elif (
        (best_share >= 70.0 and played_share < 60.0 and score_loss >= 12.0)
        or (best_cp >= 200 and played_cp < 50 and cp_loss >= 150)
    ):
        label = "Missed win"
    elif played_is_best or quality_loss <= LOSS_LIMITS["best"]:
        label = "Best"
    elif quality_loss <= LOSS_LIMITS["excellent"]:
        label = "Excellent"
    elif quality_loss <= LOSS_LIMITS["good"]:
        label = "Good"
    elif quality_loss <= LOSS_LIMITS["inaccuracy"]:
        label = "Inaccuracy"
    elif quality_loss <= LOSS_LIMITS["mistake"]:
        label = "Mistake"
    else:
        label = "Blunder"

    # The Elo estimate later uses this gap to judge how important the choice was.
    second_best_gap = None
    if best_line_share is not None and second_share is not None:
        second_best_gap = max(0.0, best_line_share - second_share)

    # Store all facts needed by deeper checking, the Elo estimate, and the report.
    return MoveReview(
        move,
        label,
        best_uci,
        played_is_best,
        score_loss,
        cp_loss,
        quality_loss,
        raw_loss,
        second_best_gap,
        after_chances,
        best_line,
    )


def _build_reviews(
    game: Game,
    analyses: list[PositionAnalysis],
) -> list[MoveReview]:
    """Create one MoveReview for every played move in the game."""

    # zip pairs board 0 with analysis 0, board 1 with analysis 1, and so on.
    chances = [
        _position_chances(board, analysis)
        for board, analysis in zip(game.boards, analyses)
    ]
    # A game with N moves has N+1 positions. Move index therefore compares the
    # position at index with the position immediately after it at index + 1.
    return [
        _review_move(
            move,
            analyses[index],
            analyses[index + 1],
            chances[index],
            chances[index + 1],
        )
        for index, move in enumerate(game.moves)
    ]


def _should_recheck(review: MoveReview) -> bool:
    """Return True when a move would benefit from the larger node limit.

    Best moves normally need no second search. Mate lines, large losses, unusual
    search differences, and values near a label border receive another check.
    """
    if review.played_is_best and review.classification != "Forced":
        return False
    if review.best_line and review.best_line.score_kind == "mate":
        return True
    if review.raw_score_loss < -1.0 or review.quality_loss >= 4.0:
        return True
    # any() becomes True if quality_loss is within 0.8 of at least one label
    # boundary. Rechecking reduces labels changing because of shallow searching.
    return any(
        abs(review.quality_loss - limit) <= 0.8
        for limit in LOSS_LIMITS.values()
    )


def _analyze_game(
    game: Game,
    engine: chess.engine.SimpleEngine,
    progress: Callable[[str, int, int], None],
) -> list[MoveReview]:
    """Analyze the whole game, then spend extra work only where it may help.

    The first pass checks every position with BASE_NODES. The second pass uses
    DEEP_NODES on positions connected to uncertain moves. This keeps the result
    careful without making every easy position take the longer search time.
    """

    # There are N+1 positions for N moves: the starting position plus the board
    # after every move. analyses will hold one Stockfish answer for each one.
    analyses: list[PositionAnalysis] = []
    total = len(game.boards)

    # First pass: check every position. start=1 makes the progress message begin
    # at 1/total even though Python list positions normally begin at zero.
    for index, board in enumerate(game.boards, start=1):
        progress("scan", index, total)
        analyses.append(_analyze_position(engine, board, BASE_NODES))

    # Build a temporary set of move reviews so we can find questionable results.
    reviews = _build_reviews(game, analyses)

    # A set stores each number only once. For every questionable move at index,
    # recheck both its position before (index) and after (index + 1).
    targets: set[int] = set()
    for index, review in enumerate(reviews):
        if _should_recheck(review):
            targets.update((index, index + 1))

    # sorted() makes the positions run in game order. Finished positions are
    # removed because there is no legal next move for Stockfish to examine.
    positions_to_recheck = [
        index
        for index in sorted(targets)
        if not game.boards[index].is_checkmate() and not _is_draw(game.boards[index])
    ]

    # Replace each selected first-pass answer with a deeper answer.
    for progress_index, position_index in enumerate(positions_to_recheck, start=1):
        progress("verify", progress_index, len(positions_to_recheck))
        analyses[position_index] = _analyze_position(
            engine,
            game.boards[position_index],
            DEEP_NODES,
        )

    # Rebuild every move review so all labels use the final engine answers.
    return _build_reviews(game, analyses)


def _interpolate(value: float) -> float:
    """Turn an accuracy between table rows into an Elo between those rows.

    For example, an accuracy halfway between 70 and 80 receives an Elo halfway
    between the two matching Elo values. This filling-in process is called
    interpolation.
    """

    # Keep values outside the table at its lowest or highest Elo.
    if value <= ELO_CURVE[0][0]:
        return float(ELO_CURVE[0][1])
    if value >= ELO_CURVE[-1][0]:
        return float(ELO_CURVE[-1][1])

    # Check each neighboring pair of table rows until value fits between them.
    for index in range(1, len(ELO_CURVE)):
        high_accuracy, high_elo = ELO_CURVE[index]
        low_accuracy, low_elo = ELO_CURVE[index - 1]
        if value <= high_accuracy:
            # distance is how far value has traveled from the lower row toward
            # the higher row, written as a number from 0 to 1.
            distance = (value - low_accuracy) / (high_accuracy - low_accuracy)
            return low_elo + distance * (high_elo - low_elo)

    # The earlier checks should always return first; this is a safety result.
    return float(ELO_CURVE[-1][1])


def _estimate_performance(reviews: list[MoveReview], color: str) -> Performance:
    """Make a rough one-game accuracy and Elo estimate for one player.

    This is not the player's real rating. It judges only the useful decisions
    in this game and later prints a wide range to show that uncertainty.
    """

    # Keep this player's non-forced decisions. Quiet opening moves through move
    # 8 are skipped unless the move lost noticeable value or had a clearly
    # better alternative. This stops memorized opening moves dominating Elo.
    informative = [
        review
        for review in reviews
        if review.move.color == color
        and review.classification != "Forced"
        and (
            review.move.move_number > 8
            or review.quality_loss > 2.0
            or (review.second_best_gap or 0.0) >= 3.0
        )
    ]

    # A short game may not contain six such moves. In that case, use all of the
    # player's non-forced moves so an estimate can still be attempted.
    usable = informative if len(informative) >= 6 else [
        review
        for review in reviews
        if review.move.color == color and review.classification != "Forced"
    ]
    if not usable:
        return Performance(None, None, None, None, 0)

    # exp() changes each quality loss into a 0-to-1 score: a tiny loss stays
    # near 1, while a large loss moves toward 0. The average measures strength.
    qualities = [math.exp(-review.quality_loss / 18.0) for review in usable]
    average_quality = sum(qualities) / len(qualities)

    # Squaring makes large errors count much more than small ones. sqrt() then
    # brings the average back to a normal-sized loss. This rewards consistency.
    average_squared_loss = sum(review.quality_loss**2 for review in usable) / len(usable)
    consistency = math.exp(-math.sqrt(average_squared_loss) / 22.0)

    # Use 68% average move quality and 32% consistency for a 0-to-100 score.
    accuracy = 100.0 * (0.68 * average_quality + 0.32 * consistency)

    # Start from the accuracy table, then lower the estimate for the share of
    # severe errors and ordinary mistakes. A rate of 0.10 means 10% of moves.
    severe = {"Blunder", "Missed mate", "Missed win"}
    severe_rate = sum(review.classification in severe for review in usable) / len(usable)
    mistake_rate = sum(review.classification == "Mistake" for review in usable) / len(usable)
    raw_elo = _interpolate(accuracy) - 1_800 * severe_rate - 700 * mistake_rate

    # Keep Elo at least 100 and round it to the nearest 25. Adding 0.5 before
    # floor() makes floor perform normal nearest-number rounding here.
    estimate = math.floor(max(100.0, raw_elo) / 25.0 + 0.5) * 25

    # The printed range is wider for fewer useful moves. It also widens when
    # the average gap was small, because many choices were nearly equal.
    average_gap = sum(min(20.0, review.second_best_gap or 0.0) for review in usable) / len(usable)
    half_range = min(
        700.0,
        max(450.0, 220.0 + 900.0 / math.sqrt(len(usable)) + (100.0 if average_gap < 2 else 0.0)),
    )

    # Round the range to 25 Elo, keep its low end at 100, and cap its high end.
    half_range = math.floor(half_range / 25.0 + 0.5) * 25
    return Performance(
        estimate,
        max(100, estimate - half_range),
        min(3200, estimate + half_range),
        accuracy,
        len(usable),
    )


def _uci_line_to_san(fen: str, uci_moves: list[str], limit: int = 6) -> list[str]:
    """Change up to six engine moves from UCI text into readable SAN text.

    UCI writes exact squares, such as g1f3. SAN is the familiar chess form Nf3.
    The moves must be replayed from the saved FEN board because SAN depends on
    the position: the same piece move can need different text on another board.
    """
    board = chess.Board(fen)
    san_moves = []

    # [:limit] means only the first limit items. Stop safely if an engine line
    # contains text that cannot be read or a move that is illegal on this board.
    for uci in uci_moves[:limit]:
        try:
            move = chess.Move.from_uci(uci)
            if move not in board.legal_moves:
                break
            san_moves.append(board.san(move))
            board.push(move)
        except (ValueError, AssertionError):
            break
    return san_moves


def _rounded_shares(chances: Chances) -> tuple[float, float]:
    """Round both player shares to one decimal while keeping their total 100."""

    # Round White normally, then calculate Black from White. Rounding both on
    # their own could occasionally display a total such as 99.9% or 100.1%.
    white = math.floor(chances.white_share * 10 + 0.5) / 10
    black = math.floor((100.0 - white) * 10 + 0.5) / 10
    return white, black


def _performance_text(name: str, performance: Performance, reported: str | None) -> str:
    """Build the two printed lines for one player's performance estimate."""

    # None means there were no non-forced decisions to judge.
    if performance.estimate is None:
        return f"{name}: not enough informative moves for an estimate"

    # Show the rating recorded in the PGN only when that header existed.
    reported_text = f" | PGN rating: {reported}" if reported else ""

    # Adjacent f-strings inside parentheses join into one string. \n starts the
    # second output line, and :.1f prints accuracy with one decimal place.
    return (
        f"{name}: about {performance.estimate} Elo "
        f"(plausible range {performance.low}–{performance.high}){reported_text}\n"
        f"  Game accuracy: {performance.accuracy:.1f}/100 | "
        f"informative moves: {performance.moves} | confidence: low"
    )


def _render_report(result: ReviewResult) -> str:
    """Turn all calculated results into the final human-readable report."""

    # Read names and ratings from the PGN. The text after or supplies a safe
    # name if a header exists but is empty; get() supplies a value if it is absent.
    game = result.game
    white_name = game.headers.get("White") or "White"
    black_name = game.headers.get("Black") or "Black"
    white_rating = game.headers.get("WhiteElo", "Unrated")
    black_rating = game.headers.get("BlackElo", "Unrated")

    # This dictionary changes standard PGN result codes into readable text.
    # dictionary.get(key, fallback) uses the fallback for an unknown result.
    result_text = {
        "1-0": "White won",
        "0-1": "Black won",
        "1/2-1/2": "Draw",
    }.get(game.result, "Unfinished or unknown")

    # Build the report as a list of lines. Joining once at the end is simpler
    # and faster than repeatedly adding text to one very large string.
    lines = [
        "═" * 92,
        "CHESS GAME REVIEW — SIMPLIFIED PYTHON",
        "═" * 92,
        f"{white_name} (White - {white_rating}) vs {black_name} (Black - {black_rating})",
        f"{result_text} | {len(game.moves)} half-moves | fixed Balanced analysis",
        "",
        "Position share splits draws equally, so the two player percentages total 100%.",
        "W/D/L means White-win / Draw / Black-win chance.",
        "─" * 92,
    ]

    # Add one main result line, optional detail line, and blank line per move.
    for review in result.reviews:
        move = review.move
        chances = review.after_chances
        white_share, black_share = _rounded_shares(chances)

        # White is printed as " 1." and Black as " 1...". :>2 right-aligns the
        # move number in two spaces. ljust() pads columns so they line up.
        prefix = f"{move.move_number:>2}." if move.color == "w" else f"{move.move_number:>2}..."
        move_text = f"{prefix} {move.san}".ljust(12)
        label = review.classification.ljust(12)

        # :.1f displays one digit after the decimal point.
        wdl = f"W/D/L {chances.white_win:.1f}/{chances.draw:.1f}/{chances.black_win:.1f}"
        lines.append(
            f"{move_text} {label} {white_name} {white_share:.1f}% | "
            f"{black_name} {black_share:.1f}%  ({wdl})"
        )

        # Convert Stockfish's exact-square best line into readable move names.
        principal_variation = []
        if review.best_line:
            principal_variation = _uci_line_to_san(
                move.before_fen,
                review.best_line.moves,
            )
        best_line_text = " ".join(principal_variation)

        # Explain a non-best move only when a useful best line is available.
        # The centipawn loss is rounded to a whole number for easier reading.
        if not review.played_is_best and review.best_uci and best_line_text:
            cp_loss = math.floor(review.centipawn_loss + 0.5)
            lines.append(
                f"             ↳ {review.score_loss:.1f} share points / "
                f"{cp_loss} cp lost; best line: {best_line_text}"
            )

        # A forced move gets an explanation even though it did not lose value.
        elif review.classification == "Forced":
            lines.append(
                f"             ↳ forced or uniquely necessary; "
                f"line: {best_line_text or move.san}"
            )
        lines.append("")

    # Add the final estimates and the warning that one game is weak evidence.
    lines.extend(
        [
            "─" * 92,
            "SINGLE-GAME PERFORMANCE ESTIMATE",
            _performance_text(
                white_name,
                result.white_performance,
                game.headers.get("WhiteElo"),
            ),
            _performance_text(
                black_name,
                result.black_performance,
                game.headers.get("BlackElo"),
            ),
            "",
            "Important: one game cannot determine a true rating. This is a low-confidence",
            "engine-based estimate with a deliberately wide range.",
            "═" * 92,
        ]
    )

    # Join every saved report line using a new-line character between them.
    return "\n".join(lines)


def review_pgn(
    pgn: str,
    progress: Callable[[str, int, int], None] | None = None,
) -> str:
    """Run the complete review. This is the function called by main.py.

    progress is optional. When main.py supplies show_progress(), this function
    reports which position is being checked. A caller can omit it when no live
    progress display is wanted.
    """

    # First validate the user's text and rebuild all moves and board positions.
    game = _parse_pgn(pgn)

    # Find the separate Stockfish program before attempting to start it.
    engine_path = _find_stockfish()

    # lambda creates a tiny unnamed function. This one does nothing, allowing
    # the same analysis code to call progress even when none was supplied.
    report_progress = progress or (lambda _stage, _current, _total: None)

    # UCI is the message format chess programs use to control engines. This
    # starts Stockfish and allows up to 180 seconds for startup communication.
    try:
        engine = chess.engine.SimpleEngine.popen_uci(engine_path, timeout=180.0)
    except (OSError, chess.engine.EngineError, TimeoutError) as error:
        raise ReviewError(f"Stockfish could not start: {error}") from error

    try:
        # Hash gives Stockfish 64 MB for remembered positions. One thread makes
        # runs more consistent. UCI_ShowWDL requests win/draw/loss forecasts.
        wanted = {"Hash": 64, "Threads": 1, "UCI_ShowWDL": True}

        # Different engines support different settings, so send only settings
        # that this engine says it understands.
        supported = {name: value for name, value in wanted.items() if name in engine.options}
        if supported:
            engine.configure(supported)
        reviews = _analyze_game(game, engine, report_progress)

    # finally always runs, even after an error, so Stockfish is not left open.
    finally:
        try:
            # quit() requests a normal shutdown.
            engine.quit()
        except (chess.engine.EngineError, chess.engine.EngineTerminatedError, OSError):
            # close() force-closes the connection if normal shutdown failed or
            # Stockfish had already stopped by itself.
            engine.close()

    # Estimate both players from their reviewed moves, then create the report.
    result = ReviewResult(
        game,
        reviews,
        _estimate_performance(reviews, "w"),
        _estimate_performance(reviews, "b"),
    )
    return _render_report(result)
