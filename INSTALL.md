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

The play’s `hosts` is the same name you put in the inventory: use **`-i your.target.example.com,`** and **`-e dns_target_host=…`** (or deprecated **`dns_journal_host`**) to that host; optional **`-e ansible_user=...`**, **`-e ansible_ssh_private_key_file=...`**, `~/.ssh/config`. On the target: `static-endpoints-export.py` with `sudo` **`-n`**. Rsync to **`.pulled-audit`**, merge, and review outputs run on the controller (**`delegate_to: localhost`**, **`connection: local`**).

Rsync source on the target defaults to `/var/lib/dns-audit` (override with **`dns_audit_fetch_src`**). Pull includes `apt-names.txt` and `ntp.txt` and hourly `*dns-names.txt` files. Writes **`.names-review.txt`** and (by default) **`.pve-allowed-staged.txt`** under the repo.

Default **`ansible_ssh_common_args`:** **`-o BatchMode=yes`**, **`-o StrictHostKeyChecking=accept-new`**. Set **`dns_audit_ssh_common_args`** to replace the whole `ssh` option string.

- `-e dns_merge_emit_pve=false` — names review only, no `getaddrinfo`.
- `-e dns_merge_ipv4_only=true` — only IPv4 when resolving.

`gather_facts: false`. Default **`dns_merge_python`:** `/usr/bin/python3`; override with **`-e dns_merge_python=...`**.

### 3. Proxmox — [ansible/proxmox-update-allowed-ips.yml](ansible/proxmox-update-allowed-ips.yml)

| Step | Tag |
| --- | --- |
| Install `proxmox-update-allowed-ips.py` on the node | `install` |
| Copy **reviewed** staged file from the controller, merge into `pve_vm_fw`, `systemctl reload pve-firewall` | `deploy` |

See [README.md](README.md#ansible-quick-start-three-playbooks) for the exact `ansible-playbook` lines.

Manual steps and fallbacks: [hacking.md](hacking.md).
