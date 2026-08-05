import { serve } from "https://deno.land/std@0.168.0/http/server.ts";

// Utility for Base64Url encoding
function base64UrlEncode(data: Uint8Array | string): string {
  let uint8Array: Uint8Array;
  if (typeof data === "string") {
    uint8Array = new TextEncoder().encode(data);
  } else {
    uint8Array = data;
  }
  let base64 = btoa(String.fromCharCode(...uint8Array));
  return base64.replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

// Convert PEM string to CryptoKey
async function importPrivateKey(pem: string): Promise<CryptoKey> {
  const pemHeader = "-----BEGIN PRIVATE KEY-----";
  const pemFooter = "-----END PRIVATE KEY-----";
  const pemRsaHeader = "-----BEGIN RSA PRIVATE KEY-----";
  const pemRsaFooter = "-----END RSA PRIVATE KEY-----";
  
  let base64 = pem;
  if (pem.includes(pemHeader)) {
    base64 = pem.substring(pem.indexOf(pemHeader) + pemHeader.length, pem.indexOf(pemFooter));
  } else if (pem.includes(pemRsaHeader)) {
    base64 = pem.substring(pem.indexOf(pemRsaHeader) + pemRsaHeader.length, pem.indexOf(pemRsaFooter));
  }
  base64 = base64.replace(/\s+/g, "");

  const binaryString = atob(base64);
  const binaryLen = binaryString.length;
  const bytes = new Uint8Array(binaryLen);
  for (let i = 0; i < binaryLen; i++) {
    bytes[i] = binaryString.charCodeAt(i);
  }

  return await crypto.subtle.importKey(
    "pkcs8",
    bytes,
    {
      name: "RSASSA-PKCS1-v1_5",
      hash: { name: "SHA-256" },
    },
    false,
    ["sign"]
  );
}

serve(async (req) => {
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "Method not allowed" }), {
      status: 405,
      headers: { "Content-Type": "application/json" },
    });
  }

  try {
    // 1. Verify Authorization Header (Basic check for Bearer token)
    const authHeader = req.headers.get("Authorization");
    if (!authHeader || !authHeader.startsWith("Bearer ")) {
      return new Response(JSON.stringify({ error: "Unauthorized" }), {
        status: 401,
        headers: { "Content-Type": "application/json" },
      });
    }
    
    // In a full implementation, you would verify the JWT with Supabase Auth
    // and fetch claims from the database based on the authenticated user.

    // 2. Parse request payload
    const body = await req.json();
    const {
      challenge,
      configuration_digest,
      process_name,
      target_pid,
      mode = "ProcessMode",
      product = "neko-family-proxy",
      scope = "proxy:start",
      sub, 
      sid,
      iid,
      lid
    } = body;

    if (!challenge || !configuration_digest || !target_pid) {
      return new Response(JSON.stringify({ error: "Missing required parameters" }), {
        status: 400,
        headers: { "Content-Type": "application/json" },
      });
    }

    // 3. Get Private Key from environment variables
    const privateKeyPem = Deno.env.get("RS256_PRIVATE_KEY");
    const kid = Deno.env.get("RS256_KID") || "neko-prod-key-1";

    if (!privateKeyPem) {
      console.error("Missing RS256_PRIVATE_KEY in environment variables");
      return new Response(JSON.stringify({ error: "Backend configuration error" }), {
        status: 500,
        headers: { "Content-Type": "application/json" },
      });
    }

    const privateKey = await importPrivateKey(privateKeyPem);

    // 4. Construct JWT Header and Payload
    const header = {
      alg: "RS256",
      typ: "neko-launch+jwt",
      kid: kid
    };

    const now = Math.floor(Date.now() / 1000);
    const payload = {
      iss: "neko-backend",
      aud: "neko-proxy-core",
      product: product,
      scope: scope,
      mode: mode,
      iat: now,
      nbf: now,
      exp: now + 30, // 30 seconds lifetime
      jti: crypto.randomUUID(),
      cfg: configuration_digest,
      challenge: challenge,
      target_pid: target_pid,
      sub: sub || "mock-sub", 
      sid: sid || "mock-sid",
      iid: iid || "mock-iid",
      lid: lid || "mock-lid"
    };

    // 5. Sign the JWT
    const encodedHeader = base64UrlEncode(JSON.stringify(header));
    const encodedPayload = base64UrlEncode(JSON.stringify(payload));
    const signingInput = `${encodedHeader}.${encodedPayload}`;
    
    const signatureBytes = await crypto.subtle.sign(
      "RSASSA-PKCS1-v1_5",
      privateKey,
      new TextEncoder().encode(signingInput)
    );
    
    const encodedSignature = base64UrlEncode(new Uint8Array(signatureBytes));
    const token = `${signingInput}.${encodedSignature}`;

    // 6. Return the signed permit
    return new Response(
      JSON.stringify({ permit: token }),
      {
        headers: { "Content-Type": "application/json" },
      },
    );
  } catch (error) {
    console.error("Error issuing permit:", error);
    return new Response(JSON.stringify({ error: "Internal server error" }), {
      status: 500,
      headers: { "Content-Type": "application/json" },
    });
  }
});
