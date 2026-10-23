# K-FINCO intermediate certificate

K-FINCO serves its leaf certificate without its issuer intermediate. This public
Sectigo intermediate completes that chain; it is **not** an additional root.

- Official distribution: https://support.sectigo.com/sfc/servlet.shepherd/version/download/0681N0000068m2W
- Subject: Sectigo RSA Organization Validation Secure Server CA
- Issuer: USERTrust RSA Certification Authority
- DER SHA256: `72A34AC2B424AED3F6B0B04755B88CC027DCCC806FDDB22B4CD7C47773973EC0`
- Valid until: 2030-12-31

Only the K-FINCO HTTPS client uses this certificate. It preserves Node's original
root set, requires a complete chain to an existing root, verifies validity and
the requested hostname, and never enables partial-chain trust. Expiry or issuer
rotation fails collection visibly rather than bypassing verification.
