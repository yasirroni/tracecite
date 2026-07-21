from tracecite.cli import main


if __name__ == "__main__":
    raise SystemExit(main(["docs", "build", "docs", "--only", "python"]))
