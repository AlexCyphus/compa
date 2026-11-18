"""Which Claude account the calls bill to: the CLI config dir from settings.json, checked at launch."""
import json
import os
import subprocess

from compa.settings import Profile


def use_claude_account(profile: Profile) -> str:
    """Point the Claude CLI at the configured account and return a line naming it."""
    os.environ["CLAUDE_CONFIG_DIR"] = str(profile.claude_config_dir)
    status = json.loads(subprocess.run(["claude", "auth", "status"], capture_output=True, text=True).stdout)
    if not status.get("loggedIn"):
        raise SystemExit(f"Not logged in to Claude in {profile.claude_config_dir}. "
                         f"Run: CLAUDE_CONFIG_DIR={profile.claude_config_dir} claude auth login")
    return f"{status['email']} · {status['orgName']} · {status['subscriptionType']}"
