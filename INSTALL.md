# DNS audit + Proxmox guest firewall — install

**Overview and the three `ansible-playbook` entrypoints** are in [README.md](README.md) (target install, pull/merge, resolve + Proxmox deploy).

**Tested on Ubuntu;** for outgoing TCP/UDP ports to allow toward mirrors, NTP, and DNS, see the **Outgoing access** section in [README.md](README.md).

**Trust model:** the **target host** only writes **FQDNs** per hour (`*dns-names.txt` from the systemd-resolved **journal**). IPs for the firewall are **never** taken from journal answers. The pull/merge playbook **merges** hourly names on the target into **`names-review.txt`**, refreshes **`apt-names.txt`**, **`ntp.txt`**, and **`dns-ips.txt`**, and **`fetch`es** all four into your repo (defaults under the repo root, each with **`become`** on the target so **`/var/lib/dns-audit`** can stay `0750` root-only). **`dns-ips.txt`** holds **resolver IP addresses** observed on the target (`python3 -m dns_proxmox_audit.static_endpoints` / **`resolvectl`**, with fallbacks). After you **review** **`names-review.txt`**, the Proxmox playbook’s **`resolve`** step **fetches** the current guest **`.fw`** from the node, **resolves** **`apt-names.txt`**, **`ntp.txt`**, and **`names-review.txt`** on the controller into staged files, and **stages** **`dns-ips.txt`** to **`[IPSET dns-ips]`** without **getaddrinfo** (IPs only). It **merges locally** into **`.pve-fw-merged.<vmid>.fw`**, updating **only** the **`[IPSET apt-names]`**, **`[IPSET ntp-names]`**, **`[IPSET reviewed-names]`**, and **`[IPSET dns-ips]`** sections. All other **`[IPSET …]`** blocks and **`[RULES]`** are left as on the node; you reference **`+guest/apt-names`**, **`+guest/dns-ips`**, and the other sets in rules if you want. **`deploy`** copies the merged file to the node, runs **`pve-firewall compile`**, and reloads.

**Prerequisites:** `ansible-playbook`, SSH to the target host and (separately) to the PVE node.

### 1. Target host — [ansible/dns-audit.yml](ansible/dns-audit.yml)

| Source (in this repo) | On the target host |
| --- | --- |
| [systemd/systemd-resolved.service.d/10-dns-audit.conf](systemd/systemd-resolved.service.d/10-dns-audit.conf) | `/etc/systemd/system/systemd-resolved.service.d/10-dns-audit.conf` |
| [systemd/journald.conf.d/90-dns-audit-limits.conf](systemd/journald.conf.d/90-dns-audit-limits.conf) | `/etc/systemd/journald.conf.d/90-dns-audit-limits.conf` |
| [lib/dns_proxmox_audit/](lib/dns_proxmox_audit/) (Python package) | `/usr/local/lib/dns_proxmox_audit/` (same layout; run with `PYTHONPATH=/usr/local/lib` and `python3 -m dns_proxmox_audit.…`) including **`static_endpoints`**, **`hourly_export`**, **`merge_hourly`** (APT + NTP + **`dns-ips.txt`**: mirrors from `/etc/apt`; NTP from **`/etc`**, **`timedatectl`**, **`systemd-analyze cat-config`**, **chronyc** if **chronyd** is active; resolvers from **`resolvectl`** with resolv fallbacks; **`ntp.txt`** is **FQDN-only**; **loopback** addresses omitted from **`dns-ips.txt`**) |
| [systemd/dns-hourly-export.service](systemd/dns-hourly-export.service), [systemd/dns-hourly-export.timer](systemd/dns-hourly-export.timer) | `/etc/systemd/system/` |
| [systemd/tmpfiles.d/dns-audit.conf](systemd/tmpfiles.d/dns-audit.conf) | `/etc/tmpfiles.d/dns-audit.conf` |

