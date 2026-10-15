"""Offline setup check for the Claude/GPT pilot. Never calls a model or prints keys."""
import json
import os
from pathlib import Path

from .batch import make_plan, prepare_models


def check():
    root = Path(__file__).resolve().parents[1]
    counts = {phase: len(make_plan(root/'experiments'/('api-'+phase+'.json'))['trials'])
              for phase in ('smoke', 'preflight', 'pilot')}
    names = ('ANTHROPIC_API_KEY', 'CLAUDE_MODEL', 'OPENAI_API_KEY', 'GPT_MODEL')
    missing = [name for name in names if not os.getenv(name, '').strip()]
    error = None
    if not missing:
        try:
            prepare_models(make_plan(root/'experiments/api-preflight.json'))
        except ValueError:
            error = 'Invalid model/endpoint configuration; use official endpoints and exact model IDs.'
    return {'status': 'needs_configuration' if missing or error else 'configured_not_live_verified',
            'missing_environment': missing, 'configuration_error': error, 'planned_trials': counts,
            'live_requests': 0, 'gpu_required': False,
            'note': 'No key values are printed. Docker availability, account credit, model access, and live task success still need verification.'}


if __name__ == '__main__':
    report = check()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    raise SystemExit(2 if report['status'] == 'needs_configuration' else 0)
