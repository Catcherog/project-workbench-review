"""One R5 probe client. No dispatcher, business consumer, training or MLX entry."""
import os
import sys

from .core import read_json, resolve_ref


def main():
    if len(sys.argv) != 3 or sys.argv[1] != "q8":
        raise SystemExit("Only a pinned original q8 probe client is supported")
    os.umask(0o077)
    config = read_json(sys.argv[2])
    from .providers import _roots
    arm = config["arm"]
    _roots(arm)
    from am_style_r5.runners import run_original_qwen
    runtime = arm["runtime"]
    plan = read_json(resolve_ref(runtime["r5_plan"], "r5_plan"))
    queue = read_json(resolve_ref(runtime["queue_config"], "queue_config"))
    run_original_qwen(plan, queue, config["output"], selected=config["case_ids"], execute=True)


if __name__ == "__main__":
    main()
