# Provider pages re-read by the engineering manager, 2026-11-14 (execution session), verbatim excerpts

## code.claude.com/docs/en/legal-and-compliance
- "OAuth authentication is intended exclusively for purchasers of Claude Free, Pro, Max, Ultra, Team, and Enterprise subscription plans and is designed to support ordinary use of Claude Code and other native Anthropic applications."
- "Developers building products or services that interact with Claude's capabilities, including those using the Agent SDK, should use API key authentication through Claude Console or a supported cloud provider. Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, Max, or Ultra plan credentials on behalf of their users. Moreover, developers may not collect, store, or intermediate Claude.ai credentials or session tokens — sign-in to a Claude account must complete through Anthropic's own flow."
- "Nor does it prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription, including where a platform hosts Claude Code as described under *Can customers offer Claude Code in their products?* above."
- "The Claude Code binary must not be modified. Claude Code must be installed and run as published by Anthropic, and customers may not remove, disable, or restrict any authentication method built into it (including methods that permit signing in with a Claude account or the user's own API key)."
- "Customers may not pay for, resell, or intermediate Claude usage on their end users' behalf. Each end user must authenticate with their own Anthropic API key, Claude subscription plan credentials, or 3P inference provider credential ..."
- "Advertised usage limits for Pro, Max, and Ultra plans assume ordinary, individual usage of Claude Code and the Agent SDK."
- "Anthropic reserves the right to take measures to enforce these restrictions and may do so without prior notice."

## code.claude.com/docs/en/agent-sdk/overview
- "Unless previously approved, Anthropic does not allow third party developers to offer claude.ai login or rate limits for their products, including agents built on the Claude Agent SDK. Use the API key authentication methods described in the Quickstart instead."
- "Agent SDK | A library that runs the Claude Code binary, with Claude Code's capabilities ..."
- "Use of the Claude Agent SDK is governed by Anthropic's Commercial Terms of Service ..."

## code.claude.com/docs/en/authentication
- "For CI pipelines, scripts, or other environments where interactive browser login isn't available, generate a one-year OAuth token with `claude setup-token`"
- "The command opens the same browser authorization flow as `/login`, and the token prints to the terminal after you approve access in the browser. It does not save the token anywhere; copy it and set it as the `CLAUDE_CODE_OAUTH_TOKEN` environment variable wherever you want to authenticate"
- "This token authenticates with your Claude subscription and requires a Pro, Max, Ultra, Team, or Enterprise plan. It can only make model requests, so it can't establish Remote Control sessions or fetch claude.ai connectors. MCP servers you configure locally still work."
- "Bare mode does not read `CLAUDE_CODE_OAUTH_TOKEN`. If your script passes `--bare`, authenticate with `ANTHROPIC_API_KEY` or an `apiKeyHelper` instead."
- Precedence: 1 cloud provider vars; 2 ANTHROPIC_AUTH_TOKEN; 3 ANTHROPIC_API_KEY; 4 apiKeyHelper; 5 CLAUDE_CODE_OAUTH_TOKEN; 6 profiles/federation; 7 /login.
- "`apiKeyHelper`, `ANTHROPIC_API_KEY`, and `ANTHROPIC_AUTH_TOKEN` apply to the CLI and the surfaces that wrap it, including the VS Code extension, the Agent SDK, and GitHub Actions."

## EM reading (for the Owner's own reading under OA-31 (d); not a substitute)
Supported: setup-token is the documented method for non-browser environments (CI, scripts); the token goes into the
environment "wherever you want to authenticate"; the binary is run unmodified; sign-in completes through Anthropic's
own flow on the host. Tension to disclose: the Agent SDK note and the "Developers ..." paragraph address third parties
offering claude.ai login *for their products* / on behalf of *their users*, and storing others' tokens. Here the
developer, operator and sole end user are the Owner, the harness is not offered to anyone, and the stored token is the
Owner's own, for his own use. That reading is the Owner's to make (OA-31 (d)); if the harness were ever offered to
other users, API-key authentication (the brokered profile) applies. Ordinary individual usage is assumed by plan
limits. New check carried to E-05.11: the pinned adapter must not launch the CLI with `--bare` (bare mode ignores
CLAUDE_CODE_OAUTH_TOKEN).
