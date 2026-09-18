"""The user-facing start file: receive one PGN and print its review."""

# ReviewError represents a readable review problem. review_pgn() performs all
# chess work and gives this file the finished report as text.
from chess_review import ReviewError, review_pgn


def read_pgn() -> str:
    """Collect every pasted PGN line and return them as one piece of text.

    PGN means Portable Game Notation: the normal text format for a chess game.
    Because a PGN has many lines, END on its own line tells this loop when the
    paste is finished. END is a marker for this program, not part of the PGN.
    """
    print("Paste the complete PGN below.")
    print("When finished, type END on a new line and press Enter.\n")

    # Save each entered line so the original multi-line PGN can be rebuilt.
    lines = []
    while True:
        try:
            line = input()
        # EOF means the editor closed its input. Treat that like the end of the
        # paste instead of showing a Python error.
        except EOFError:
            break

        # strip() removes surrounding spaces before checking for the END marker.
        if line.strip() == "END":
            break
        lines.append(line)

    # Join the saved lines with new-line characters to rebuild the complete PGN.
    return "\n".join(lines)


def show_progress(stage: str, current: int, total: int) -> None:
    """Show which board position Stockfish is currently checking.

    chess_review.py calls this function during both its first scan and its more
    careful rechecks.
    """
    label = "Analyzing" if stage == "scan" else "Deep-checking"

    # \r moves back to the start of the same terminal line. ljust(55) adds
    # spaces to erase an older, longer message. end="" avoids a new line, and
    # flush=True displays the update immediately.
    print(f"\r{label} position {current}/{total}...".ljust(55), end="", flush=True)


def main() -> None:
    """Run the complete user flow from pasted PGN to printed review."""

    # The PGN is the program's only user-controlled setting.
    pgn = read_pgn()
    if not pgn.strip():
        print("\nNo PGN was provided.")
        return

    # Keep expected problems inside a short readable message instead of showing
    # a long Python error report to the user.
    try:
        print("\nStarting Stockfish...")

        # Pass the PGN and the progress function into the review code. The call
        # waits here until the full report has been created.
        report = review_pgn(pgn, show_progress)
        print("\rAnalysis complete.".ljust(55))
        print()
        print(report)

    # These problem types cover invalid PGNs, missing Stockfish, engine errors,
    # file-system problems, and invalid values returned during the review.
    except (ReviewError, RuntimeError, OSError, ValueError) as error:
        print(f"\nReview failed: {error}")


# Python gives this file the name "__main__" when an editor runs it directly.
# This check starts main(), but prevents an accidental run if another file ever
# imports main.py only to reuse one of its functions.
if __name__ == "__main__":
    main()
