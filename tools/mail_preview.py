"""List local preview metadata, or open an explicitly chosen preview in the browser."""
import argparse
import sys
import webbrowser
from email import policy
from email.parser import BytesParser
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
from app.core.config import get_settings  # noqa: E402
from app.core.runtime_paths import runtime_namespace  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", required=True, type=UUID)
    parser.add_argument("--message", type=UUID)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if settings.environment == "production" or settings.mail_delivery != "preview":
        parser.error("Preview mail is available only in local development/test")
    directory = runtime_namespace("mail-preview") / settings.environment / str(args.workspace)
    if args.message and args.open:
        import re
        message = BytesParser(policy=policy.default).parsebytes((directory / f"{args.message}.eml").read_bytes())
        link = re.search(r"https?://\S+", message.get_content()).group(0)
        if not link.startswith(settings.frontend_origin + "/account-action?"):
            parser.error("Preview does not contain a ResearchOS account action link")
        webbrowser.open(link)
        print("Opened the selected local preview. The token was not printed.")
    else:
        for path in sorted(directory.glob("*.eml")):
            message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
            print(f"{path.stem} | {message['Subject']}")


if __name__ == "__main__":
    main()
