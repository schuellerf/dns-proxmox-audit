# DNS audit + Proxmox `allowed-ips` — manual install and operations

Use this if you are **not** using Ansible (see [INSTALL.md](INSTALL.md) for playbooks) or for troubleshooting.

All paths are **on the target host** (the machine under audit: `systemd-resolved` and hourly export, and/or a Proxmox node for the firewall tool).

## Part 1 — systemd-resolved and journald

| Repository file | Install to |
| --- | --- |
| [systemd/systemd-resolved.service.d/10-dns-audit.conf](systemd/systemd-resolved.service.d/10-dns-audit.conf) | `/etc/systemd/system/systemd-resolved.service.d/10-dns-audit.conf` |
| [systemd/systemd-resolved.service.d/10-dns-audit-no-logfilter.conf](systemd/systemd-resolved.service.d/10-dns-audit-no-logfilter.conf) | Only if the full variant fails: **replace** the above (rename this file to `10-dns-audit.conf` when copying) |
| [systemd/journald.conf.d/90-dns-audit-limits.conf](systemd/journald.conf.d/90-dns-audit-limits.conf) | `/etc/systemd/journald.conf.d/90-dns-audit-limits.conf` |
| [systemd/resolved.conf.d/10-optional-LogLevel.conf.example](systemd/resolved.conf.d/10-optional-LogLevel.conf.example) | Optional. If you use it: `/etc/systemd/resolved.conf.d/10-optional-LogLevel.conf` (see comments inside) |

**Commands (resolved + journald):** (run from the `dns-proxmox-audit` directory in this repo, or use full paths to the files to copy)

```bash
sudo install -d -m 0755 /etc/systemd/system/systemd-resolved.service.d
sudo install -m 0644 systemd/systemd-resolved.service.d/10-dns-audit.conf \
  /etc/systemd/system/systemd-resolved.service.d/
sudo install -d -m 0755 /etc/systemd/journald.conf.d
sudo install -m 0644 systemd/journald.conf.d/90-dns-audit-limits.conf \
  /etc/systemd/journald.conf.d/
sudo systemctl daemon-reload
sudo systemctl restart systemd-journald
sudo systemctl restart systemd-resolved
```

**Check:** `journalctl -u systemd-resolved -n 30 --no-pager`

If the unit fails (unknown `LogFilterPatterns=` on older systemd): install [10-dns-audit-no-logfilter.conf](systemd/systemd-resolved.service.d/10-dns-audit-no-logfilter.conf) as `10-dns-audit.conf` and rely on the exporter’s `--line-substr` / `--no-substr-filter` behaviour.

## Part 2 — Hourly export

| Repository file | Install to |
| --- | --- |
| [lib/dns_proxmox_audit/](lib/dns_proxmox_audit/) (entire package directory) | `/usr/local/lib/dns_proxmox_audit/` (same layout; e.g. `…/dns_proxmox_audit/hourly_export.py` — run as `python3 -m dns_proxmox_audit.…` with `PYTHONPATH=/usr/local/lib`) |
| [systemd/dns-hourly-export.service](systemd/dns-hourly-export.service) | `/etc/systemd/system/dns-hourly-export.service` |
| [systemd/dns-hourly-export.timer](systemd/dns-hourly-export.timer) | `/etc/systemd/system/dns-hourly-export.timer` |
| [systemd/tmpfiles.d/dns-audit.conf](systemd/tmpfiles.d/dns-audit.conf) | `/etc/tmpfiles.d/dns-audit.conf` (or `/usr/lib/tmpfiles.d/dns-audit.conf`) |

**Output directory (hourly files):** `/var/lib/dns-audit/`

**Filename pattern:** e.g. `2026032914+0100-dns-names.txt`: wall-clock **start** of the hour, then `strftime("%z")` (no separator before the offset), as in [audit_export_common.filename_for_hour_start](lib/dns_proxmox_audit/audit_export_common.py). Each file lists **one FQDN per line** (no IPs; used for names-seen-only audit).

