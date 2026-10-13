# Security and execution scope

Closure's preview executes **trusted local engineering projects**. Review analysis commands and dependencies before using `--trusted`. The runner can access the host account's files, network, and installed tools. Source snapshots, checksums and process cleanup support evidence integrity; they are not a sandbox.

The viewer binds to loopback only. It uses local Host/Origin checks, a session write token, guarded edits and serialized operations. It has no user accounts, multiuser isolation, remote execution service, or production hosting support. Do not proxy or expose its execution API to a network. A public website may serve the specification, source downloads, or exported static reports.

Report corruption and ordinary bugs through [GitHub issues](https://github.com/keystoneintelligence/closure/issues). For suspected vulnerabilities, use [GitHub private vulnerability reporting](https://github.com/keystoneintelligence/closure/security/advisories/new), also available through the repository's Security tab. Do not put sensitive reproductions in public issues. The release review verifies that private reporting is enabled before publication.

The preview support scope is the latest `0.1.0aN` candidate on tested Windows/Linux environments. There is no response-time SLA. Maintainers should acknowledge private reports, reproduce safely, coordinate a fix and advisory, and retire affected preview builds. Report the version, OS, minimal reproduction, affected trust boundary and potential impact without including private project artifacts.
