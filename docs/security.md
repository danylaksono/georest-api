# Deployment security

Traefik is the only service that publishes host ports. It uses file-based routes over Docker DNS. Dashboard, admin, and backend operations stay private. The bundled database sits on an internal network, and application and tile processes use dedicated DB logins.

- Levels 1–2 serve public read-only data. The demo binds to loopback. Treat every published collection and tile source as accessible to clients that can reach the edge.
- Level 3 uses HTTPS. Editor permissions apply only to the tables marked editable, and Traefik checks the configured write guards. An IP guard uses the socket peer by default. Configure the edge topology before relying on a forwarded client address.
- Level 3 can protect feature and tile reads with Basic auth. Requests using authorization or cookies bypass shared caching. The internal OGC tile provider does not forward client credentials to Martin.

Generate deployment-specific passwords and keep `.env`, htpasswd files, TLS keys, and administrator DSNs out of Git. Rotate anything that was used from the old committed environment file or service configs. Those credentials were removed from the current tree. Historical revisions are retained.

Before removing write access, reconcile the grants against the new manifest and then refresh the services. Keep the dedicated reader and editor roles free of inherited privileges that could grant unexpected write access. [Configure HTTPS and grants](configuration.md#https-and-editable-collections)
