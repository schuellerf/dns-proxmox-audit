# DNS audit + Proxmox `allowed-ips` — manual install and operations

Use this if you are **not** using Ansible (see [INSTALL.md](INSTALL.md) for playbooks) or for troubleshooting.

All paths are **on the target host** (the machine running `systemd-resolved` for the audit, and a Proxmox node for the firewall tool).

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
| [lib/dns-hourly-export.py](lib/dns-hourly-export.py) | `/usr/local/lib/dns-proxmox-audit/dns-hourly-export.py` (mode `0755`) |
| [systemd/dns-hourly-export.service](systemd/dns-hourly-export.service) | `/etc/systemd/system/dns-hourly-export.service` |
| [systemd/dns-hourly-export.timer](systemd/dns-hourly-export.timer) | `/etc/systemd/system/dns-hourly-export.timer` |
| [systemd/tmpfiles.d/dns-audit.conf](systemd/tmpfiles.d/dns-audit.conf) | `/etc/tmpfiles.d/dns-audit.conf` (or `/usr/lib/tmpfiles.d/dns-audit.conf`) |

**Output directory (hourly files):** `/var/lib/dns-audit/`

**Filename pattern:** e.g. `2026032914_+0100-dns-requests.txt`: wall-clock **start** of the hour, `_`, then `strftime("%z")` for that instant (`+0100`, `-0500`, …). If `%z` is empty, the code uses `+0000`. DST is in the offset segment.

**Commands:**

```bash
sudo install -d -m 0755 /usr/local/lib/dns-proxmox-audit
sudo install -m 0755 lib/dns-hourly-export.py /usr/local/lib/dns-proxmox-audit/
sudo install -d -m 0755 /etc/tmpfiles.d
sudo install -m 0644 systemd/tmpfiles.d/dns-audit.conf /etc/tmpfiles.d/dns-audit.conf
sudo systemd-tmpfiles --create /etc/tmpfiles.d/dns-audit.conf
sudo install -m 0644 systemd/dns-hourly-export.service /etc/systemd/system/
sudo install -m 0644 systemd/dns-hourly-export.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now dns-hourly-export.timer
```

**Manual run (last completed local hour):**

```bash
sudo /usr/local/lib/dns-proxmox-audit/dns-hourly-export.py --output-dir /var/lib/dns-audit
```

**Time zone for filenames:** the script uses `datetime.now().astimezone().tzinfo` when `--timezone local` (default). For a named zone: `--timezone Europe/Berlin`.

## Part 3 — Proxmox guest firewall (run on a Proxmox node)

The helper can be installed with `ansible-playbook` and [ansible/proxmox-update-allowed-ips.yml](ansible/proxmox-update-allowed-ips.yml) (see [INSTALL.md](INSTALL.md)), or with `install` / copy as below.

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
- `/usr/local/lib/dns-proxmox-audit/dns-hourly-export.py`
- `/usr/local/lib/dns-proxmox-audit/proxmox-update-allowed-ips.py`
- `/etc/systemd/system/dns-hourly-export.service`
- `/etc/systemd/system/dns-hourly-export.timer`
- `/etc/tmpfiles.d/dns-audit.conf`
- `/var/lib/dns-audit/` (hourly `…_+0100-…` / `…_-0500-…` — see filename pattern above)
- `/etc/pve/firewall/<VMID>.fw` (Proxmox)
