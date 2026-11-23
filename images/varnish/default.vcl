vcl 4.1;

backend default {
    .host = "martin";
    .port = "3000";
    .probe = {
        .url = "/tiles/health";
        .interval = 2s;
        .timeout = 1s;
        .window = 3;
        .threshold = 2;
        .initial = 2;
    }
}

include "/runtime/current/cache-policy.vcl";

sub vcl_recv {
    unset req.http.X-GeoREST-Cache;
    if (req.method != "GET" && req.method != "HEAD" && req.method != "OPTIONS") {
        return (synth(405));
    }
    if (req.method == "OPTIONS" || req.http.Authorization || req.http.Cookie ||
        req.url !~ "^/tiles/([a-z][a-z0-9_-]*)/[0-9]+/[0-9]+/[0-9]+([?].*)?$") {
        set req.http.X-GeoREST-Cache = "PASS";
        return (pass);
    }
}

sub vcl_backend_fetch {
    unset bereq.http.X-GeoREST-Cache;
    unset bereq.http.Authorization;
    unset bereq.http.Cookie;
}

sub vcl_backend_response {
    set beresp.grace = 0s;
    set beresp.keep = 0s;
    if (bereq.uncacheable || beresp.status != 200 ||
        beresp.http.Content-Type !~ "^(application/x-protobuf|application/vnd.mapbox-vector-tile)(;|$)" ||
        beresp.http.Content-Length == "0" || beresp.http.Set-Cookie ||
        beresp.http.Vary == "*" ||
        beresp.http.Cache-Control ~ "(?i)(no-store|no-cache|private)") {
        set beresp.uncacheable = true;
        set beresp.ttl = 0s;
        return (deliver);
    }
    call georest_cache_ttl;
}

sub vcl_deliver {
    if (req.http.X-GeoREST-Cache == "PASS") {
        set resp.http.X-Cache = "PASS";
    } elseif (obj.hits > 0) {
        set resp.http.X-Cache = "HIT";
    } else {
        set resp.http.X-Cache = "MISS";
    }
}
