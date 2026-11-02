"""Analyse an approved conversation CSV using the existing redacted analysis layer."""
import argparse
from pathlib import Path
import pandas as pd
from conversation_insights import analyse_csv


def main(argv=None):
    parser = argparse.ArgumentParser(description="Analyse an approved conversation CSV through Groq")
    parser.add_argument("--input", required=True, help="Approved CSV containing conversation text")
    parser.add_argument("--output", required=True)
    parser.add_argument("--text-column", default="conversation_text")
    parser.add_argument("--id-column")
    args = parser.parse_args(argv)
    frame = pd.read_csv(args.input, dtype={args.id_column: str} if args.id_column else None)
    result = analyse_csv(frame, text_column=args.text_column, id_column=args.id_column)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(output, index=False)


if __name__ == "__main__":
    main()
