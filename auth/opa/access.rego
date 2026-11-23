package georest.access

import rego.v1

default decision := "unavailable"

decision := "unauthenticated" if {
	not claims
	keys
}

decision := "forbidden" if {
	claims
	not allowed
}

decision := "allow" if allowed

keys := response.body if {
	response := http.send({
		"method": "GET",
		"url": "http://keycloak:8080/auth/realms/georest/protocol/openid-connect/certs",
		"timeout": "1s",
		"force_cache": true,
		"force_cache_duration_seconds": 30,
		"raise_error": false,
	})
	response.status_code == 200
	count(response.body.keys) > 0
}

claims := token if {
	[verified, _, token] := io.jwt.decode_verify(input.token, {
		"cert": json.marshal(keys),
		"alg": "RS256",
		"aud": "georest-api",
		"iss": data.georest.issuer,
	})
	verified
	token.typ == "Bearer"
	is_number(token.exp)
	is_string(token.sub)
	token.sub != ""
}

allowed if {
	input.action == "read"
	input.method in {"GET", "HEAD", "OPTIONS"}
	some role in {"viewer", "editor"}
	role in claims.realm_access.roles
}

allowed if {
	input.action == "write"
	"editor" in claims.realm_access.roles
	collection := write_collection(input.method, input.path)
	collection in data.georest.editable
}

write_collection(method, path) := matches[0][1] if {
	method == "POST"
	matches := regex.find_all_string_submatch_n(`^/api/collections/([a-z][a-z0-9_-]*)/items$`, path, 1)
}

write_collection(method, path) := matches[0][1] if {
	method in {"PUT", "DELETE"}
	matches := regex.find_all_string_submatch_n(`^/api/collections/([a-z][a-z0-9_-]*)/items/[^/]+$`, path, 1)
}
