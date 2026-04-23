# dns-proxmox-audit

This project intends to learn which DNS names a machine actually queries over time, turn that into a **reviewed list of IP addresses** on a trusted host, and feed that into a **Proxmox VM outgoing firewall** so you can **tighten policy—mainly for outgoing traffic** (permitted destination IPs on allowed outgoing rules) instead of a wide open egress path.

**Three stages:**

1. **Audit host (journal):** Log DNS activity and write **names-only** hourly files (FQDNs you observed—no “trust the answer IP from the log” on this machine).
2. **Controller (merge and resolve):** Copy those files to the machine you trust, merge “last seen” per name, **resolve names to A/AAAA on the controller**, review the result.
3. **Proxmox (deploy):** Copy the reviewed staged file to the node, run the merge script into the guest firewall file, **reload the firewall** so the updated **outgoing-destination allowlist** (and related rules) takes effect.

Details and commands: [INSTALL.md](INSTALL.md). Manual steps: [hacking.md](hacking.md).

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE).