**Static lists (not hourly):** `apt-names.txt`, `ntp.txt`, and `dns-ips.txt` in the same directory. **`apt-names.txt`:** **HTTP(S) mirror hostnames** from `/etc/apt`. **`ntp.txt`:** **NTP peers** from config files (**timesyncd**, chrony, **ntp.conf**), plus **`timedatectl show`** / **`timedatectl timesync-status`** (current **`Server:`**), **`systemd-analyze cat-config systemd/timesyncd.conf`**, and **`chronyc`** if **`chronyd`** is active. **`ntp.txt` lists FQDN-style names only** (at least one dot, not an IP literal); IP-only endpoints are skipped. **`dns-ips.txt`:** current **DNS resolver** addresses on the target (**`resolvectl`**, with resolv fallbacks); **loopback** and **stub** addresses are omitted. Regenerated when you run [ansible/dns-audit-pull-merge.yml](ansible/dns-audit-pull-merge.yml) (static step on the target) or manually below. NTP from DHCP-only setups may still be missing; edge Deb822 or mirror URL formats may need manual checks.

**Commands:**

```bash
sudo install -d -m 0755 /usr/local/lib/dns_proxmox_audit
sudo cp -a lib/dns_proxmox_audit/. /usr/local/lib/dns_proxmox_audit/
sudo install -d -m 0755 /etc/tmpfiles.d
sudo install -m 0644 systemd/tmpfiles.d/dns-audit.conf /etc/tmpfiles.d/dns-audit.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/dns-audit.conf
sudo install -m 0644 systemd/dns-hourly-export.service /etc/systemd/system/
sudo install -m 0644 systemd/dns-hourly-export.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dns-hourly-export.timer
```

**Manual run (this clock hour so far,** start of the hour through now — default for ad-hoc use):

```bash
sudo env PYTHONPATH=/usr/local/lib python3 -m dns_proxmox_audit.hourly_export
```

**Last completed local hour** (same as the timer service):

```bash
sudo env PYTHONPATH=/usr/local/lib python3 -m dns_proxmox_audit.hourly_export --previous-hour
```

**Time zone for filenames:** the script uses `datetime.now().astimezone().tzinfo` when `--timezone local` (default). For a named zone: `--timezone Europe/Berlin`.

**Static APT + NTP host lists (manual, on the target, root):**

```bash
sudo env PYTHONPATH=/usr/local/lib python3 -m dns_proxmox_audit.static_endpoints
```

## Part 2b — Pull, merge, fetch

[ansible/dns-audit-pull-merge.yml](ansible/dns-audit-pull-merge.yml) runs **`python3 -m dns_proxmox_audit.merge_hourly`** on the **target**, then **`fetch`es** **`names-review.txt`**, **`apt-names.txt`**, **`ntp.txt`**, and **`dns-ips.txt`** into the repo (same basenames by default; fetch uses **`become`** because **`/var/lib/dns-audit`** is **`0750`**). Re-run [ansible/dns-audit.yml](ansible/dns-audit.yml) on the target after pulling new `lib/dns_proxmox_audit/` files.

**Manual on the target** (merge hourly files under the audit dir):

```bash
sudo env PYTHONPATH=/usr/local/lib python3 -m dns_proxmox_audit.merge_hourly
```

**Manual on the controller** (after review; from repo root — resolves **`apt-names.txt`**, **`ntp.txt`**, **`names-review.txt`** into **`.pve-apt-names-staged.txt`**, **`.pve-ntp-names-staged.txt`**, **`.pve-allowed-staged.txt`**, and stages **`dns-ips.txt`** to **`.pve-dns-ips-staged.txt`** without **getaddrinfo**; a missing input file produces an empty staged file for that channel):

```bash
env PYTHONPATH=lib python3 -m dns_proxmox_audit.resolve_for_pve
# or: env PYTHONPATH=lib python3 -m dns_proxmox_audit.resolve_for_pve --ipv4-only
```

After `pip install -e .` (see [pyproject.toml](pyproject.toml)), you can omit `PYTHONPATH=lib`.

