"""Automatic checks for the most important parts of chess_review.py.

This file does not run when a player starts main.py. It is run separately after
code changes to catch broken PGN reading, percentages, move labels, reports, or
performance estimates. Most tests use small pretend Stockfish answers so they
finish quickly without starting the real Stockfish program.
"""

# unittest is Python's built-in tool for organizing and running automatic tests.
import unittest

# chess supplies real boards and chess rules for the test positions.
import chess

# Import only the settings, data containers, and functions being checked.
# Names beginning with _ are normally internal helpers, but tests call them
# directly so a problem can be traced to one small part of the program.
from chess_review import (
    BASE_NODES,
    DEEP_NODES,
    Chances,
    Game,
    Line,
    Move,
    Performance,
    PositionAnalysis,
    ReviewError,
    ReviewResult,
    _estimate_performance,
    _parse_pgn,
    _position_chances,
    _render_report,
    _review_move,
)


def move(**changes):
    """Create a normal sample move, with optional changes for a specific test.

    **changes collects named values such as legal_move_count=1 into a dictionary.
    This lets a test change only the detail it cares about instead of rebuilding
    the entire Move object every time.
    """

    # These are safe starting values for a normal White move, e4.
    values = {
        "move_number": 1,
        "color": "w",
        "san": "e4",
        "uci": "e2e4",
        "legal_move_count": 20,
        "before_fen": chess.STARTING_FEN,
        "gives_checkmate": False,
    }

    # update() replaces any starting values supplied through **changes.
    values.update(changes)

    # **values sends each dictionary item into the matching Move field.
    return Move(**values)


def line(uci, win, draw, loss, score_kind="cp", score_value=20):
    """Create one small pretend Stockfish line for a test."""

    # [uci] places the chosen move inside the move list expected by Line.
    return Line(score_kind, score_value, win, draw, loss, [uci])


def analysis(uci, win, draw, loss, score_kind="cp", score_value=20, second=None):
    """Create a pretend position analysis with one or two engine choices."""

    # The first line is Stockfish's best choice.
    lines = [line(uci, win, draw, loss, score_kind, score_value)]

    # Some checks need a second-best choice to measure the gap between moves.
    if second is not None:
        lines.append(second)
    return PositionAnalysis(lines)


def chances(white_share):
    """Create simple chances where White and Black always total 100%."""
    return Chances(white_share, 0, 100 - white_share, white_share, 100 - white_share)


# A TestCase groups related checks. Every method beginning with test_ is found
# and run automatically by unittest.
class ParsingTests(unittest.TestCase):
    def test_parses_headers_moves_promotion_and_checkmate(self):
        """Check that PGN headers, moves, boards, and checkmate are rebuilt."""

        # Adjacent quoted strings inside parentheses join into one string. \n
        # means a new line, preserving the normal multi-line PGN format.
        pgn = (
            '[White "Alice"]\n[Black "Bob"]\n[WhiteElo "900"]\n'
            '[BlackElo "850"]\n[Result "1-0"]\n\n'
            'e4 f6 2. e5 g5 3. Qh5# 1-0'
        )
        game = _parse_pgn(pgn)

        # assertEqual fails the test unless both values are equal.
        self.assertEqual(game.headers["White"], "Alice")
        self.assertEqual(len(game.moves), 5)

        # Five moves create six boards: the starting board plus one after each move.
        self.assertEqual(len(game.boards), 6)

        # assertTrue fails unless the supplied value is True.
        self.assertTrue(game.moves[-1].gives_checkmate)

        # [-1] means the final item in a list.
        self.assertEqual(game.moves[-1].san, "Qh5#")

    def test_rejects_empty_pgn(self):
        """Check that blank input becomes a readable ReviewError."""

        # assertRaises passes only if the indented code produces ReviewError.
        with self.assertRaises(ReviewError):
            _parse_pgn("  ")

    def test_preserves_repetition_history(self):
        """Check that saved boards remember enough history to detect repetition."""
        game = _parse_pgn(
            '[Result "1/2-1/2"]\n\n'
            '1. Nf3 Nf6 2. Ng1 Ng8 3. Nf3 Nf6 4. Ng1 Ng8 1/2-1/2'
        )

        # The final board should recognize that this position occurred 3 times.
        self.assertTrue(game.boards[-1].is_repetition(3))