Hourly files under the default output dir (`/var/lib/dns-audit/`) are named like `YYYYMMDDHH+0100-dns-names.txt` (wall-clock start of the hour + `strftime("%z")`, no separator before the offset; see [audit_export_common.filename_for_hour_start](lib/dns_proxmox_audit/audit_export_common.py)). Each file lists **one FQDN per line** (no IPs). **Interactive** runs of `python3 -m dns_proxmox_audit.hourly_export` with no time flags export the **current partial** hour; the **systemd** unit passes `--previous-hour` so each run covers the **last full** local hour only.

The playbook also installs the [lib/dns_proxmox_audit](lib/dns_proxmox_audit) package so you can run e.g. `sudo env PYTHONPATH=/usr/local/lib python3 -m dns_proxmox_audit.static_endpoints` manually on the target; the timer does **not** run it.

### 2. Pull, merge, fetch — [ansible/dns-audit-pull-merge.yml](ansible/dns-audit-pull-merge.yml)

Use **`-i your.target.example.com,`** and **`-e dns_target_host=…`** (must match the inventory host); optional **`-e ansible_user=...`**, **`-e ansible_ssh_private_key_file=...`**, `~/.ssh/config`. On the **target:** `python3 -m dns_proxmox_audit.static_endpoints` and **`python3 -m dns_proxmox_audit.merge_hourly`** (package under **`/usr/local/lib/dns_proxmox_audit/`**, **`PYTHONPATH=/usr/local/lib`**) with `sudo` **`-n`**. **`ansible.builtin.fetch`** (as root on the target) copies **`names-review.txt`**, **`apt-names.txt`**, **`ntp.txt`**, and **`dns-ips.txt`** to the repo defaults **`names-review.txt`**, **`apt-names.txt`**, **`ntp.txt`**, **`dns-ips.txt`** (override with **`dns_audit_names_review`**, **`dns_audit_apt_names`**, **`dns_audit_ntp_list`**, **`dns_audit_dns_ips`**).

Input dir on the target defaults to **`/var/lib/dns-audit`** (override with **`dns_audit_fetch_src`**). Merge reads hourly `*dns-names.txt` there and writes **`names-review.txt`** in that directory.

Default **`ansible_ssh_common_args`:** **`-o BatchMode=yes`**, **`-o StrictHostKeyChecking=accept-new`**. Set **`dns_audit_ssh_common_args`** to replace the whole `ssh` option string for the play connection (used for SSH + **`fetch`**).

`gather_facts: false`.

### 3. Resolve + Proxmox — [ansible/proxmox-update-allowed-ips.yml](ansible/proxmox-update-allowed-ips.yml)

Use **`-i your.pve.node.example.com,`** and **`-e pve_vmid=<guest id>`** (or **`-e pve_vm_fw=/etc/pve/firewall/custom.fw`** to override the path).

| Step | Tag |
| --- | --- |
| **Slurp** guest **`.fw`**; **`apt-names.txt`**, **`ntp.txt`**, **`names-review.txt`**, **`dns-ips.txt`** → staged IP files; local **`python3 -m dns_proxmox_audit.proxmox_update_allowed_ips --dry-run --managed-ipset …`** (four sets) → **`.pve-fw-merged.<vmid>.fw`** | `resolve` |
| Copy merged **`.fw`** to the node, **`pve-firewall compile`**, **`systemctl reload pve-firewall`** | `deploy` |

Typical: **`--tags resolve`** then **`--tags deploy`** after editing **`names-review.txt`**. Defaults: **`dns_audit_apt_names`**, **`dns_audit_ntp_names`**, **`dns_audit_names_review`**, **`dns_audit_dns_ips`**, **`dns_audit_pve_staged_apt`**, **`dns_audit_pve_staged_ntp`**, **`dns_audit_pve_staged_reviewed`**, **`dns_audit_pve_staged_dns`** under **`$REPO/`**; **`dns_audit_pve_merged_fw`** (deploy source) defaults to **`$REPO/.pve-fw-merged.<vmid>.fw`**.

**`-e dns_resolve_ipv4_only=true`** — pass **`--ipv4-only`** to staging on the controller ( **`getaddrinfo`** for the three name lists; IPv6 lines dropped for **`dns-ips`** as well).

See [README.md](README.md#ansible-quick-start-three-playbooks) for example `ansible-playbook` lines.

Manual steps and fallbacks: [hacking.md](hacking.md).
