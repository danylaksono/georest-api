package georest.access

import rego.v1

viewer := {"realm_access": {"roles": ["viewer"]}}

editor := {"realm_access": {"roles": ["editor"]}}

create := {"action": "write", "method": "POST", "path": "/api/collections/points/items"}

test_viewer_can_read if {
	decision == "allow" with input as {"action": "read", "method": "GET"} with claims as viewer
}

test_viewer_cannot_write if {
	decision == "forbidden" with input as create with claims as viewer with data.georest.editable as ["points"]
}

test_editor_only_writes_editable_collection if {
	decision == "allow" with input as create with claims as editor with data.georest.editable as ["points"]
	decision == "forbidden" with input as create with claims as editor with data.georest.editable as ["other"]
}

test_editor_cannot_write_other_endpoints if {
	request := {"action": "write", "method": "PUT", "path": "/api/collections/points/items"}
	decision == "forbidden" with input as request with claims as editor with data.georest.editable as ["points"]
}

test_missing_jwks_fails_closed if {
	decision == "unavailable" with input as create with http.send as {"status_code": 503}
}
