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
| [lib/audit_export_common.py](lib/audit_export_common.py) | `/usr/local/lib/dns-proxmox-audit/audit_export_common.py` (mode `0644`) |
| [lib/dns_audit_names_lib.py](lib/dns_audit_names_lib.py) | `/usr/local/lib/dns-proxmox-audit/dns_audit_names_lib.py` (mode `0644`) |
| [lib/dns-merge-hourly-names.py](lib/dns-merge-hourly-names.py) | `/usr/local/lib/dns-proxmox-audit/dns-merge-hourly-names.py` (mode `0755`) |
| [lib/dns-hourly-export.py](lib/dns-hourly-export.py) | `/usr/local/lib/dns-proxmox-audit/dns-hourly-export.py` (mode `0755`) |
| [lib/static-endpoints-export.py](lib/static-endpoints-export.py) | `/usr/local/lib/dns-proxmox-audit/static-endpoints-export.py` (mode `0755`) |
| [systemd/dns-hourly-export.service](systemd/dns-hourly-export.service) | `/etc/systemd/system/dns-hourly-export.service` |
| [systemd/dns-hourly-export.timer](systemd/dns-hourly-export.timer) | `/etc/systemd/system/dns-hourly-export.timer` |
| [systemd/tmpfiles.d/dns-audit.conf](systemd/tmpfiles.d/dns-audit.conf) | `/etc/tmpfiles.d/dns-audit.conf` (or `/usr/lib/tmpfiles.d/dns-audit.conf`) |

**Output directory (hourly files):** `/var/lib/dns-audit/`

**Filename pattern:** e.g. `2026032914+0100-dns-names.txt`: wall-clock **start** of the hour, then `strftime("%z")` (no separator before the offset), as in [audit_export_common.filename_for_hour_start](lib/audit_export_common.py). Each file lists **one FQDN per line** (no IPs; used for names-seen-only audit).

**Static lists (not hourly):** `apt-names.txt` and `ntp.txt` in the same directory — **HTTP(S) mirror hostnames** from `/etc/apt` and **NTP/chrony/timesyncd** peers (including `/etc/systemd/timesyncd.conf` and **`/etc/systemd/timesyncd.conf.d/*.conf`**). Regenerated when you run [ansible/dns-audit-pull-merge.yml](ansible/dns-audit-pull-merge.yml) (static step on the target) or manually below. NTP from DHCP is not read; edge Deb822 or mirror URL formats may need manual checks.

**Commands:**

```bash
sudo install -d -m 0755 /usr/local/lib/dns-proxmox-audit
sudo install -m 0644 lib/audit_export_common.py /usr/local/lib/dns-proxmox-audit/
sudo install -m 0644 lib/dns_audit_names_lib.py /usr/local/lib/dns-proxmox-audit/
sudo install -m 0755 lib/dns-merge-hourly-names.py /usr/local/lib/dns-proxmox-audit/
sudo install -m 0755 lib/dns-hourly-export.py /usr/local/lib/dns-proxmox-audit/
sudo install -m 0755 lib/static-endpoints-export.py /usr/local/lib/dns-proxmox-audit/
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
sudo /usr/local/lib/dns-proxmox-audit/dns-hourly-export.py
```

**Last completed local hour** (same as the timer service):

```bash
sudo /usr/local/lib/dns-proxmox-audit/dns-hourly-export.py --previous-hour
```

**Time zone for filenames:** the script uses `datetime.now().astimezone().tzinfo` when `--timezone local` (default). For a named zone: `--timezone Europe/Berlin`.

**Static APT + NTP host lists (manual, on the target, root):**

```bash
sudo /usr/local/lib/dns-proxmox-audit/static-endpoints-export.py
```

## Part 2b — Pull, merge, fetch

[ansible/dns-audit-pull-merge.yml](ansible/dns-audit-pull-merge.yml) runs **`dns-merge-hourly-names.py`** on the **target**, then **`fetch`es** **`names-review.txt`** into the repo as **`names-review.txt`** (fetch uses **`become`** because **`/var/lib/dns-audit`** is **`0750`**). Re-run [ansible/dns-audit.yml](ansible/dns-audit.yml) on the target after pulling new `lib/` files.

**Manual on the target** (merge hourly files under the audit dir):

```bash
sudo /usr/local/lib/dns-proxmox-audit/dns-merge-hourly-names.py
```

**Manual on the controller** (after review; from repo root, defaults `names-review.txt` → `.pve-allowed-staged.txt`):

```bash
python3 lib/dns-resolve-names-for-pve.py
# or: python3 lib/dns-resolve-names-for-pve.py --ipv4-only
```

Review **`names-review.txt`** (`name # last request: YYYYMMDDHH+0100`), then run the resolver (or [ansible/proxmox-update-allowed-ips.yml](ansible/proxmox-update-allowed-ips.yml) **`--tags resolve`**). Edit **`.pve-allowed-staged.txt`** if needed (IP # name last request: …). For APT/NTP hostnames, use `apt-names.txt` / `ntp.txt` on the target under the audit dir (from static export) or re-run the static export. See [INSTALL.md](INSTALL.md) and `-e dns_target_host=…` with `-i …,`.

## Part 3 — Proxmox guest firewall (run on a Proxmox node)

Install the helper with [ansible/proxmox-update-allowed-ips.yml](ansible/proxmox-update-allowed-ips.yml) `--tags install`, or copy the script as below. **Resolve** then **deploy**: `--tags resolve,deploy` (defaults use **`.pve-allowed-staged.txt`** in the repo; override with `-e dns_audit_pve_staged_file=...`). That run also does `systemctl reload pve-firewall` (errors ignored if the unit does not support reload).

| Repository file | Install to (example) |
| --- | --- |
| [lib/proxmox-update-allowed-ips.py](lib/proxmox-update-allowed-ips.py) | `/usr/local/lib/dns-proxmox-audit/proxmox-update-allowed-ips.py` (mode `0755`) |
| Guest rules | `/etc/pve/firewall/<VMID>.fw` (pass to `--firewall`) |

**Dry run:**

```bash
cat approved-lines.txt | sudo /usr/local/lib/dns-proxmox-audit/proxmox-update-allowed-ips.py \
  --firewall /etc/pve/firewall/100.fw --dry-run
```

**Apply (adds new IPs, keeps existing; optional `--sort`):**

```bash
cat approved-lines.txt | sudo /usr/local/lib/dns-proxmox-audit/proxmox-update-allowed-ips.py \
  --firewall /etc/pve/firewall/100.fw --input - 
```

(Use a real file path; `pve-firewall compile` is run automatically unless `--no-compile`.)

## Copy-paste: paths on the host

- `/etc/systemd/system/systemd-resolved.service.d/10-dns-audit.conf`
- `/etc/systemd/journald.conf.d/90-dns-audit-limits.conf`
- `/usr/local/lib/dns-proxmox-audit/dns-merge-hourly-names.py`
- `/usr/local/lib/dns-proxmox-audit/dns-hourly-export.py`
- `/usr/local/lib/dns-proxmox-audit/static-endpoints-export.py`
- `/usr/local/lib/dns-proxmox-audit/proxmox-update-allowed-ips.py`
- `/etc/systemd/system/dns-hourly-export.service`
- `/etc/systemd/system/dns-hourly-export.timer`
- `/etc/tmpfiles.d/dns-audit.conf`
- `/var/lib/dns-audit/` (hourly `…-dns-names.txt`)
- `/etc/pve/firewall/<VMID>.fw` (Proxmox)
