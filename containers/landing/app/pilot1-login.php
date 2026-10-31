<?php
declare(strict_types=1);

header('Cache-Control: no-store, max-age=0');
header('Pragma: no-cache');
header('Referrer-Policy: no-referrer');
header('X-Content-Type-Options: nosniff');
header('X-Frame-Options: DENY');
$nonce = base64_encode(random_bytes(18));
header("Content-Security-Policy: default-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'; connect-src 'self'; script-src 'nonce-{$nonce}'");
?>
<!doctype html>
<html lang="en">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>NERDs Pilot 1 invitation</title></head>
<body>
<main>
<h1>NERDs Pilot 1</h1>
<p id="status">Checking your invitation…</p>
</main>
<script nonce="<?= htmlspecialchars($nonce, ENT_QUOTES, 'UTF-8') ?>">
(async () => {
  const secret = window.location.hash.startsWith('#') ? window.location.hash.slice(1) : '';
  // Remove the secret immediately from address bar and session history.
  window.history.replaceState(null, '', window.location.pathname);
  const output = document.getElementById('status');
  if (!/^[a-f0-9]{64}$/.test(secret)) {
    output.textContent = 'Invitation is missing or invalid. Request a new invitation from your study administrator.';
    return;
  }
  try {
    const response = await fetch('/pilot1-redeem.php', {
      method: 'POST',
      credentials: 'same-origin',
      cache: 'no-store',
      headers: {'Content-Type': 'application/json', 'X-NERDS-Invitation': '1'},
      body: JSON.stringify({token: secret})
    });
    if (!response.ok) {
      output.textContent = 'Invitation expired, already used, or unavailable. Request a new invitation.';
      return;
    }
    const data = await response.json();
    if (typeof data.redirect !== 'string' || data.redirect !== '/pilot1-intro.php') {
      throw new Error('Invalid redirect');
    }
    output.textContent = 'Opening your study introduction…';
    window.location.replace(data.redirect);
  } catch (_) {
    output.textContent = 'Unable to open the study. Contact your study administrator.';
  }
})();
</script>
</body>
</html>
