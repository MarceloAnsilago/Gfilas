from pathlib import Path

from print_agent_client import PrintAgentConfig, PrintAgentConfigError, run_agent_loop


def main() -> int:
    try:
        config = PrintAgentConfig.from_env(Path(__file__).resolve().parent / ".env")
    except PrintAgentConfigError as exc:
        print(str(exc))
        return 1
    return run_agent_loop(config)


if __name__ == "__main__":
    raise SystemExit(main())
