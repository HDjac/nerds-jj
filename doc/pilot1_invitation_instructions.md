# NERDs Pilot 1 — single-use browser invitations

This bundle implements one-time invitation redemption using your existing
`fuzz_pilot` sessions, PostgreSQL-backed PHP authorization, and Nginx proxy.

Contents:

- `db/migrations/003_pilot1_invitations.sql`: single-use invitation table and
  least-privilege atomic redemption function.
- `scripts/pilot1_invite.py`: administrator-only invitation generator. Uses
  Docker and PostgreSQL from your WSL host; never expose it to participants.
- `containers/landing/app/pilot1-login.php`: browser entry page; reads the token
  from the URL fragment and posts it to the redemption endpoint.
- `containers/landing/app/pilot1-redeem.php`: server creates a fresh `Secure`,
  `HttpOnly`, `SameSite=Lax`, `__Host-` browser cookie.

Run `php -l` on both PHP files and compile-check Python before deployment.
Apply migration 003 against `notebook` as postgres. Then rebuild **only**
`landing-server` and recreate the local private `nerds-pilot1-php` container,
keeping `--use-aliases`; do not start the legacy public landing/Nginx services.

The existing test credential is revoked when an invitation is redeemed.
This is a local pilot implementation; do not share remote tester invitations
until TLS trust, network access controls, legacy routes, and auditing have
been reviewed. Tokens are sensitive: never put them in Git, chats, screenshots,
server logs, or a public website. HTTPS is mandatory.
