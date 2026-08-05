# Backend Permit Issuer - Walkthrough & Setup

The Supabase Edge Function `issue_launch_permit` has been implemented and is ready for production use. This function will read the RS256 private key from the secure environment variables, validate the incoming request, and sign a JWT permit that can be verified by `StrictLaunchPermitVerifier` in Core.

## 1. Edge Function Implementation

The function was created at [`E:\Github\Neko-Family-Proxy\supabase\functions\issue_launch_permit\index.ts`](file:///E:/Github/Neko-Family-Proxy/supabase/functions/issue_launch_permit/index.ts).

**Key Features:**
- **Auth Validation:** Validates the presence of the Bearer token.
- **Payload Parsing:** Extracts `challenge`, `cfg` (configuration digest), `target_pid`, and other required claims.
- **Secure Key Loading:** Loads `RS256_PRIVATE_KEY` and `RS256_KID` from Supabase Secrets (`Deno.env.get`).
- **Standardized JWT:** Signs the payload strictly adhering to the `neko-launch+jwt` spec (`RS256`, correct claims).

## 2. Generate and Configure RS256 Key Pair

> [!IMPORTANT]
> You must generate the RS256 key pair locally and inject the private key directly into Supabase Secrets. Do not commit the private key to any file.

Run the following commands in your terminal to generate the keys (requires OpenSSL):

```bash
# 1. Generate the RSA 2048-bit Private Key
openssl genrsa -out private.pem 2048

# 2. Extract the Public Key (for Core's StrictLaunchPermitVerifier)
openssl rsa -in private.pem -pubout -out public.pem

# 3. View the Private Key (copy the output for the next step)
cat private.pem
```

### Injecting into Supabase Secrets
Once you have the `private.pem` content, inject it into your Supabase project (both local and production):

**For Local Development:**
Create a `.env.local` file inside the `supabase/` directory (make sure it's in your `.gitignore`):
```env
RS256_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
RS256_KID="neko-prod-key-1"
```

**For Production:**
Use the Supabase CLI to set the secrets securely:
```bash
supabase secrets set RS256_PRIVATE_KEY="-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----"
supabase secrets set RS256_KID="neko-prod-key-1"
```

## 3. Core Allow-list Configuration

After generating the keys, take the contents of `public.pem` and inject it into the `StrictLaunchPermitVerifier`'s allow-list in `NekoProxyCore`. Since we are using the `ProductionAuthorizationComposition`, you must ensure that the `publicKeys` dictionary passed to `CreateStartAuthorizer` contains the public key mapped to the ID `neko-prod-key-1`.

## 4. Run and Test Locally

To test the Edge Function locally:

```bash
cd E:\Github\Neko-Family-Proxy
supabase start
supabase functions serve
```

Send a test curl request:
```bash
curl -i --location --request POST 'http://127.0.0.1:54321/functions/v1/issue_launch_permit' \
  --header 'Authorization: Bearer mock-token' \
  --header 'Content-Type: application/json' \
  --data-raw '{
    "challenge": "mock-challenge-43-chars-long-1234567890123",
    "configuration_digest": "a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2c3d4e5f6a1b2",
    "target_pid": 1234
  }'
```

The response will be a valid RS256-signed JWT permit.
