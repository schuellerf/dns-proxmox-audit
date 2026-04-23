# dns-proxmox-audit

This project intends to learn which DNS names a machine actually queries over time, turn that into a **reviewed list of IP addresses** on a trusted host, and feed that into a **Proxmox VM outgoing firewall** so you can **tighten policy—mainly for outgoing traffic** (permitted destination IPs on allowed outgoing rules) instead of a wide open egress path.

**Developed and tested for an Ubuntu target** (Debian family with `systemd-resolved` and the apt layout and paths assumed here; other distros are untested and may need adaptation.)

**Three steps:**

1. **Target host (audit):** Log DNS activity and write **names-only** hourly files (FQDNs you observed—no “trust the answer IP from the log” on this machine).
2. **Pull / merge / fetch:** On the audit host, merge hourly files into **`names-review.txt`**, refresh **`apt-names.txt`**, **`ntp.txt`**, and **`dns-ips.txt`** (resolver addresses from the target), and **`fetch`** all four into the repo root. **Edit `names-review.txt`** after review.
3. **Resolve and Proxmox:** With **`-i "$PVE_HOST,"`**, **`resolve`** fetches the guest **`.fw`** from the node, runs **`getaddrinfo`** on the controller from **`apt-names.txt`**, **`ntp.txt`**, and **`names-review.txt`** into three staged files, and copies **`dns-ips.txt`** to a fourth staged file **without** resolution (addresses are already IP literals from the target). It then merges **only** the **`[IPSET apt-names]`**, **`[IPSET ntp-names]`**, **`[IPSET reviewed-names]`**, and **`[IPSET dns-ips]`** bodies into **`.pve-fw-merged.<vmid>.fw`**. Every other **`[IPSET …]`** block and the entire **`[RULES]`** section are copied unchanged from the fetched file—you add **`+guest/apt-names`**, **`+guest/ntp-names`**, **`+guest/reviewed-names`**, **`+guest/dns-ips`** (or not) in Proxmox yourself. See **`.gitignore`** for local-only paths. Review the merged **`.fw`**, then **`deploy`** uploads it, runs **`pve-firewall compile`**, and reloads the firewall.

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

**2. Pull and merge** — on the target: static export + merge hourly names; **fetch** **`names-review.txt`**, **`apt-names.txt`**, **`ntp.txt`**, and **`dns-ips.txt`** into the repo (review **`names-review.txt`** before step 3):

```bash
ansible-playbook -i "$TARGET_HOST," -b -K ansible/dns-audit-pull-merge.yml -e dns_target_host="$TARGET_HOST"
```

**3. Proxmox** — **resolve** (fetch **`.fw`**, DNS staging, local merge) and **deploy** (upload merged **`.fw`** only):

Before running **resolve** step, review **`names-review.txt`**, **`apt-names.txt`**, **`ntp.txt`**, and (if you use the set in rules) **`dns-ips.txt`**

Before running **deploy** step, review the merged **`.pve-fw-merged.NNN.fw`** and make sure the **`[RULES]`** section is correct.

```bash
ansible-playbook -i "$PVE_HOST," -b -K ansible/proxmox-update-allowed-ips.yml --tags resolve \
  -e pve_vmid=100

ansible-playbook -i "$PVE_HOST," -b -K ansible/proxmox-update-allowed-ips.yml --tags deploy \
  -e pve_vmid=100
```

Guest firewall path on the node defaults to **`/etc/pve/firewall/<pve_vmid>.fw`** (default **`pve_vmid`**: 100). Override the path with **`-e pve_vm_fw=/path/to/guest.fw`** if needed.


More detail: [INSTALL.md](INSTALL.md). Manual steps: [hacking.md](hacking.md).

## Outgoing access for the allowlists (hint)

To actually use the generated lists for **outgoing** rules toward mirrors and time servers, you typically need:

- **APT / HTTP(S) mirrors:** allow outbound **TCP 443** (HTTPS) and, if you still have plain HTTP sources, **TCP 80** to the relevant hosts. Name resolution to those hosts also needs **DNS (UDP/53 and often TCP/53 to the resolver you use).**
- **NTP:** allow outbound **UDP 123** to the configured NTP pool or `server` hostnames/addresses (NTP and SNTP are conventionally on UDP/123; chrony and systemd-timesyncd use that path).

Tighten source/destination in your own firewall; this repo only helps you list destination names/IPs to review and update regularly.

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE).
