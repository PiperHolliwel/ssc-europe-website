/**
 * Minimal GitHub OAuth proxy for Decap CMS, deployed as a single Cloudflare
 * Worker. Decap's "github" backend needs somewhere to run the OAuth
 * handshake with GitHub (client_secret can never be exposed in the browser);
 * normally that's Netlify — this Worker does the same two steps ourselves:
 *
 *   GET /auth       -> redirects the popup window to GitHub's login page
 *   GET /callback   -> GitHub redirects back here with a ?code=..., which
 *                       this exchanges for an access token, then hands that
 *                       token back to the Decap CMS admin page via the
 *                       postMessage handshake it expects.
 *
 * Setup (see README section "Setting up the content editor"):
 *   1. Deploy this file as a new Cloudflare Worker (paste into the
 *      dashboard's Quick Edit editor — no build step needed).
 *   2. Create a GitHub OAuth App (github.com/settings/developers) with its
 *      "Authorization callback URL" set to: https://<this-worker>.workers.dev/callback
 *   3. In the Worker's Settings -> Variables and Secrets, add two secrets:
 *        GITHUB_CLIENT_ID      = the OAuth App's Client ID
 *        GITHUB_CLIENT_SECRET  = a generated Client Secret
 *   4. In admin_src/config.yml, set backend.base_url to this Worker's URL.
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    if (url.pathname === "/auth") {
      return handleAuth(url, env);
    }
    if (url.pathname === "/callback") {
      return handleCallback(url, request, env);
    }
    return new Response("Decap CMS OAuth proxy for ssc-europe-website. Routes: /auth, /callback", {
      status: 200,
      headers: { "content-type": "text/plain" },
    });
  },
};

function randomState() {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, (b) => b.toString(16).padStart(2, "0")).join("");
}

async function handleAuth(url, env) {
  if (!env.GITHUB_CLIENT_ID) {
    return new Response("Missing GITHUB_CLIENT_ID secret on this Worker.", { status: 500 });
  }
  const state = randomState();
  const redirectUri = `${url.origin}/callback`;
  const authorizeUrl = new URL("https://github.com/login/oauth/authorize");
  authorizeUrl.searchParams.set("client_id", env.GITHUB_CLIENT_ID);
  authorizeUrl.searchParams.set("redirect_uri", redirectUri);
  authorizeUrl.searchParams.set("scope", "repo,user");
  authorizeUrl.searchParams.set("state", state);

  return new Response(null, {
    status: 302,
    headers: {
      Location: authorizeUrl.toString(),
      // short-lived, HttpOnly cookie so /callback can check the state came
      // from a request this Worker actually issued (basic CSRF guard)
      "Set-Cookie": `oauth_state=${state}; Max-Age=600; Path=/; HttpOnly; Secure; SameSite=Lax`,
    },
  });
}

function getCookie(request, name) {
  const header = request.headers.get("Cookie") || "";
  const match = header.match(new RegExp(`(?:^|; )${name}=([^;]+)`));
  return match ? match[1] : null;
}

async function handleCallback(url, request, env) {
  const code = url.searchParams.get("code");
  const state = url.searchParams.get("state");
  const expectedState = getCookie(request, "oauth_state");

  if (!code || !state || !expectedState || state !== expectedState) {
    return new Response("OAuth state mismatch or missing code — please try logging in again.", {
      status: 400,
    });
  }
  if (!env.GITHUB_CLIENT_ID || !env.GITHUB_CLIENT_SECRET) {
    return new Response("Missing GITHUB_CLIENT_ID / GITHUB_CLIENT_SECRET secrets on this Worker.", {
      status: 500,
    });
  }

  const tokenResp = await fetch("https://github.com/login/oauth/access_token", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      accept: "application/json",
    },
    body: JSON.stringify({
      client_id: env.GITHUB_CLIENT_ID,
      client_secret: env.GITHUB_CLIENT_SECRET,
      code,
      redirect_uri: `${url.origin}/callback`,
    }),
  });

  if (!tokenResp.ok) {
    return new Response("GitHub token exchange failed.", { status: 502 });
  }
  const tokenData = await tokenResp.json();
  if (!tokenData.access_token) {
    return new Response(
      `GitHub did not return an access token: ${tokenData.error_description || JSON.stringify(tokenData)}`,
      { status: 502 }
    );
  }

  const payload = JSON.stringify({ token: tokenData.access_token, provider: "github" });

  // The handshake Decap CMS's admin page expects from the OAuth popup:
  //   1. popup -> opener: "authorizing:github"
  //   2. opener replies (any message); popup learns the trusted origin from it
  //   3. popup -> opener: "authorization:github:success:<payload JSON>"
  const html = `<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Authorizing…</title></head>
<body>
<p>Signing you in…</p>
<script>
(function() {
  function receiveMessage(e) {
    window.opener.postMessage(
      'authorization:github:success:${payload.replace(/'/g, "\\'")}',
      e.origin
    );
    window.removeEventListener("message", receiveMessage, false);
  }
  window.addEventListener("message", receiveMessage, false);
  window.opener.postMessage("authorizing:github", "*");
})();
</script>
</body></html>`;

  return new Response(html, {
    status: 200,
    headers: {
      "content-type": "text/html; charset=utf-8",
      "Set-Cookie": "oauth_state=; Max-Age=0; Path=/",
    },
  });
}
