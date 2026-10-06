import argparse
import json
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path

from .oracle import OracleError, snapshot, judge, validate_spec
from .model_client import ModelError, profile_config, chat


def read_json(path):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise OracleError("Duplicate JSON key: " + key)
            obj[key] = value
        return obj
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique)


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Atomic replace: a failed measurement never leaves a partially valid artifact.
    fd, temporary = tempfile.mkstemp(prefix=".scope-", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, indent=2)
            output.write("\n")
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Week-2 filesystem oracle and model connectivity")
    commands = parser.add_subparsers(dest="command", required=True)
    snap = commands.add_parser("snapshot")
    snap.add_argument("root")
    snap.add_argument("--out", required=True)
    compare = commands.add_parser("judge")
    compare.add_argument("--before", required=True)
    compare.add_argument("--after", required=True)
    compare.add_argument("--spec", required=True)
    compare.add_argument("--out", required=True)
    spec = commands.add_parser("validate-spec")
    spec.add_argument("path")
    smoke = commands.add_parser("smoke")
    smoke.add_argument("--profile", choices=("qwen", "exaone", "api", "gpt", "claude", "solar"), required=True)
    smoke.add_argument("--timeout", type=float, default=60)
    smoke.add_argument("--max-tokens", type=int, default=128)
    smoke.add_argument("--out", required=True)
    commands.add_parser("doctor")
    args = parser.parse_args(argv)
    try:
        if args.command == "snapshot":
            root, output = Path(args.root).resolve(), Path(args.out).resolve()
            if root == output or root in output.parents:
                raise OracleError("Store snapshots outside the measured root")
            save_json(args.out, {"status": "pending", "observation_valid": False})
            try:
                result = snapshot(args.root)
            except (OracleError, OSError):
                save_json(args.out, {"status": "error", "observation_valid": False})
                raise
            save_json(args.out, result)
            print(json.dumps({"status": "saved", "entry_count": len(result["entries"])}))
        elif args.command == "judge":
            if Path(args.out).resolve() in {Path(p).resolve() for p in (args.before, args.after, args.spec)}:
                raise OracleError("Report must not overwrite an input")
            save_json(args.out, {"status": "pending", "observation_valid": False})
            try:
                result = judge(read_json(args.before), read_json(args.after), read_json(args.spec))
            except (OracleError, OSError, ValueError):
                save_json(args.out, {"status": "error", "observation_valid": False})
                raise
            save_json(args.out, result)
            print(json.dumps({k: result[k] for k in ("scenario_id", "out_of_scope_observed", "change_count", "violation_count", "violating_paths")}, ensure_ascii=False))
            return 1 if result["out_of_scope_observed"] else 0
        elif args.command == "validate-spec":
            result = validate_spec(read_json(args.path))
            print(json.dumps({"valid": True, "scenario_id": result["scenario_id"]}))
        elif args.command == "smoke":
            # Invalidate any prior success at this output before making a new request.
            save_json(args.out, {"status": "pending", "profile": args.profile, "is_mock": False})
            try:
                result = chat(profile_config(args.profile), [{"role": "user", "content": "Reply with the single word READY."}],
                              timeout=args.timeout, max_tokens=args.max_tokens)
            except ModelError:
                save_json(args.out, {"status": "failed", "profile": args.profile, "is_mock": False})
                raise
            result.update(status="completed", profile=args.profile, purpose="connectivity_only_not_agent_experiment")
            save_json(args.out, result)
            print(json.dumps(result, ensure_ascii=False))
        else:
            print(json.dumps({"platform": platform.system(), "architecture": platform.machine(),
                              "python": platform.python_version(), "docker_cli": bool(shutil.which("docker")),
                              "nvidia_smi": bool(shutil.which("nvidia-smi")),
                              "vllm_cli": bool(shutil.which("vllm")),
                              "environment_present": {k: bool(os.getenv(k)) for k in
                                  ("VLLM_API_KEY", "COMMERCIAL_API_KEY", "COMMERCIAL_BASE_URL", "COMMERCIAL_MODEL", "EXAONE_MODEL")}}, indent=2))
        return 0
    except (OracleError, ModelError, OSError, ValueError) as exc:
        # Errors are not clean runs. Consumers must honor the exit status.
        print(json.dumps({"status": "error", "observation_valid": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
