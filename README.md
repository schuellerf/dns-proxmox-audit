# dns-proxmox-audit

This project intends to learn which DNS names a machine actually queries over time, turn that into a **reviewed list of IP addresses** on a trusted host, and feed that into a **Proxmox VM outgoing firewall** so you can **tighten policy—mainly for outgoing traffic** (permitted destination IPs on allowed outgoing rules) instead of a wide open egress path.

**Developed and tested on Ubuntu** (Debian family with `systemd-resolved` and the apt layout and paths assumed here; other distros are untested and may need adaptation.)

**Three steps:**

1. **Target host (audit):** Log DNS activity and write **names-only** hourly files (FQDNs you observed—no “trust the answer IP from the log” on this machine).
2. **Pull / merge / fetch:** On the audit host, merge hourly files into **`names-review.txt`** and **`fetch`** that file into the repo as **`names-review.txt`** (repo root). **Edit it** after review.
3. **Resolve and Proxmox:** On the **controller**, run **`getaddrinfo`** to build **`.pve-allowed-staged.txt`**, then copy it to the node and merge into the guest firewall (**`resolve`** + **`deploy`** tags).

## Ansible quick start (three playbooks)

Set the two hosts, `cd` into your clone of this repo, then copy-paste the `ansible-playbook` lines (they use `$TARGET_HOST` and `$PVE_HOST`).

```bash
export TARGET_HOST=your-audit.target.example.com    # ssh hostname or address for the machine under audit
export PVE_HOST=your-pve.node.example.com           # Proxmox node for the firewall playbooks
cd /path/to/dns-proxmox-audit
```

**1. Target host** — install audit tooling, resolved/journald drop-ins, hourly DNS export, static APT/NTP helper, merge script:

```bash
ansible-playbook -i "$TARGET_HOST," -b -K ansible/dns-audit.yml
```

**2. Pull and merge** — on the target: static export + merge hourly names; **fetch** **`names-review.txt`** into the repo (review and edit it before step 3):

```bash
ansible-playbook -i "$TARGET_HOST," -b -K ansible/dns-audit-pull-merge.yml -e dns_target_host="$TARGET_HOST"
```

**3. Proxmox** — install the firewall helper once; then **resolve** (controller DNS) and **deploy** to the node:

```bash
ansible-playbook -i "$PVE_HOST," -b -K ansible/proxmox-update-allowed-ips.yml --tags install

ansible-playbook -i "$PVE_HOST," -b -K ansible/proxmox-update-allowed-ips.yml --tags resolve,deploy \
  -e pve_vm_fw=/etc/pve/firewall/100.fw
```

Default paths under the repo are **`names-review.txt`** and **`.pve-allowed-staged.txt`**. Use **`-e dns_resolve_ipv4_only=true`** on the resolve/deploy playbook if you want IPv4 only. Override paths with **`-e dns_audit_names_review=…`**, **`-e dns_audit_pve_staged=…`** (resolve step) or **`-e dns_audit_pve_staged_file=…`** (deploy copy source). Fetch uses **`become`** so the controller can read **`/var/lib/dns-audit`** (mode `0750`).

More detail: [INSTALL.md](INSTALL.md). Manual steps: [hacking.md](hacking.md).

## Outgoing access for the allowlists (hint)

To actually use the generated lists for **outgoing** rules toward mirrors and time servers, you typically need:

- **APT / HTTP(S) mirrors:** allow outbound **TCP 443** (HTTPS) and, if you still have plain HTTP sources, **TCP 80** to the relevant hosts. Name resolution to those hosts also needs **DNS (UDP/53 and often TCP/53 to the resolver you use).**
- **NTP:** allow outbound **UDP 123** to the configured NTP pool or `server` hostnames/addresses (NTP and SNTP are conventionally on UDP/123; chrony and systemd-timesyncd use that path).

Tighten source/destination in your own firewall; this repo only helps you list destination names/IPs to review.

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE).
