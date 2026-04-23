# DNS audit + Proxmox `allowed-ips` — install

**Overview and the three `ansible-playbook` entrypoints** are in [README.md](README.md) (target install, pull/merge, resolve + Proxmox deploy).

**Tested on Ubuntu;** for outgoing TCP/UDP ports to allow toward mirrors, NTP, and DNS, see the **Outgoing access** section in [README.md](README.md).

**Trust model:** the **target host** only writes **FQDNs** per hour (`*dns-names.txt` from the systemd-resolved **journal**). IPs for the firewall are **never** taken from journal answers. The pull/merge playbook **merges** hourly names on the target into **`names-review.txt`**, refreshes **`apt-names.txt`** and **`ntp.txt`**, and **`fetch`es** all three into your repo (defaults: **`names-review.txt`**, **`apt-names.txt`**, **`ntp.txt`** under the repo root, each with **`become`** on the target so **`/var/lib/dns-audit`** can stay `0750` root-only). After you **review** that file, the Proxmox playbook’s **`resolve`** step runs **`getaddrinfo` on the controller** and writes **`.pve-allowed-staged.txt`**; **`deploy`** copies it to the node and updates the guest firewall.

**Prerequisites:** `ansible-playbook`, SSH to the target host and (separately) to the PVE node.

### 1. Target host — [ansible/dns-audit.yml](ansible/dns-audit.yml)

| Source (in this repo) | On the target host |
| --- | --- |
| [systemd/systemd-resolved.service.d/10-dns-audit.conf](systemd/systemd-resolved.service.d/10-dns-audit.conf) | `/etc/systemd/system/systemd-resolved.service.d/10-dns-audit.conf` |
| [systemd/journald.conf.d/90-dns-audit-limits.conf](systemd/journald.conf.d/90-dns-audit-limits.conf) | `/etc/systemd/journald.conf.d/90-dns-audit-limits.conf` |
| [lib/audit_export_common.py](lib/audit_export_common.py) | `/usr/local/lib/dns-proxmox-audit/audit_export_common.py` |
| [lib/dns_audit_names_lib.py](lib/dns_audit_names_lib.py) | `/usr/local/lib/dns-proxmox-audit/dns_audit_names_lib.py` |
| [lib/dns-merge-hourly-names.py](lib/dns-merge-hourly-names.py) | `/usr/local/lib/dns-proxmox-audit/dns-merge-hourly-names.py` |
| [lib/dns-hourly-export.py](lib/dns-hourly-export.py) | `/usr/local/lib/dns-proxmox-audit/dns-hourly-export.py` |
| [lib/static-endpoints-export.py](lib/static-endpoints-export.py) | `/usr/local/lib/dns-proxmox-audit/static-endpoints-export.py` (APT + NTP lists: `/etc`, **`timedatectl`**, **`systemd-analyze cat-config`**, **chronyc** if **chronyd** is active; **`ntp.txt`** is **FQDN-only**, IP-only peers omitted) |
| [systemd/dns-hourly-export.service](systemd/dns-hourly-export.service), [systemd/dns-hourly-export.timer](systemd/dns-hourly-export.timer) | `/etc/systemd/system/` |
| [systemd/tmpfiles.d/dns-audit.conf](systemd/tmpfiles.d/dns-audit.conf) | `/etc/tmpfiles.d/dns-audit.conf` |

Hourly files under the default output dir (`/var/lib/dns-audit/`) are named like `YYYYMMDDHH+0100-dns-names.txt` (wall-clock start of the hour + `strftime("%z")`, no separator before the offset; see [audit_export_common.filename_for_hour_start](lib/audit_export_common.py)). Each file lists **one FQDN per line** (no IPs). **Interactive** runs of `dns-hourly-export.py` with no time flags export the **current partial** hour; the **systemd** unit passes `--previous-hour` so each run covers the **last full** local hour only.

The playbook also installs [lib/static-endpoints-export.py](lib/static-endpoints-export.py) so you can run it manually on the target (`sudo …/static-endpoints-export.py`); the timer does **not** run it.

### 2. Pull, merge, fetch — [ansible/dns-audit-pull-merge.yml](ansible/dns-audit-pull-merge.yml)

Use **`-i your.target.example.com,`** and **`-e dns_target_host=…`** (must match the inventory host); optional **`-e ansible_user=...`**, **`-e ansible_ssh_private_key_file=...`**, `~/.ssh/config`. On the **target:** `static-endpoints-export.py` and **`dns-merge-hourly-names.py`** (under **`/usr/local/lib/dns-proxmox-audit/`**) with `sudo` **`-n`**. **`ansible.builtin.fetch`** (as root on the target) copies **`names-review.txt`**, **`apt-names.txt`**, and **`ntp.txt`** to the repo defaults **`names-review.txt`**, **`apt-names.txt`**, **`ntp.txt`** (override with **`dns_audit_names_review`**, **`dns_audit_apt_names`**, **`dns_audit_ntp_list`**).

Input dir on the target defaults to **`/var/lib/dns-audit`** (override with **`dns_audit_fetch_src`**). Merge reads hourly `*dns-names.txt` there and writes **`names-review.txt`** in that directory.

Default **`ansible_ssh_common_args`:** **`-o BatchMode=yes`**, **`-o StrictHostKeyChecking=accept-new`**. Set **`dns_audit_ssh_common_args`** to replace the whole `ssh` option string for the play connection (used for SSH + **`fetch`**).

`gather_facts: false`.

### 3. Resolve + Proxmox — [ansible/proxmox-update-allowed-ips.yml](ansible/proxmox-update-allowed-ips.yml)

| Step | Tag |
| --- | --- |
| Resolve **`names-review.txt`** → **`.pve-allowed-staged.txt`** on the **controller** (localhost) | `resolve` |
| Install `proxmox-update-allowed-ips.py` on the node | `install` |
| Copy staged file from the controller, merge into `pve_vm_fw`, `systemctl reload pve-firewall` | `deploy` |

Typical: **`--tags resolve,deploy`** after editing **`names-review.txt`**. Defaults: **`dns_audit_names_review`** and **`dns_audit_pve_staged`** (resolve) point to **`$REPO/names-review.txt`** and **`$REPO/.pve-allowed-staged.txt`**; **`dns_audit_pve_staged_file`** (deploy) defaults to **`$REPO/.pve-allowed-staged.txt`**.

**`-e dns_resolve_ipv4_only=true`** — pass **`--ipv4-only`** to the resolver on the controller.

See [README.md](README.md#ansible-quick-start-three-playbooks) for example `ansible-playbook` lines.

Manual steps and fallbacks: [hacking.md](hacking.md).
