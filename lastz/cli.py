"""
Interactive master menu.  Each menu option maps to a flow or the watcher daemon.
"""
import time

from lastz.input import GameNotRunningError


def _header() -> None:
    print("=" * 60)
    print("          LASTZ GAME AUTOMATION MASTER RUNNER          ")
    print("=" * 60)
    print(" 1. [Flow 1 & 2] Claim Alliance Gifts (Common & Rare)")
    print(" 2. [Flow 3]     Claim Battle Rewards (Dynamic Chest)")
    print(" 3. [Flow 4]     Collect HQ Drone Gift (Idle Reward)")
    print(" 4. [Flow 5]     HQ Resource Collection (Buildings)")
    print(" 5. [Flow 5d]    HQ Resource Collection — Dry Run (no clicks)")
    print(" 6. [Full Loop]  Run All Claim Flow Sequences")
    print(" 7. [Watcher]    Start Background Watcher Guardian Daemon")
    print(" 8. [Scouting]   World Map Scouting Loop (Ctrl+C to stop)")
    print(" 9. [Scouting]   Scouting — Dry Run (scan only, no clicks)")
    print("10. Exit")
    print("=" * 60)


def main() -> None:
    while True:
        _header()
        try:
            choice = input("Enter your choice (1-10): ").strip()
        except KeyboardInterrupt:
            print("\nExiting. Goodbye!")
            break

        if choice == "1":
            print("\n>>> Launching Alliance Gifts Claim Flow...")
            from lastz.flows.alliance_gifts import run_alliance_gifts_flow
            try:
                run_alliance_gifts_flow()
                print(">>> Alliance Gifts Claim Flow finished!\n")
            except GameNotRunningError as e:
                print(f"\n[!] {e}\n")

        elif choice == "2":
            print("\n>>> Launching Battle Rewards Claim Flow...")
            from lastz.flows.battle_rewards import run_battle_rewards_flow
            try:
                run_battle_rewards_flow()
                print(">>> Battle Rewards Claim Flow finished!\n")
            except GameNotRunningError as e:
                print(f"\n[!] {e}\n")

        elif choice == "3":
            print("\n>>> Launching HQ Drone Gift Collect Flow...")
            from lastz.flows.drone_gift import run_drone_gift_flow
            try:
                status = run_drone_gift_flow()
                print(f">>> Drone Gift Flow finished: {status}\n")
            except GameNotRunningError as e:
                print(f"\n[!] {e}\n")

        elif choice == "4":
            print("\n>>> Launching HQ Resource Collection Flow...")
            from lastz.flows.hq_resources import run_hq_resources_flow
            try:
                status = run_hq_resources_flow()
                print(f">>> HQ Resource Collection finished: {status}\n")
            except GameNotRunningError as e:
                print(f"\n[!] {e}\n")

        elif choice == "5":
            print("\n>>> Launching HQ Resource Collection — DRY RUN (scan only, no clicks)...")
            from lastz.flows.hq_resources import run_hq_resources_flow
            try:
                status = run_hq_resources_flow(dry_run=True)
                print(f">>> HQ Resource Dry Run finished: {status}\n")
            except GameNotRunningError as e:
                print(f"\n[!] {e}\n")

        elif choice == "6":
            print("\n>>> Running Full Automation Sequence...\n")
            from lastz.flows.alliance_gifts import run_alliance_gifts_flow
            from lastz.flows.battle_rewards import run_battle_rewards_flow
            from lastz.flows.drone_gift import run_drone_gift_flow
            from lastz.flows.hq_resources import run_hq_resources_flow

            try:
                print("--- STEP 1: Alliance Gifts ---")
                run_alliance_gifts_flow()
                time.sleep(2.0)

                print("\n--- STEP 2: Battle Rewards ---")
                run_battle_rewards_flow()
                time.sleep(2.0)

                print("\n--- STEP 3: HQ Resource Collection ---")
                res_status = run_hq_resources_flow()
                print(f"    HQ Resources: {res_status}")
                time.sleep(2.0)

                print("\n--- STEP 4: HQ Drone Gift ---")
                drone_status = run_drone_gift_flow()
                print(f"    Drone Gift: {drone_status}")

                print("\n>>> Full Automation Sequence completed successfully!\n")
            except GameNotRunningError as e:
                print(f"\n[!] {e}\n")

        elif choice == "7":
            print("\n>>> Starting Background Watcher Guardian Daemon...")
            from lastz.watcher import run_watcher_loop
            run_watcher_loop()

        elif choice == "8":
            print("\n>>> Starting World Map Scouting Loop...")
            from lastz.flows.scouting import run_scouting_flow
            try:
                run_scouting_flow()
                print(">>> Scouting loop ended.\n")
            except GameNotRunningError as e:
                print(f"\n[!] {e}\n")

        elif choice == "9":
            print("\n>>> Starting Scouting Dry Run (no Scout clicks)...")
            from lastz.flows.scouting import run_scouting_flow
            try:
                run_scouting_flow(dry_run=True)
                print(">>> Scouting dry run ended.\n")
            except GameNotRunningError as e:
                print(f"\n[!] {e}\n")

        elif choice == "10":
            print("Exiting. Goodbye!")
            break

        else:
            print("Invalid choice. Please enter a number between 1 and 10.")
            time.sleep(1)
