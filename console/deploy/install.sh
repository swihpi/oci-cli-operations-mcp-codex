#!/bin/bash
# Install source from a reviewed staging directory; no credentials in this file.
set -euo pipefail
test "$(id -u)" -eq 0
staging=${1:?Pass the exact staging source directory}
test -f "$staging/opsconsole/app.py"
test ! -e /opt/oci-operations-console || { echo 'Existing installation: use a reviewed upgrade procedure'; exit 1; }
useradd --system --home-dir /var/lib/oci-operations-console --shell /sbin/nologin ociconsole
useradd --system --home-dir /var/lib/ociworker --shell /sbin/nologin ociworker
install -d -m 0755 /opt/oci-operations-console/app
install -d -m 0700 -o ociconsole -g ociconsole /var/lib/oci-operations-console
install -d -m 0700 -o ociworker -g ociworker /var/lib/ociworker/.oci
install -d -m 0755 -o root -g root /etc/oci-operations-console
cp -R "$staging/opsconsole" /opt/oci-operations-console/app/
cp "$staging/requirements.txt" /opt/oci-operations-console/requirements.txt
chown -R root:root /opt/oci-operations-console
chmod -R go-w /opt/oci-operations-console
python3 -m venv /opt/oci-operations-console/venv
/opt/oci-operations-console/venv/bin/pip install -r /opt/oci-operations-console/requirements.txt
python3 -m venv /opt/oci-operations-console/oci-venv
/opt/oci-operations-console/oci-venv/bin/pip install 'oci-cli==3.81.1'
sudo -u postgres createuser --login ociconsole 2>/dev/null || true
sudo -u postgres createdb --owner=ociconsole oci_operations_console 2>/dev/null || true
install -m 0440 "$staging/deploy/oci-console-worker.sudoers" /etc/sudoers.d/oci-console-worker
visudo -cf /etc/sudoers.d/oci-console-worker
install -m 0644 "$staging/deploy/oci-operations-console.service" /etc/systemd/system/oci-operations-console.service
restorecon -R /opt/oci-operations-console /var/lib/oci-operations-console /var/lib/ociworker /etc/oci-operations-console /etc/sudoers.d/oci-console-worker
systemctl daemon-reload
echo 'Source installed. Provision credentials before starting the private service.'