class PercentageAndLabelTests(unittest.TestCase):
    def test_checkmate_has_exact_percentages(self):
        """Check that a known checkmate uses exact values instead of an estimate."""

        # FEN is one line of text describing a complete board position. Here it
        # describes Black to move while checkmated by White.
        board = chess.Board("7k/6Q1/6K1/8/8/8/8/8 b - - 0 1")
        result = _position_chances(board, PositionAnalysis([]))

        # White must receive 100% win/share, with 0% draw and Black win/share.
        self.assertEqual(result, Chances(100, 0, 0, 100, 0))

    def test_all_normal_quality_bands(self):
        """Check every normal label from Best through Blunder."""

        # Each pair is: White's share after the move, then the expected label.
        cases = [
            (50, "Best"),
            (49, "Excellent"),
            (47, "Good"),
            (43, "Inaccuracy"),
            (35, "Mistake"),
            (20, "Blunder"),
        ]

        # Run the same check for every pair. subTest reports which particular
        # label failed instead of treating the whole loop as one unclear failure.
        for after_share, expected in cases:
            with self.subTest(expected=expected):
                review = _review_move(
                    # The played move is e4, while the pretend best move is d4.
                    move(),
                    analysis("d2d4", 250, 500, 250, "cp", 0),
                    analysis("e7e5", 250, 500, 250, "cp", 0),
                    chances(50),
                    chances(after_share),
                )
                self.assertEqual(review.classification, expected)

    def test_forced_missed_mate_and_missed_win(self):
        """Check the three important labels outside the normal quality scale."""

        # legal_move_count=1 means the player had exactly one legal move.
        forced = _review_move(
            move(legal_move_count=1),
            analysis("e2e4", 300, 500, 200),
            analysis("e7e5", 220, 500, 280),
            chances(55),
            chances(54),
        )

        # Stockfish sees mate in 2 with h5h7, but the player chooses d4 and loses it.
        missed_mate = _review_move(
            move(uci="d2d4", san="d4"),
            analysis("h5h7", 1000, 0, 0, "mate", 2),
            analysis("e7e5", 500, 0, 500),
            chances(100),
            chances(50),
        )

        # White could keep an 80% share but falls to 50%, which loses a clear win.
        missed_win = _review_move(
            move(),
            analysis("d2d4", 650, 300, 50, "cp", 300),
            analysis("e7e5", 250, 500, 250, "cp", 0),
            chances(80),
            chances(50),
        )
        self.assertEqual(forced.classification, "Forced")
        self.assertEqual(missed_mate.classification, "Missed mate")
        self.assertEqual(missed_win.classification, "Missed win")

    def test_fixed_quality_settings_match_balanced_mode(self):
        """Protect the fixed search amounts used by the simplified version."""
        self.assertEqual(BASE_NODES, 30_000)
        self.assertEqual(DEEP_NODES, 150_000)


class ReportAndPerformanceTests(unittest.TestCase):
    def test_report_labels_players_and_separates_moves(self):
        """Check the player heading and blank line between printed moves."""

        # Build a tiny pretend game containing White's e4 and Black's e6.
        game = Game(
            {"White": "Alice", "Black": "Bob", "WhiteElo": "900", "BlackElo": "850"},
            [move(), move(move_number=1, color="b", san="e6", uci="e7e6")],
            [chess.Board(), chess.Board(), chess.Board()],
            "1-0",
        )

        # Create a review for each of the two moves without starting Stockfish.
        first = _review_move(
            game.moves[0],
            analysis("e2e4", 300, 500, 200),
            analysis("e7e5", 300, 500, 200),
            chances(55),
            chances(55),
        )
        second = _review_move(
            game.moves[1],
            analysis("e7e6", 300, 500, 200),
            analysis("e2e4", 300, 500, 200),
            chances(55),
            chances(55),
        )

        # No Elo estimate is needed for this formatting test.
        unavailable = Performance(None, None, None, None, 0)
        report = _render_report(ReviewResult(game, [first, second], unavailable, unavailable))

        # assertIn checks that this exact player heading appears somewhere.
        self.assertIn("Alice (White - 900) vs Bob (Black - 850)", report)

        # assertRegex checks a text pattern. .* allows any text on the move line,
        # while \n\n requires the blank line requested between moves.
        self.assertRegex(report, r" 1\. e4 .*\n\n 1\.\.\. e6 ")

    def test_performance_has_a_wide_range(self):
        """Check that one-game Elo is an estimate with a lower and upper range."""
        reviews = []

        # Create 20 similar non-opening decisions so there is enough information
        # for the performance formula to produce an estimate.
        for index in range(20):
            reviewed = _review_move(
                move(move_number=index + 9),
                analysis(
                    "d2d4",
                    300,
                    500,
                    200,
                    second=line("e2e4", 250, 500, 250),
                ),
                analysis("e7e5", 250, 500, 250),
                chances(55),
                chances(52),
            )
            reviews.append(reviewed)
        estimate = _estimate_performance(reviews, "w")

        # assertIsNotNone confirms that an estimate was produced. assertLess and
        # assertGreater confirm that it sits inside a deliberately wide range.
        self.assertIsNotNone(estimate.estimate)
        self.assertLess(estimate.low, estimate.estimate)
        self.assertGreater(estimate.high, estimate.estimate)


# When this file is run directly, ask unittest to find and run every test_ method.
# Importing the file from somewhere else will not start the tests automatically.
if __name__ == "__main__":
    unittest.main()
