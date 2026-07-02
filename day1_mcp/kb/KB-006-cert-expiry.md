# TLS certificate expired or about to expire

**Category:** security | **Severity:** high | **Id:** KB-006

## Symptoms

Clients fail with `certificate has expired`, browsers show NET::ERR_CERT_DATE_INVALID,
service-to-service calls start failing TLS handshakes at a suspiciously round timestamp.
Kubernetes: ingress TLS secret contains an expired cert; cert-manager Certificate resources
show `Ready: False`.

## Diagnosis

1. Check the actual cert being served (not the one you think is deployed):
   `openssl s_client -connect host:443 -servername host </dev/null 2>/dev/null | openssl x509 -noout -dates -subject`
2. In Kubernetes with cert-manager: `kubectl get certificate -A` and
   `kubectl describe certificate <name>` — read the Events for renewal failures (commonly
   ACME HTTP-01 challenge blocked by ingress rules, or DNS-01 credentials expired).
3. Check who owns renewal: cert-manager, a cloud LB-managed cert, or a manually uploaded one.
   Manual certs are the ones that expire.

## Resolution

- cert-manager renewal stuck: fix the challenge path (ingress must route
  `/.well-known/acme-challenge/` to the solver), then delete the failed CertificateRequest to
  retrigger; or `kubectl cert-manager renew <cert>` with the plugin.
- Manually managed: obtain/renew the cert, update the TLS secret:
  `kubectl create secret tls <name> --cert=fullchain.pem --key=key.pem --dry-run=client -o yaml | kubectl apply -f -`
  Rolling restart of the ingress controller is normally NOT required; it watches secrets.

## Prevention

Automate issuance (cert-manager / managed certs), alert at 21 and 7 days before expiry
(blackbox exporter probe `probe_ssl_earliest_cert_expiry`), and inventory all manual certs.
