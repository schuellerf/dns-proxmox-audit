# dns-proxmox-audit

This project intends to learn which DNS names a machine actually queries over time, turn that into a **reviewed list of IP addresses** on a trusted host, and feed that into a **Proxmox VM outgoing firewall** so you can **tighten policy—mainly for outgoing traffic** (permitted destination IPs on allowed outgoing rules) instead of a wide open egress path.

**Developed and tested on Ubuntu** (Debian family with `systemd-resolved` and the apt layout and paths assumed here; other distros are untested and may need adaptation.)

**Three stages (conceptual):**

1. **Target host (audit):** Log DNS activity and write **names-only** hourly files (FQDNs you observed—no “trust the answer IP from the log” on this machine).
2. **Controller (merge and resolve):** Copy those files to the machine you trust, merge “last seen” per name, **resolve names to A/AAAA on the controller**, review the result.
3. **Proxmox (deploy):** Copy the reviewed staged file to the node, run the merge script into the guest firewall file, **reload the firewall** so the updated **outgoing-destination allowlist** (and related rules) takes effect.

## Ansible quick start (three playbooks)

Set the two hosts, `cd` into your clone of this repo, then copy-paste the `ansible-playbook` lines (they use `$TARGET_HOST` and `$PVE_HOST`).

```bash
export TARGET_HOST=your-audit.target.example.com    # ssh hostname or address for the machine under audit
export PVE_HOST=your-pve.node.example.com           # Proxmox node for the firewall playbooks
cd /path/to/dns-proxmox-audit
```

**1. Target host** — install audit tooling, resolved/journald drop-ins, hourly DNS export, static APT/NTP helper:

```bash
ansible-playbook -i "$TARGET_HOST," -b -K ansible/dns-audit.yml
```

**2. Controller** — this play uses your normal `ssh` to `$TARGET_HOST` (via **`-e dns_target_host=`** and optional inventory/SSH options), runs static export on the target, `rsync`s the audit tree into the clone, then merge/resolve (run from the host where you keep the repo):

```bash
ansible-playbook ansible/dns-audit-pull-merge.yml -e dns_target_host="$TARGET_HOST"
```

**3. Proxmox** — install the firewall helper, then (after review) deploy the staged file from this repo on the controller:

```bash
ansible-playbook -i "$PVE_HOST," -b -K ansible/proxmox-update-allowed-ips.yml --tags install

ansible-playbook -i "$PVE_HOST," -b -K ansible/proxmox-update-allowed-ips.yml --tags deploy \
  -e dns_audit_pve_staged_file="$PWD/.pve-allowed-staged.txt" \
  -e pve_vm_fw=/etc/pve/firewall/100.fw
```

More options (e.g. `dns_merge_emit_pve`, file layout): [INSTALL.md](INSTALL.md). Manual copy/install steps: [hacking.md](hacking.md).

## Outgoing access for the allowlists (hint)

To actually use the generated lists for **outgoing** rules toward mirrors and time servers, you typically need:

- **APT / HTTP(S) mirrors:** allow outbound **TCP 443** (HTTPS) and, if you still have plain HTTP sources, **TCP 80** to the relevant hosts. Name resolution to those hosts also needs **DNS (UDP/53 and often TCP/53 to the resolver you use).**
- **NTP:** allow outbound **UDP 123** to the configured NTP pool or `server` hostnames/addresses (NTP and SNTP are conventionally on UDP/123; chrony and systemd-timesyncd use that path).

Tighten source/destination in your own firewall; this repo only helps you list destination names/IPs to review.

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE).
