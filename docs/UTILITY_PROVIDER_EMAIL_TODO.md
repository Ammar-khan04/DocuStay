# Utility provider authority letter – email and sign flow

## Implemented

- **When we send**: As soon as a property’s utility providers are saved (`POST /owners/properties/{id}/utilities`), each authority letter is emailed to that provider’s `contact_email` (or to `TEST_PROVIDER_EMAIL` in dev when `contact_email` is missing). When the **provider contact lookup** job later finds a `contact_email` for a provider that had none, we send the authority letter to that address as well.
- **Email content**: The email includes a **link to the app** (`FRONTEND_BASE_URL#/provider/authority/{token}`) where the provider can view the letter and sign it.
- **Sign flow**: Provider opens the link (no login). They see the letter, enter name/email and accept acknowledgments, then click “Sign with Dropbox Sign”. They receive an email from Dropbox Sign to complete the signature. When the document is signed, we store the signed PDF in Postgres and set `signed_at` on the authority letter.
- **Owner view**: On the property Utilities tab, the owner sees per-letter status: “Email sent”, “Signed &lt;date&gt;”, and a “View signed PDF” button when the provider has signed.

## Config

- `TEST_PROVIDER_EMAIL`: In development, used when a provider has no `contact_email`.
- `FRONTEND_BASE_URL`: Base URL of the frontend (e.g. `https://app.docustay.com`) used in the email link. If unset, dev default is `http://localhost:5173`.
- Mailgun (or SendGrid) and Dropbox Sign must be configured for sending and signing.

## Optional future work

- **Verification job**: When the *pending provider verification* job marks a provider as “approved”, we could promote them to a full provider, create an authority letter, and send the email (same flow as above). Today, pending providers are not automatically promoted to `property_utility_providers` / letters.
- **Dropbox Sign webhook**: We currently fetch the signed PDF when the owner or provider requests it. A webhook from Dropbox Sign could update `signed_at` and store the PDF as soon as the signature is complete.
