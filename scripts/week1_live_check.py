"""Opt-in real SDK/CLI acceptance check. Spends 0.001 Devnet SOL once per saved job."""

import json
import os
import subprocess
import sys
from pathlib import Path

import httpx

from sdk.poa import PoAClient


def main():
    root = Path(__file__).resolve().parents[1]
    owner = json.loads((root / "data/tracy-owner.json").read_text(encoding="utf-8"))
    recipient = json.loads((root / "data/presentation-recipient.json").read_text(encoding="utf-8"))[
        "public_key"
    ]
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=180) as browser:
        login = browser.post("/v1/auth/login", json={k: owner[k] for k in ("email", "password")})
        login.raise_for_status()
        browser.headers["X-CSRF-Token"] = login.json()["csrf_token"]
        key = browser.post("/v1/account/api-keys", json={"name": "Week-one SDK acceptance"})
        key.raise_for_status()
        token = key.json()["token"]
        env = {**os.environ, "TRACY_API_KEY": token}
        agent_file = root / "data/week1-sdk-agent.json"
        jobs_file = root / "data/week1-sdk-jobs.json"
        jobs_file.write_text(
            json.dumps([{"request_id": "week1_payout_001", "to": recipient, "amount": 0.001}]),
            encoding="utf-8",
        )
        report = {}
        try:
            init = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "sdk.poa",
                    "init",
                    "--key-file",
                    str(agent_file),
                    "--name",
                    "Tracy SDK payout bot",
                    "--description",
                    "Independent process with restart-safe payouts",
                    "--recipient",
                    recipient,
                    "--limit",
                    "0.01",
                    "--daily-budget",
                    "0.01",
                ],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            )
            report["agent"] = json.loads(init.stdout)
            command = [
                sys.executable,
                "-m",
                "scripts.payout_bot",
                "--key-file",
                str(agent_file),
                "--jobs",
                str(jobs_file),
            ]
            for name in ("first_process", "restarted_process"):
                result = subprocess.run(command, env=env, capture_output=True, text=True, check=True)
                report[name] = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
            first, second = report["first_process"], report["restarted_process"]
            assert first[0]["action_id"] == second[0]["action_id"]
            assert second[0]["status"] == "VERIFIED" and second[1]["verification"]["valid"]
            with PoAClient(api_key=token) as tracy:
                action = tracy.request(report["agent"]["agent_id"], "week1_payout_001")
                report["action"] = action
                assert tracy.agent(report["agent"]["agent_id"])["budget"]["used_lamports"] == 1_000_000
            report["passed"] = True
            print(
                json.dumps(
                    {
                        "passed": True,
                        "agent_id": report["agent"]["agent_id"],
                        "action_id": second[0]["action_id"],
                        "receipt_id": second[0]["receipt_id"],
                        "restart_sent_no_duplicate": True,
                    },
                    indent=2,
                )
            )
        finally:
            browser.delete("/v1/account/api-keys/" + key.json()["key_id"]).raise_for_status()
            (root / "data/week1-sdk-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
