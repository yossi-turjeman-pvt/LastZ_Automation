"""
Interactive master menu — Alliance Gifts + Helicopter + CrossOver helpers.
"""
import time

from lastz.input import GameNotRunningError


def _header() -> None:
    print("=" * 60)
    print("          LASTZ — ALLIANCE GIFTS                     ")
    print("=" * 60)
    print(" 1. Claim Alliance Gifts (once)")
    print(" 2. Watcher loop (claim on interval + Heli priority)")
    print(" 3. Fix Hebrew (CrossOver) — one-time setup")
    print(" 4. Help watcher (handshake blink clicker)")
    print(" 5. Show stats (motivation ledger)")
    print(" 6. Helicopter monitor (BR watch + heli flow)")
    print(" 7. Exit")
    print("=" * 60)


def main() -> None:
    while True:
        _header()
        try:
            choice = input("Enter your choice (1-7): ").strip()
        except KeyboardInterrupt:
            print("\nExiting. Goodbye!")
            break

        if choice == "1":
            print("\n>>> Launching Alliance Gifts Claim Flow...")
            from lastz.flows.alliance_gifts import run_alliance_gifts_flow
            try:
                run_alliance_gifts_flow(source="menu")
                print(">>> Alliance Gifts Claim Flow finished!\n")
            except GameNotRunningError as e:
                print(f"\n[!] {e}\n")
            except Exception as e:
                print(f"\n[!] Flow failed: {e}")
                print("    See logs/runs.log and logs/debug/flow/crash_*.png\n")

        elif choice == "2":
            print("\n>>> Starting Alliance Gifts Watcher Loop...")
            print("    Helicopter priority ON when helicopter.enabled=true\n")
            from lastz.watcher import run_watcher_loop
            run_watcher_loop()

        elif choice == "3":
            print("\n>>> Fix Hebrew (one-time CrossOver bottle setup)...")
            from lastz.crossover_hebrew import apply_hebrew_fix
            apply_hebrew_fix()
            print()

        elif choice == "4":
            print("\n>>> Starting Help Watcher (BR corner handshake)...")
            print("    Play while it runs; Ctrl+C returns to this menu.\n")
            from lastz.flows.help_watcher import run_help_watcher_loop
            run_help_watcher_loop()

        elif choice == "5":
            from lastz.stats import print_month_stats
            print()
            print_month_stats()
            print()

        elif choice == "6":
            print("\n>>> Helicopter monitor — watches BR heli indication...")
            print("    Ctrl+C returns to this menu.\n")
            from lastz.flows.helicopter import run_helicopter_monitor_loop
            run_helicopter_monitor_loop()

        elif choice == "7":
            print("Exiting. Goodbye!")
            break

        else:
            print("Invalid choice. Please enter a number between 1 and 7.")
            time.sleep(1)
