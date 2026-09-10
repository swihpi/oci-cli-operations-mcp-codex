"""Explicit opt-in provisioning: transfer only DEFAULT's key/config via SSH.

Never prints keys, fingerprint, identifiers, password, or configuration content.
Run locally only after the owner authorizes using their administrator identity.
The local login receipt must stay outside the public repository.
"""
import argparse
import configparser
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import tarfile
from werkzeug.security import generate_password_hash


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',required=True)
    parser.add_argument('--ssh-key',required=True)
    parser.add_argument('--protected-instance',required=True)
    parser.add_argument('--receipt',required=True)
    args=parser.parse_args()
    receipt=Path(args.receipt).resolve()
    source_root=Path(__file__).resolve().parents[2]
    if receipt==source_root or source_root in receipt.parents:
        raise SystemExit('Credential receipt must not be stored in the public source tree')
    if receipt.exists():raise SystemExit('Refusing to overwrite an existing credential receipt')
    config=configparser.ConfigParser(interpolation=None)
    config.read(Path.home()/'.oci/config')
    profile=config['DEFAULT']
    if profile.get('pass_phrase'):raise SystemExit('Encrypted key requires a separately reviewed passphrase handling design')
    keypath=Path(os.path.expanduser(profile['key_file'])).resolve()
    selected={k:profile[k] for k in ['user','fingerprint','tenancy','region']}
    selected['key_file']='/var/lib/ociworker/.oci/api_key.pem'
    target=configparser.ConfigParser(interpolation=None)
    target['DEFAULT']=selected
    out=io.StringIO();target.write(out)
    password=secrets.token_urlsafe(24)
    web={
        'CONSOLE_MODE':'live','CONSOLE_DATABASE':'/var/lib/oci-operations-console/console.db',
        'CONSOLE_PASSWORD_HASH':generate_password_hash(password),
        'CONSOLE_TENANCY':profile['tenancy'],'CONSOLE_REGION':profile['region'],
        'CONSOLE_ENABLE_WRITES':'true','CONSOLE_ISOLATED_WORKER':'true',
        'CONSOLE_PROTECTED_INSTANCES':args.protected_instance,
        'CONSOLE_ORIGIN':'http://127.0.0.1:8766','CONSOLE_SECURE_COOKIE':'false',
        'CONSOLE_START_SCHEDULER':'true',
        'CONSOLE_ARCHIVE_DSN':'postgresql:///oci_operations_console?host=/var/run/postgresql',
    }
    worker={'enable_writes':True,'protected_instances':[args.protected_instance]}
    files={'config':out.getvalue().encode(),'api_key.pem':keypath.read_bytes(),
           'web.env':'\n'.join(k+'='+v for k,v in web.items()).encode(),
           'worker.json':json.dumps(worker).encode()}
    archive=io.BytesIO()
    with tarfile.open(fileobj=archive,mode='w') as tar:
        for name,content in files.items():
            info=tarfile.TarInfo(name);info.size=len(content);info.mode=0o600
            tar.addfile(info,io.BytesIO(content))
    remote='''set -eu
test ! -e /var/lib/ociworker/.oci/api_key.pem
staging=$(mktemp -d /var/lib/ociworker/provision.XXXXXX)
chmod 700 "$staging"
tar -xf - -C "$staging"
install -o ociworker -g ociworker -m 0600 "$staging/config" /var/lib/ociworker/.oci/config
install -o ociworker -g ociworker -m 0600 "$staging/api_key.pem" /var/lib/ociworker/.oci/api_key.pem
install -o root -g ociconsole -m 0640 "$staging/web.env" /etc/oci-operations-console/web.env
install -o root -g ociworker -m 0640 "$staging/worker.json" /etc/oci-operations-console/worker.json
rm "$staging/config" "$staging/api_key.pem" "$staging/web.env" "$staging/worker.json"
rmdir "$staging"
restorecon -R /var/lib/ociworker /etc/oci-operations-console
'''
    # Script is a fixed literal, never derived from credentials or resource input.
    import shlex
    command=['ssh','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes','-i',args.ssh_key,args.host,'sudo -n bash -c '+shlex.quote(remote)]
    result=subprocess.run(command,input=archive.getvalue(),capture_output=True)
    if result.returncode:
        raise SystemExit('Provisioning failed; no credentials printed. Inspect remote file existence and permissions before retrying.')
    receipt.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd=os.open(receipt,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
    with os.fdopen(fd,'w') as file:
        file.write('Private OCI Operations Console\nURL: http://127.0.0.1:8766/\nPassword: '+password+'\nAccess requires the SSH tunnel. Do not share this file.\n')
    print('Administrator credential provisioned over SSH. Restricted local login receipt created. Writes are approval-gated and audit-retained.')


if __name__=='__main__':main()
