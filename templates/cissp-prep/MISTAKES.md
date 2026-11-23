# Mistakes Log

| Date | Domain | Question gist | My answer | Correct | Rule / why |
|---|---|---|---|---|---|
| 2026-11-23 | D1 | Fire in the data center: FIRST priority? | Shut down servers | Evacuate personnel | Human safety always comes first, before assets or data |
| 2026-11-23 | D3 | Integrity model, "no read down, no write up" | Bell-LaPadula | Biba | BLP = confidentiality (no read up, no write down). Biba = integrity, the reverse |
| 2026-11-23 | D4 | OSI layer of a router | Layer 2 | Layer 3 | Routers use IP addresses (L3); switches and bridges use MAC addresses (L2) |
| 2026-11-23 | D5 | SSO into a partner organization's apps via SAML | Role-based access | Federated identity | Trust across organizations via SAML/OIDC = federation; RBAC = permissions inside one system |
| 2026-11-23 | D7 | RTO of 1 hour: which site? | Cold site | Hot site | Hot = minutes to hours; warm = days; cold = weeks |
