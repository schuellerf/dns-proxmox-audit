# DNS audit + Proxmox `allowed-ips` — install

**Overview:** see [README.md](README.md) for the use case (observed DNS names to reviewed IPs to Proxmox firewall, **mainly to restrict outgoing** traffic to allowed destinations).

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

```bash
cd /path/to/dns-proxmox-audit
ansible-playbook -i 'TARGET_HOST,' -b -K ansible/dns-audit.yml
```

The playbook also installs [lib/static-endpoints-export.py](lib/static-endpoints-export.py) so you can run it manually on the target (`sudo …/static-endpoints-export.py`); the timer does **not** run it.

### 2. Controller — pull, merge, resolve — [ansible/dns-audit-pull-merge.yml](ansible/dns-audit-pull-merge.yml)

Runs `static-endpoints-export.py` on the **target** over SSH (`sudo` required), then `rsync` from the target to `dns-proxmox-audit/.pulled-audit/`. The pull now includes `apt-names.txt` and `ntp.txt` (snapshot, not time-prefixed) for review alongside the hourly `*dns-names.txt` files, then runs the merge script. Writes `.names-review.txt` and (by default) `.pve-allowed-staged.txt` next to the repo. Extra var: `dns_target_host` (or deprecated `dns_journal_host`).

```bash
cd /path/to/dns-proxmox-audit
ansible-playbook ansible/dns-audit-pull-merge.yml -e dns_target_host=TARGET_HOST
```

- `-e dns_merge_emit_pve=false` — names-only list, no `getaddrinfo` on the controller.
- `-e dns_merge_ipv4_only=true` — only IPv4 when resolving.

### 3. Proxmox — [ansible/proxmox-update-allowed-ips.yml](ansible/proxmox-update-allowed-ips.yml)

| Step | Tag |
| --- | --- |
| Install `proxmox-update-allowed-ips.py` on the node | `install` |
| Copy **reviewed** staged file from the controller, merge into `pve_vm_fw`, `systemctl reload pve-firewall` | `deploy` |

Install once:

```bash
ansible-playbook -i 'PVE_HOST,' -b -K ansible/proxmox-update-allowed-ips.yml --tags install
```

Deploy after you have edited/approved the staged file on the controller:

```bash
ansible-playbook -i 'PVE_HOST,' -b -K ansible/proxmox-update-allowed-ips.yml --tags deploy \
  -e dns_audit_pve_staged_file=/path/to/dns-proxmox-audit/.pve-allowed-staged.txt \
  -e pve_vm_fw=/etc/pve/firewall/100.fw
```

Manual steps and fallbacks: [hacking.md](hacking.md).
