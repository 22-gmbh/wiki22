# Code signing policy

Status: **application submitted on 2026-10-02; awaiting assessment, not approved or signed by SignPath yet**.

Wiki22 is maintained by 22 GmbH. The proposed maintainer, reviewer and signing
approver is Flavio Cristiano, GitHub account `flaviocristiano-collab`.
The final roles and multifactor authentication must be confirmed in SignPath.

Requested service: free code signing provided by SignPath.io, certificate by
SignPath Foundation. This attribution describes the requested program, not
an existing grant or endorsement.

Release artifacts must be compiled from the public source repository on
GitHub-hosted runners and uploaded as GitHub Actions artifacts before a
signing request. Production signing requires approval by the designated
maintainer. Requests must originate from the protected release process.

Only first-party Wiki22 executables are in scope. Third-party runtime files
retain their own signatures and licensing. Signed artifacts must not be
modified after signing. Their SHA-256 checksums must be generated afterward.

The initial artifact configuration covers `Wiki22.exe`. The historical
multi-gigabyte installer is not submitted for signing. Signing the launcher
does not imply that the historical installer is signed or that a native
Windows compatibility test has passed.

The application does not transfer information to other networked systems
unless requested by the user operating it; see [Privacy](PRIVACY.md) for
the local application and user-initiated source links and downloads.

References:
- https://signpath.org/terms.html
- https://docs.signpath.io/trusted-build-systems/github
