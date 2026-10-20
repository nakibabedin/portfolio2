# Cloudflare Tunnel: the public ingress, as in w_notes. A cloudflared sidecar in
# the task dials out to Cloudflare, which terminates TLS for api.<domain> and
# sends requests down the tunnel to the app on localhost:8000. No load balancer,
# no certificate, no inbound port. WebSockets (the live audio ingest) pass
# through it as they are.

resource "random_id" "tunnel_secret" {
  byte_length = 35
}

resource "cloudflare_zero_trust_tunnel_cloudflared" "api" {
  account_id = var.cloudflare_account_id
  name       = "${local.name}-api"
  secret     = random_id.tunnel_secret.b64_std
  config_src = "cloudflare"
}

resource "cloudflare_zero_trust_tunnel_cloudflared_config" "api" {
  account_id = var.cloudflare_account_id
  tunnel_id  = cloudflare_zero_trust_tunnel_cloudflared.api.id

  config {
    ingress_rule {
      hostname = local.api_fqdn
      service  = "http://localhost:8000"
    }
    ingress_rule {
      service = "http_status:404"
    }
  }
}

# api.<domain> -> the tunnel. Proxying is mandatory: the cfargotunnel.com target
# is only reachable through Cloudflare's edge.
resource "cloudflare_record" "api" {
  zone_id = var.cloudflare_zone_id
  name    = var.api_subdomain
  content = cloudflare_zero_trust_tunnel_cloudflared.api.cname
  type    = "CNAME"
  proxied = true
  ttl     = 1
}
