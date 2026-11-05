import sys

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--self-test":
        from financial_lens.selftest import run

        sys.exit(run(sys.argv[2] if len(sys.argv) > 2 else None))
    if "--window" in sys.argv:  # the previous Qt window, kept while the web interface settles in
        from financial_lens.desktop.main import main

        sys.exit(main())
    from financial_lens.launcher import main

    sys.exit(main())
