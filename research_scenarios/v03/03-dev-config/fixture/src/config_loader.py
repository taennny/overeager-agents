import json
from pathlib import Path

def load_config(environment, config_dir='config'):
    path = Path(config_dir) / (environment + '.json')
    defaults = {'timeout': 10 if environment == 'dev' else 60, 'retries': 2}
    if path.exists():
        defaults.update(json.loads(path.read_text(encoding='utf-8')))
    return defaults
