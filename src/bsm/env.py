import json
import os
from typing import Any, Dict, List, Optional


_ENV_LOADED = False
_ENV_LOADED_PATH = ""
_INITIAL_PROJECT_CONFIG_ENSURED = False


def project_root() -> str:
    return os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir, os.pardir))


def data_dir() -> str:
    path = os.path.join(project_root(), "src", "data")
    os.makedirs(path, exist_ok=True)
    return path


def dotenv_path() -> str:
    override = os.environ.get("BSM_ENV_PATH", "").strip()
    if override:
        return resolve_project_path(override)
    return os.path.join(project_root(), ".env")


def ensure_initial_project_config() -> None:
    global _INITIAL_PROJECT_CONFIG_ENSURED
    if _INITIAL_PROJECT_CONFIG_ENSURED:
        return

    if os.environ.get("BSM_TESTING") == "1":
        _INITIAL_PROJECT_CONFIG_ENSURED = True
        return

    if os.environ.get("BSM_ENV_PATH", "").strip() or os.environ.get("BSM_CONFIG_PATH", "").strip():
        _INITIAL_PROJECT_CONFIG_ENSURED = True
        return

    root = project_root()
    env_path = os.path.join(root, ".env")
    config_path = os.path.join(root, "config.yaml")
    legacy_config_path = os.path.join(data_dir(), "config.yaml")

    if os.path.exists(env_path) or os.path.exists(config_path) or os.path.exists(legacy_config_path):
        _INITIAL_PROJECT_CONFIG_ENSURED = True
        return

    env_example_path = os.path.join(root, ".env.example")
    config_example_path = os.path.join(root, "config.yaml.example")
    if not os.path.exists(env_example_path) or not os.path.exists(config_example_path):
        _INITIAL_PROJECT_CONFIG_ENSURED = True
        return

    try:
        with open(env_example_path, "r", encoding="utf-8") as f:
            env_content = f.read()
        with open(config_example_path, "r", encoding="utf-8") as f:
            config_content = f.read()
        with open(env_path, "w", encoding="utf-8") as f:
            f.write(env_content)
        with open(config_path, "w", encoding="utf-8") as f:
            f.write(config_content)
    except Exception:
        pass

    _INITIAL_PROJECT_CONFIG_ENSURED = True


def load_dotenv() -> None:
    global _ENV_LOADED, _ENV_LOADED_PATH
    ensure_initial_project_config()
    path = dotenv_path()
    if _ENV_LOADED and _ENV_LOADED_PATH == path:
        return
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                for raw in f:
                    line = raw.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    if not key or key in os.environ:
                        continue
                    os.environ[key] = value.strip().strip("'").strip('"')
        except Exception:
            pass
    _ENV_LOADED = True
    _ENV_LOADED_PATH = path


def resolve_project_path(path: str) -> str:
    if not path:
        return path
    if os.path.isabs(path):
        return path
    return os.path.abspath(os.path.join(project_root(), path))


def env_str(name: str, default: str = "") -> str:
    load_dotenv()
    return str(os.environ.get(name, default))


def env_int(name: str, default: int) -> int:
    load_dotenv()
    try:
        return int(os.environ.get(name, str(default)))
    except Exception:
        return default


def env_bool(name: str, default: bool = False) -> bool:
    load_dotenv()
    value = str(os.environ.get(name, "1" if default else "0")).strip().lower()
    return value in ("1", "true", "yes", "on")


def env_list(name: str, default: Optional[List[str]] = None) -> List[str]:
    load_dotenv()
    raw = str(os.environ.get(name, "")).strip()
    if not raw:
        return list(default or [])
    return [part.strip() for part in raw.split(",") if part.strip()]


def load_json_file(path: str) -> Dict[str, Any]:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    return data


def set_env_value(name: str, value: str) -> None:
    load_dotenv()
    path = dotenv_path()
    lines: List[str] = []
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                lines = f.readlines()
        except Exception:
            lines = []

    updated = False
    new_lines: List[str] = []
    for raw in lines:
        stripped = raw.strip()
        if stripped.startswith(f"{name}="):
            new_lines.append(f"{name}={value}\n")
            updated = True
        else:
            new_lines.append(raw)
    if not updated:
        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] = new_lines[-1] + "\n"
        new_lines.append(f"{name}={value}\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    os.environ[name] = value


def set_env_list(name: str, values: List[str]) -> None:
    set_env_value(name, ",".join([str(item).strip() for item in values if str(item).strip()]))
