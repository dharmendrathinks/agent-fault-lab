# Security policy

Agent Fault Lab is experimental evaluation software, not a sandbox or security
certification. Use only synthetic tasks, local disposable databases, and models
you are authorized to run. Do not give the sample agent filesystem, shell, account,
production-service, or secret access.

When GitHub's **Report a vulnerability** button is enabled, use the private
[security-advisory form](https://github.com/dharmendrathinks/agent-fault-lab/security/advisories/new).
Private reporting needs repository-owner setup; a link alone does not enable it.
If unavailable, open an issue asking for a private security contact without posting
vulnerability details. Wait for that route before sharing a reproduction. Never
include real secrets, customer data or third-party targets.

Saved-report validation is not authentication or a hostile-file sandbox. Inspect
trusted local evidence only. Markdown can contain model/tool text; review it before
rendering or publishing outside this repository.

Only the latest published release will be eligible for security fixes once a
release exists. Until then, the repository is pre-release software and no support
window is promised.
