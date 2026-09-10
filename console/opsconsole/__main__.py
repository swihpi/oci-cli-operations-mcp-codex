import argparse
import getpass
from werkzeug.security import generate_password_hash

parser=argparse.ArgumentParser()
parser.add_argument("command",choices=["serve","password-hash"])
args=parser.parse_args()
if args.command=="password-hash":
    password=getpass.getpass("Console password (at least 16 characters): ")
    if len(password)<16: raise SystemExit("Use at least 16 characters")
    if password!=getpass.getpass("Confirm password: "): raise SystemExit("Passwords differ")
    print(generate_password_hash(password))
else:
    from .app import create_app
    create_app().run(host="127.0.0.1",port=8765,debug=False)
