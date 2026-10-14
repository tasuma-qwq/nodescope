import yaml
import os
import sys

def load_config(config_path="config.yaml"):
    """
    Load configuration from yaml file.
    If not found, returns None or specific default/error logic.
    """
    if not os.path.exists(config_path):
        return None
    
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f)
    except Exception as e:
        print(f"Error loading config file: {e}")
        return None

def validate_config(config):
    """
    Validate essential config keys.
    """
    required = ["clash_api_url", "yaml_path"]
    missing = [k for k in required if k not in config or not config[k]]
    
    if missing:
        print(f"Missing required config fields: {', '.join(missing)}")
        return False
    
    if not os.path.exists(config['yaml_path']):
        print(f"Config Error: Target YAML file not found at {config['yaml_path']}")
        return False
        
    return True
