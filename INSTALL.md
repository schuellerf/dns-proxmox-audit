# DNS audit + Proxmox `allowed-ips` — install

**Overview and the three `ansible-playbook` entrypoints** are in [README.md](README.md) (target install, pull/merge, Proxmox install/deploy).

**Tested on Ubuntu;** for outgoing TCP/UDP ports to allow toward mirrors, NTP, and DNS, see the **Outgoing access** section in [README.md](README.md).

**Trust model:** the **target host** only writes **FQDNs** per hour (`*dns-names.txt` from the systemd-resolved **journal**). IPs for the firewall are **never** taken from journal answers. You **rsync** those files to the **Ansible controller**, run [lib/dns-resolve-and-stage-for-pve.py](lib/dns-resolve-and-stage-for-pve.py) there (DNS = controller’s resolver), **review** output, then deploy to Proxmox.

**Prerequisites:** `ansible-playbook`, SSH to the target host and (separately) to the PVE node; `rsync` over SSH for the pull playbook.

### 1. Target host — [ansible/dns-audit.yml](ansible/dns-audit.yml)

| Source (in this repo) | On the target host |
| --- | --- |
| [systemd/systemd-resolved.service.d/10-dns-audit.conf](systemd/systemd-resolved.service.d/10-dns-audit.conf) | `/etc/systemd/system/systemd-resolved.service.d/10-dns-audit.conf` |
| [systemd/journald.conf.d/90-dns-audit-limits.conf](systemd/journald.conf.d/90-dns-audit-limits.conf) | `/etc/systemd/journald.conf.d/90-dns-audit-limits.conf` |
| [lib/audit_export_common.py](lib/audit_export_common.py) | `/usr/local/lib/dns-proxmox-audit/audit_export_common.py` |
| [lib/dns-hourly-export.py](lib/dns-hourly-export.py) | `/usr/local/lib/dns-proxmox-audit/dns-hourly-export.py` |
| [lib/static-endpoints-export.py](lib/static-endpoints-export.py) | `/usr/local/lib/dns-proxmox-audit/static-endpoints-export.py` (APT + NTP host lists) |
| [systemd/dns-hourly-export.service](systemd/dns-hourly-export.service), [systemd/dns-hourly-export.timer](systemd/dns-hourly-export.timer) | `/etc/systemd/system/` |
| [systemd/tmpfiles.d/dns-audit.conf](systemd/tmpfiles.d/dns-audit.conf) | `/etc/tmpfiles.d/dns-audit.conf` |

Hourly files under the default output dir (`/var/lib/dns-audit/`) look like `YYYYMMDDHH+0100-dns-names.txt` (one FQDN per line; older exports may have `…HH_+0100-…` with an extra underscore, still supported when merging). **Interactive** runs of `dns-hourly-export.py` with no time flags export the **current partial** hour; the **systemd** unit passes `--previous-hour` so each run covers the **last full** local hour only.

The playbook also installs [lib/static-endpoints-export.py](lib/static-endpoints-export.py) so you can run it manually on the target (`sudo …/static-endpoints-export.py`); the timer does **not** run it.

### 2. Controller — pull, merge, resolve — [ansible/dns-audit-pull-merge.yml](ansible/dns-audit-pull-merge.yml)

The play **connects to the audit target** (same SSH and inventory as any normal playbook: **`-e dns_target_host=...`** or deprecated **`dns_journal_host`**; optional **`-e ansible_user=...`**, **`-e ansible_ssh_private_key_file=...`**, and host/SSH config as usual). On the target it runs `static-endpoints-export.py` with `sudo` **`-n`** (non-interactive; passwordless **sudo** is required for that). The merge step, local pull directory, and `rsync` from the target run on the **Ansible controller** via **`delegate_to: localhost`**.

`rsync` pulls to `dns-proxmox-audit/.pulled-audit/`. The pull includes `apt-names.txt` and `ntp.txt` (snapshot, not time-prefixed) for review alongside the hourly `*dns-names.txt` files, then runs the merge script. Writes `.names-review.txt` and (by default) `.pve-allowed-staged.txt` next to the repo.

The SSH connection to the play host defaults to **`-o BatchMode=yes`**, **`-o StrictHostKeyChecking=accept-new`**; override the full extra args for `ssh` with **`-e 'dns_audit_ssh_common_args=…'`** (for example a different `StrictHostKeyChecking` or password-based auth) if you need to.

- `-e dns_merge_emit_pve=false` — names-only list, no `getaddrinfo` on the controller.
- `-e dns_merge_ipv4_only=true` — only IPv4 when resolving.

The playbook does **not** run Ansible fact gathering. The merge step uses **`/usr/bin/python3`** for **`dns_merge_python`** by default, so a broken **pyenv**/`PATH` on the controller does not break the run. Override with **`-e dns_merge_python=...`** if your system Python lives elsewhere.

### 3. Proxmox — [ansible/proxmox-update-allowed-ips.yml](ansible/proxmox-update-allowed-ips.yml)

| Step | Tag |
| --- | --- |
| Install `proxmox-update-allowed-ips.py` on the node | `install` |
| Copy **reviewed** staged file from the controller, merge into `pve_vm_fw`, `systemctl reload pve-firewall` | `deploy` |

See [README.md](README.md#ansible-quick-start-three-playbooks) for the exact `ansible-playbook` lines.

Manual steps and fallbacks: [hacking.md](hacking.md).
