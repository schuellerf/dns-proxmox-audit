# DNS audit + Proxmox `allowed-ips` — install

**Journal audit host** ([ansible/dns-audit.yml](ansible/dns-audit.yml)): `systemd-resolved` + journald limits, hourly export to `/var/lib/dns-audit/`. **Proxmox node** (optional, separate play): only the firewall helper script; run it when you want that file on a PVE host — it does not start any service or timer there.

**Prerequisites:** `ansible-playbook` on the control node; SSH and `become` to each target as usual.

### Journal audit (`dns-audit.yml`)

| Source (in this repo) | On the target host |
| --- | --- |
| [systemd/systemd-resolved.service.d/10-dns-audit.conf](systemd/systemd-resolved.service.d/10-dns-audit.conf) | `/etc/systemd/system/systemd-resolved.service.d/10-dns-audit.conf` |
| [systemd/journald.conf.d/90-dns-audit-limits.conf](systemd/journald.conf.d/90-dns-audit-limits.conf) | `/etc/systemd/journald.conf.d/90-dns-audit-limits.conf` |
| [lib/dns-hourly-export.py](lib/dns-hourly-export.py) | `/usr/local/lib/dns-proxmox-audit/dns-hourly-export.py` |
| [systemd/dns-hourly-export.service](systemd/dns-hourly-export.service), [systemd/dns-hourly-export.timer](systemd/dns-hourly-export.timer) | `/etc/systemd/system/` |
| [systemd/tmpfiles.d/dns-audit.conf](systemd/tmpfiles.d/dns-audit.conf) | `/etc/tmpfiles.d/dns-audit.conf` |

```bash
cd /path/to/dns-proxmox-audit
ansible-playbook -i 'JOURNAL_HOST,' -b -K ansible/dns-audit.yml
```

### Proxmox helper only (`proxmox-update-allowed-ips.yml`)

| Source | On the Proxmox node |
| --- | --- |
| [lib/proxmox-update-allowed-ips.py](lib/proxmox-update-allowed-ips.py) | `/usr/local/lib/dns-proxmox-audit/proxmox-update-allowed-ips.py` |

```bash
cd /path/to/dns-proxmox-audit
ansible-playbook -i 'PVE_HOST,' -b -K ansible/proxmox-update-allowed-ips.yml
```

Manual `install` / `systemctl` and CLI examples: [hacking.md](hacking.md).
