import argparse
import json

from pipeline.engine import STAGES, run_stage


def main() -> None:
    parser = argparse.ArgumentParser(description="Data cleaning pipeline")
    parser.add_argument("course_id", help="Course id e.g. AI_INTRO")
    parser.add_argument("--stage", choices=STAGES, default="export")
    parser.add_argument("--config", default=None)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()

    result = run_stage(args.course_id, args.stage, config_path=args.config, root_dir=args.root)
    print(json.dumps(result.__dict__, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
