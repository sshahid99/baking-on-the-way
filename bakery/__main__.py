"""python -m bakery <command> ...   (run with no command for help)"""
import argparse

from . import config


def main():
    ap = argparse.ArgumentParser(prog="python -m bakery", description="Baking on the way: morning run planner")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("generate", help="(re)create the fictional customers and 60 order sheets, seed 4336")
    r = sub.add_parser("roads", help="build the drive-time matrix from OpenStreetMap (fallback: straight line x1.3)")
    r.add_argument("--fallback", action="store_true")
    sub.add_parser("prices", help="fetch BLS flour/egg/butter prices (public API, no key)")
    sub.add_parser("setup", help="load customers and prices into the database")
    c = sub.add_parser("clean", help="step 1: clean and check one order sheet")
    c.add_argument("order_file")
    lg = sub.add_parser("ingest-log", help="learn drive times from a van delivery log")
    lg.add_argument("log_file")
    p = sub.add_parser("plan", help="step 2: optimise tomorrow's run (needs clean first)")
    p.add_argument("date")
    sub.add_parser("export", help="step 4a: write docs/data/*.json for the dashboard from the database")
    a = sub.add_parser("approve", help="record Rosa's approval of a plan")
    a.add_argument("date")
    d = sub.add_parser("drive", help="simulate the morning for an approved plan and write the van log")
    d.add_argument("date")
    b = sub.add_parser("backfill", help="run every night up to a date (history for the trends)")
    b.add_argument("--until", default=None)
    args = ap.parse_args()

    if args.cmd == "generate":
        from . import generate
        generate.main()
    elif args.cmd == "roads":
        from . import geo
        geo.build_matrix(force_fallback=args.fallback)
    elif args.cmd == "prices":
        from . import prices
        prices.fetch()
    else:
        from . import pipeline
        if args.cmd == "setup":
            pipeline.setup()
        elif args.cmd == "clean":
            pipeline.clean_step(args.order_file)
        elif args.cmd == "ingest-log":
            pipeline.ingest_log(args.log_file)
        elif args.cmd == "plan":
            pipeline.plan_day(args.date)
        elif args.cmd == "export":
            from . import export
            export.main()
        elif args.cmd == "approve":
            from . import db
            mins = db.mark_approved_by_rosa(args.date)
            took = f" ({mins:.1f} min from cleaning the order sheet to your approval)" if mins is not None else ""
            print(f"Plan for {args.date} marked approved by Rosa{took}")
        elif args.cmd == "drive":
            pipeline.drive_morning(args.date)
        elif args.cmd == "backfill":
            pipeline.backfill(args.until)


if __name__ == "__main__":
    main()