Review **`names-review.txt`** (`name # last request: YYYYMMDDHH+0100`), then run the resolver (or [ansible/proxmox-update-allowed-ips.yml](ansible/proxmox-update-allowed-ips.yml) **`--tags resolve`**). Edit the staged files if needed. For APT/NTP hostnames, use **`apt-names.txt`** / **`ntp.txt`** from the target (static export) or re-run the static export. **`dns-ips.txt`** is IP literals from the target; optional **`+guest/dns-ips`** in **`[RULES]`** for DNS egress. The merge step updates **only** **`[IPSET apt-names]`**, **`[IPSET ntp-names]`**, **`[IPSET reviewed-names]`**, and **`[IPSET dns-ips]`** in the guest **`.fw`**; add **`+guest/apt-names`**, **`+guest/ntp-names`**, **`+guest/reviewed-names`**, **`+guest/dns-ips`** in **`[RULES]`** yourself if you want those sets enforced. See [INSTALL.md](INSTALL.md) and `-e dns_target_host=…` with `-i …,`.

## Part 3 — Proxmox guest firewall (run on a Proxmox node)

Copy the script to the node as in the table below if you want to run it on the node. The playbook’s flow is **`--tags resolve`** (fetch guest **`.fw`**, resolve **`apt-names.txt` / `ntp.txt` / `names-review.txt`**, stage **`dns-ips.txt`** without GAI, merge **only** the four managed IPSET bodies into **`.pve-fw-merged.<vmid>.fw`**) then **`--tags deploy`** (upload that file, `pve-firewall compile`, `systemctl reload pve-firewall`). **`[RULES]`** and all other **`[IPSET …]`** blocks are copied unchanged from the fetched file. Override merged output with **`-e dns_audit_pve_merged_fw=...`**. Reload after **deploy** ignores failure if the unit does not support reload.

| Repository file | Install to (example) |
| --- | --- |
| [lib/dns_proxmox_audit/proxmox_update_allowed_ips.py](lib/dns_proxmox_audit/proxmox_update_allowed_ips.py) (same as full package) | Copy [lib/dns_proxmox_audit](lib/dns_proxmox_audit) to `/usr/local/lib/dns_proxmox_audit/`, then `sudo env PYTHONPATH=/usr/local/lib python3 -m dns_proxmox_audit.proxmox_update_allowed_ips` |
| Guest rules | `/etc/pve/firewall/<VMID>.fw` (pass to `--firewall`) |

**Dry run (managed IPSETs — same model as the Ansible resolve step):**

```bash
env PYTHONPATH=lib python3 -m dns_proxmox_audit.proxmox_update_allowed_ips --firewall /path/to/.pve-fw.fetched.100.fw --dry-run \
  --managed-ipset apt-names:.pve-apt-names-staged.txt \
  --managed-ipset ntp-names:.pve-ntp-names-staged.txt \
  --managed-ipset reviewed-names:.pve-allowed-staged.txt \
  --managed-ipset dns-ips:.pve-dns-ips-staged.txt
```

**Dry run / apply (legacy: single `[IPSET <name>]`, default `allowed-ips`):**

```bash
cat approved-lines.txt | sudo env PYTHONPATH=/usr/local/lib python3 -m dns_proxmox_audit.proxmox_update_allowed_ips \
  --firewall /etc/pve/firewall/100.fw --dry-run
```

**Apply legacy merge (adds new IPs, keeps existing; optional `--sort`):**

```bash
cat approved-lines.txt | sudo env PYTHONPATH=/usr/local/lib python3 -m dns_proxmox_audit.proxmox_update_allowed_ips \
  --firewall /etc/pve/firewall/100.fw --input -
```

(`pve-firewall compile` runs automatically unless `--no-compile`.)

## Copy-paste: paths on the host

- `/etc/systemd/system/systemd-resolved.service.d/10-dns-audit.conf`
- `/etc/systemd/journald.conf.d/90-dns-audit-limits.conf`
- `/usr/local/lib/dns_proxmox_audit/` (Python package: run with `PYTHONPATH=/usr/local/lib` and `python3 -m dns_proxmox_audit.…`)
- `/etc/systemd/system/dns-hourly-export.service`
- `/etc/systemd/system/dns-hourly-export.timer`
- `/etc/tmpfiles.d/dns-audit.conf`
- `/var/lib/dns-audit/` (hourly `…-dns-names.txt`)
- `/etc/pve/firewall/<VMID>.fw` (Proxmox)
