import argparse
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    source = (args.root / "tools" / "h1_readonly_collector.cpp").read_text(encoding="utf-8")
    for token in ("motor_on(", "motor_off(", "stop(", "set_position(", "set_zero_ram(", "clear_error(", "release_brake(", "engage_brake("):
        assert token not in source, f"forbidden control call present: {token}"
    for token in ("read_position(", "read_status(", "read_state(", "read_encoder(", "read_brake("):
        assert token in source, f"required read call missing: {token}"
    assert source.count("/dev/serial/by-path/") >= 1
    assert "controller_network_clock" in source
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
